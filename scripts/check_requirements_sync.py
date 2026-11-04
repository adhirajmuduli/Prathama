from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator:
            raise SystemExit(f"{path.name} must use exact 'name==version' pins; found: {line}")
        pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def main() -> None:
    """Fail when any direct requirement is missing or drifts from the lock."""
    direct = _pins(ROOT / "requirements.txt")
    locked = _pins(ROOT / "requirements.lock.txt")
    drift = [
        f"{name}=={version} is not pinned identically in requirements.lock.txt"
        for name, version in sorted(direct.items())
        if locked.get(name) != version
    ]
    if drift:
        print("\n".join(drift), file=sys.stderr)
        raise SystemExit("requirements.txt and requirements.lock.txt disagree; regenerate the lock.")
    print(f"requirements sync verified ({len(direct)} direct pins present in lock)")


if __name__ == "__main__":
    main()
