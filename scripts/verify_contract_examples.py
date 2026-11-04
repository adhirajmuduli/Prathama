"""Validate the committed contract examples against the running backend.

The examples in ``contracts/examples`` are the payloads a client sees. They are
checked against the live application so that a change in the API cannot pass CI
while the committed examples keep describing the old contract.

The script starts the FastAPI application in-process with a temporary SQLite
database and a temporary local object store, requests every documented
endpoint, and compares the response with the committed example. The error
envelope is additionally validated against the Pydantic contract model.

Run it with the backend environment::

    cd backend && uv run python ../scripts/verify_contract_examples.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = REPOSITORY_ROOT / "backend" / "src"
EXAMPLES_DIRECTORY = REPOSITORY_ROOT / "contracts" / "examples"

if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

import httpx  # noqa: E402

from trendsmapp.api.app import create_app  # noqa: E402
from trendsmapp.contracts.api_errors import ErrorEnvelope  # noqa: E402
from trendsmapp.settings import Settings  # noqa: E402

#: The endpoint that produces each committed example.
EXAMPLE_ENDPOINTS: dict[str, str] = {
    "health_live.json": "/api/v1/health/live",
    "health_ready.json": "/api/v1/health/ready",
    "capabilities.json": "/api/v1/capabilities",
    "contract_versions.json": "/api/v1/contracts/versions",
}


def _load(path: Path) -> Any:
    """Return the parsed JSON document at ``path``."""
    return json.loads(path.read_text(encoding="utf-8"))


async def _live_payloads(settings: Settings) -> dict[str, Any]:
    """Return the live response of every documented endpoint."""
    application = create_app(settings=settings)
    payloads: dict[str, Any] = {}
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for filename, endpoint in EXAMPLE_ENDPOINTS.items():
                response = await client.get(endpoint)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"{endpoint} answered with status {response.status_code}"
                    )
                payloads[filename] = response.json()
    return payloads


def _render(payload: Any) -> str:
    """Return the deterministic JSON representation of an example payload."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


async def update_examples() -> list[str]:
    """Rewrite every committed example from the live API and return the findings."""
    findings: list[str] = []
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        settings = Settings(
            environment="development",
            database_url=f"sqlite+aiosqlite:///{(root / 'contract.db').as_posix()}",
            object_store_backend="local",
            local_storage_root=root / "objects",
        )
        live = await _live_payloads(settings)

    for filename, payload in live.items():
        path = EXAMPLES_DIRECTORY / filename
        path.write_text(_render(payload), encoding="utf-8")
        print(f"verify_contract_examples: updated {path.name}")
    return findings


async def verify() -> list[str]:
    """Return the list of findings; an empty list means the examples are current."""
    findings: list[str] = []
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        settings = Settings(
            environment="development",
            database_url=f"sqlite+aiosqlite:///{(root / 'contract.db').as_posix()}",
            object_store_backend="local",
            local_storage_root=root / "objects",
        )
        live = await _live_payloads(settings)

    for filename, expected in live.items():
        path = EXAMPLES_DIRECTORY / filename
        if not path.exists():
            findings.append(f"{path}: the committed example is missing")
            continue
        committed = _load(path)
        if committed != expected:
            findings.append(f"{path}: the committed example no longer matches the API response")

    envelope_path = EXAMPLES_DIRECTORY / "error_envelope.json"
    if not envelope_path.exists():
        findings.append(f"{envelope_path}: the committed example is missing")
    else:
        try:
            ErrorEnvelope.model_validate(_load(envelope_path))
        except Exception as exc:  # noqa: BLE001 - the finding is the validation message
            findings.append(f"{envelope_path}: {exc}")

    unknown = {
        path.name
        for path in EXAMPLES_DIRECTORY.glob("*.json")
        if path.name not in EXAMPLE_ENDPOINTS and path.name != "error_envelope.json"
    }
    for name in sorted(unknown):
        findings.append(f"{EXAMPLES_DIRECTORY / name}: the example is not verified by this script")

    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the verification and report the findings."""
    if "--update" in (argv if argv is not None else sys.argv[1:]):
        findings = asyncio.run(update_examples())
        if findings:
            for finding in findings:
                print(finding)
            return 1
        return 0
    findings = asyncio.run(verify())
    for finding in findings:
        print(finding)
    if findings:
        print(f"verify_contract_examples: {len(findings)} finding(s)")
        return 1
    print("verify_contract_examples: every committed example matches the API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
