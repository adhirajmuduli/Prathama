# Performance baseline

Measured on 2026-08-22 with the working-tree code and
`python scripts/benchmark.py --repeats 3`. Raw evidence is in
[`benchmarks/latest.json`](../benchmarks/latest.json).

The 2026-08-22 rerun follows a boundary-masking fix: shapely's vectorized
`contains_xy` no longer runs against unprepared geometries, which had made
every grid mask cost O(boundary vertices) — roughly 18.8 s per surface on the
bundled 10,089-vertex Chilika coastline versus about 0.01 s prepared.

## Environment

| Field | Value |
|---|---|
| OS | Windows 10 build 26200 |
| CPU | Intel64 Family 6 Model 183, 16 logical CPUs |
| Python | 3.10.6 |

## Results

| Operation | Input | Wall time (median of 3) |
|---|---:|---:|
| Demo parse + validation | 395 observations | 0.018 s (0.015-0.018 s) |
| IDW, 160 by 160 grid | 100 stations | 0.115 s |
| IDW, 160 by 160 grid | 500 stations | 0.567 s |
| IDW, 160 by 160 grid | 1,000 stations | 1.791 s |
| KDE, 160 by 160 grid | 100 stations | 0.178 s |
| KDE, 160 by 160 grid | 500 stations | 0.872 s |
| KDE, 160 by 160 grid | 1,000 stations | 1.804 s |
| H.264 IDW MP4 export | 91 frames / 10.11 s at 9 FPS | 9.036 s |

Estimator timings include construction and masking of 25,600 grid cells.
Point-count timings are not strictly monotonic because allocation,
warm-up, and operating-system scheduling are uncontrolled. They are
engineering baselines, not universal performance guarantees.

## Interpretation and limits

- IDW and KDE execute on the server CPU; no client-side estimator is present.
- The MP4 measurement includes IDW surfaces, Matplotlib rendering, and H.264
  encoding.
- MapLibre WebGL2 is an optional display surface. Its frame rate is outside this
  scientific computation benchmark and no interactive-FPS claim is made.
- The benchmark does not provide uncertainty, accuracy, or estimator-selection
  evidence; those require a separately designed validation study.

## Reproduction

```bash
python scripts/benchmark.py
```

Use `--quick` to benchmark one IDW and one KDE surface without MP4 export.
Benchmark the release commit on deployment hardware and archive the JSON with
the manuscript supplement.
