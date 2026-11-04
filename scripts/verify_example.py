from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.data_processing import normalize_observations, read_tabular_file


DATASET = ROOT / "examples" / "chilika_demo.xlsx"
EXPECTED_SHA256 = "ebfa146ad0040b41d3bb5713dba96956c6ce788eb71adf8e57b1a2357d0d7030"
EXPECTED_STATIONS = 33
EXPECTED_TIMESTAMPS = 12
EXPECTED_OBSERVATIONS = 395


def main() -> None:
    digest = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"Dataset checksum mismatch: {digest}")
    observations = normalize_observations(read_tabular_file(DATASET))
    stations = observations[["latitude", "longitude"]].drop_duplicates()
    timestamps = observations["timestamp"].nunique()
    actual = (len(stations), timestamps, len(observations))
    expected = (EXPECTED_STATIONS, EXPECTED_TIMESTAMPS, EXPECTED_OBSERVATIONS)
    if actual != expected:
        raise SystemExit(f"Dataset dimensions changed: expected {expected}, found {actual}")
    print(f"verified sha256={digest} stations={actual[0]} timestamps={actual[1]} observations={actual[2]}")


if __name__ == "__main__":
    main()
