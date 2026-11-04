import json

import pandas as pd

from utils.animation_generator import generate_spatiotemporal_video


def test_generates_valid_mp4(tmp_path):
    boundary = tmp_path / "boundary.geojson"
    boundary.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[85.0, 19.4], [85.3, 19.4], [85.3, 19.7], [85.0, 19.7], [85.0, 19.4]]],
    }), encoding="utf-8")
    rows = []
    for timestamp, offset in [("2024-01-01", 0.0), ("2024-02-01", 1.0)]:
        for latitude, longitude, value in [
            (19.45, 85.05, 1.0), (19.45, 85.25, 2.0), (19.65, 85.05, 3.0), (19.65, 85.25, 4.0)
        ]:
            rows.append({
                "latitude": latitude,
                "longitude": longitude,
                "value": value + offset,
                "sampled_at": timestamp,
            })
    video = generate_spatiotemporal_video(pd.DataFrame(rows), 2, 1, "viridis", boundary)
    assert len(video) > 1_000
    assert b"ftyp" in video[:64]
