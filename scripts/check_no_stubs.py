"""Fail when a production path contains a prohibited placeholder construct.

The rebuild plan forbids placeholder execution branches in production code. A
file that returns dummy data, raises ``NotImplementedError``, or contains an
empty ``pass`` branch can ship silently and mislead every downstream consumer,
so the repository-level check runs in pre-commit and in CI.

The scan covers the production paths of the rebuilt application only:

* ``backend/src`` and ``backend/scripts`` are parsed with the Python abstract
  syntax tree, so a mention of the word "mock" inside a docstring is not a
  finding while a real ``mock`` function definition is;
* ``frontend/src`` is scanned with conservative patterns, because a regular
  expression cannot distinguish a JavaScript identifier from prose.

The frozen prototype at the repository root is excluded on purpose: it is a
historical artifact and is documented in ``docs/legacy-audit.md``.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

PYTHON_ROOTS = (REPOSITORY_ROOT / "backend" / "src", REPOSITORY_ROOT / "backend" / "scripts")
TYPESCRIPT_ROOTS = (REPOSITORY_ROOT / "frontend" / "src",)

EXCLUDED_DIRECTORIES = {"__pycache__", ".venv", "node_modules", ".next", "dist", "build"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd"}

FORBIDDEN_IDENTIFIER_FRAGMENTS = ("mock", "dummy", "fake", "placeholder", "stub")
FORBIDDEN_IDENTIFIER_ALLOWLIST = {"stubborn"}

PYTHON_COMMENT_PATTERN = re.compile(r"#\s*(TODO|FIXME|XXX)\b", re.IGNORECASE)
TYPESCRIPT_FORBIDDEN_PATTERNS = (
    re.compile(r"throw\s+new\s+Error\(\s*[\"'`](not implemented|unimplemented|todo)"),
    re.compile(r"\bTODO\b"),
    re.compile(r"\bFIXME\b"),
)
TYPESCRIPT_IDENTIFIER_PATTERN = re.compile(r"\b(?:const|let|var|function|class)\s+([A-Za-z0-9_$]+)")


def _is_excluded(path: Path) -> bool:
    """Return whether a path is excluded from the scan."""
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    return any(part in EXCLUDED_DIRECTORIES for part in path.parts)


def _python_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield every Python file below the given roots."""
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if not _is_excluded(path):
                yield path


def _typescript_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield every TypeScript source file below the given roots."""
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.ts", "*.tsx"):
            for path in sorted(root.rglob(pattern)):
                if not _is_excluded(path) and ".test." not in path.name:
                    yield path


def _forbidden_identifier(name: str) -> bool:
    """Return whether an identifier name is a prohibited placeholder name."""
    lowered = name.lower()
    if lowered in FORBIDDEN_IDENTIFIER_ALLOWLIST:
        return False
    return any(fragment in lowered for fragment in FORBIDDEN_IDENTIFIER_FRAGMENTS)


def _scan_python(path: Path) -> list[str]:
    """Return the findings for one Python file."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: the file could not be parsed ({exc.msg})"]

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Pass):
            findings.append(f"{path}:{node.lineno}: a 'pass' branch is not allowed")
        elif isinstance(node, ast.Raise):
            exception = node.exc
            if isinstance(exception, ast.Call):
                function = exception.func
                name = getattr(function, "id", None) or getattr(function, "attr", None)
                if name == "NotImplementedError":
                    findings.append(f"{path}:{node.lineno}: 'NotImplementedError' is not allowed")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (
            _forbidden_identifier(node.name)
        ):
            findings.append(f"{path}:{node.lineno}: '{node.name}' is a placeholder name")
    for match in PYTHON_COMMENT_PATTERN.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        findings.append(f"{path}:{line}: an unresolved task marker was found")
    return findings


def _scan_typescript(path: Path) -> list[str]:
    """Return the findings for one TypeScript file."""
    source = path.read_text(encoding="utf-8")
    findings: list[str] = []
    for pattern in TYPESCRIPT_FORBIDDEN_PATTERNS:
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(f"{path}:{line}: a prohibited placeholder construct was found")
    for match in TYPESCRIPT_IDENTIFIER_PATTERN.finditer(source):
        name = match.group(1)
        if _forbidden_identifier(name):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(f"{path}:{line}: '{name}' is a placeholder name")
    return findings


def collect_findings() -> list[str]:
    """Return every finding across the production paths."""
    findings: list[str] = []
    for path in _python_files(PYTHON_ROOTS):
        findings.extend(_scan_python(path))
    for path in _typescript_files(TYPESCRIPT_ROOTS):
        findings.extend(_scan_typescript(path))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the scan and report the findings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print only the summary line",
    )
    arguments = parser.parse_args(argv)

    findings = collect_findings()
    if not arguments.quiet:
        for finding in findings:
            print(finding)
    if findings:
        print(f"check_no_stubs: {len(findings)} prohibited construct(s) found")
        return 1
    print("check_no_stubs: no prohibited constructs found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
