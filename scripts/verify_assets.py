from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "static/vendor/maplibre-gl/maplibre-gl.js": "06b392de571c99e242581b0f3f23893e6e95efd3656974d6edfd8f8599ddf362",
    "static/vendor/maplibre-gl/maplibre-gl.css": "1dae8925ee5906e442f0fd7028dded2884381b9acd7a780e5270025e09fc7c5e",
    "static/vendor/ag-grid-community/dist/ag-grid-community.min.noStyle.js": (
        "c8cbba7ae582366b7165255e5d1eb028f2adb678d302fd650dd7b55f42b56ad3"
    ),
    "static/vendor/ag-grid-community/styles/ag-grid.css": (
        "90e29873aecc6657788eaa387ae756b4001a6846c0419df55712d13b6148c70d"
    ),
    "static/vendor/ag-grid-community/styles/ag-theme-alpine.css": (
        "dabed091295a2b03dde5fd0f18b5c5583e2f319b5c41af86da7251f8e62d8ecd"
    ),
    "static/vendor/bootstrap/css/bootstrap.min.css": (
        "7f1d37f0d90b6385354c2ac10e2bb91563c46bd7a266ed351222ebcac8496c2a"
    ),
    "static/vendor/bootstrap/js/bootstrap.bundle.min.js": (
        "aa53d582f97eb594c2a5cc5824574707f9ba9837bce3046bfa5f3556860f4e04"
    ),
}


def main() -> None:
    for relative, expected in EXPECTED.items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"Asset checksum mismatch for {relative}: {actual}")
    print(f"verified {len(EXPECTED)} vendored browser assets")


if __name__ == "__main__":
    main()
