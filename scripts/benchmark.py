from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar, TypedDict

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.animation_generator import generate_spatiotemporal_video
from utils.data_processing import normalize_observations, read_tabular_file
from utils.spatial_rendering import interpolate_surface, load_boundary

ResultT = TypeVar("ResultT")


class Timing(TypedDict):
    repeats: int
    seconds_min: float
    seconds_median: float
    seconds_max: float


def timed(function: Callable[[], ResultT], repeats: int = 1) -> tuple[ResultT, Timing]:
    if repeats < 1:
        raise ValueError("Benchmark repeats must be at least one.")
    started = time.perf_counter()
    result = function()
    durations = [time.perf_counter() - started]
    for _ in range(1, repeats):
        started = time.perf_counter()
        result = function()
        durations.append(time.perf_counter() - started)
    return result, {
        "repeats": repeats,
        "seconds_min": min(durations),
        "seconds_median": float(np.median(durations)),
        "seconds_max": max(durations),
    }


def synthetic_points(count: int, seed: int = 20260720) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    generator = np.random.default_rng(seed)
    longitude = generator.uniform(85.03, 85.27, count)
    latitude = generator.uniform(19.43, 19.67, count)
    values = 2.5 + np.sin(longitude * 20) + np.cos(latitude * 18) + generator.normal(0, 0.1, count)
    return longitude, latitude, values


def animation_frame() -> pd.DataFrame:
    rows = []
    coordinates = [(19.45, 85.05), (19.45, 85.25), (19.65, 85.05), (19.65, 85.25)]
    for time_index, timestamp in enumerate(pd.date_range("2024-01-01", periods=4, freq="MS")):
        for station_index, (latitude, longitude) in enumerate(coordinates):
            rows.append({
                "latitude": latitude,
                "longitude": longitude,
                "value": float(station_index + time_index),
                "sampled_at": timestamp,
            })
    return pd.DataFrame(rows)


def run(full: bool, repeats: int = 3) -> dict:
    boundary_path = ROOT / "static" / "data" / "export.geojson"
    boundary = load_boundary(boundary_path)[0]
    demo_path = ROOT / "examples" / "chilika_demo.xlsx"
    observations, validation = timed(
        lambda: normalize_observations(read_tabular_file(demo_path)), repeats=max(repeats, 1)
    )

    spatial = {"idw": {}, "kde": {}}
    for method in spatial:
        for point_count in ([100, 500, 1_000] if full else [100]):
            longitude, latitude, values = synthetic_points(point_count)
            _, measurement = timed(
                lambda: interpolate_surface(
                    longitude, latitude, values, boundary, method=method, resolution=160, bandwidth_km=2.0
                ),
                repeats=repeats,
            )
            spatial[method][str(point_count)] = {**measurement, "grid_cells": 25_600}
    animation = None
    if full:
        video, animation_measurement = timed(
            lambda: generate_spatiotemporal_video(
                animation_frame(), 9, 30, "viridis", boundary_path, "idw"
            ),
            repeats=repeats,
        )
        animation = {
            **animation_measurement,
            "duration_seconds": 91 / 9,
            "frames": 91,
            "bytes": len(video),
        }

    return {
        "schema_version": 2,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "logical_cpus": __import__("os").cpu_count(),
        },
        "demo_validation": {**validation, "normalized_observations": len(observations)},
        "scientific_surfaces_160x160": spatial,
        "mp4_export": animation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible Trendsmapp CPU/API preparation benchmarks.")
    parser.add_argument("--quick", action="store_true", help="skip large and MP4 measurements")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="measurements per item so min/median/max are meaningful (1 reproduces single-shot runs)",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "latest.json")
    arguments = parser.parse_args()
    if arguments.repeats < 1:
        parser.error("--repeats must be at least one.")
    results = run(full=not arguments.quick, repeats=arguments.repeats)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
