from __future__ import annotations

import io
import math
import tempfile
from pathlib import Path
from typing import Protocol, cast

import imageio.v2 as imageio
import numpy as np
import pandas as pd
from PIL import Image

from config import settings
from utils.data_processing import DataValidationError, filter_date_range, normalize_observations, read_tabular_file
from utils.spatial_rendering import interpolate_surface, load_boundary, render_surface_png

MAX_VIDEO_FRAMES = settings.max_video_frames
ANIMATION_RESOLUTION = settings.animation_resolution


class _FrameWriter(Protocol):
    def append_data(self, image: np.ndarray) -> None: ...

    def close(self) -> None: ...


def allocate_transition_frames(gaps_seconds: list[float], total_frames: int) -> list[int]:
    """Distribute transition frames across observed intervals proportionally to duration.

    Deterministic largest-remainder rounding keeps the caller's total frame
    budget exact while giving longer gaps proportionally more playback frames,
    so animation speed reflects real elapsed time between observations.
    Every interval receives at least one frame.
    """
    count = len(gaps_seconds)
    if count == 0:
        return []
    if total_frames < count:
        raise ValueError("Total transition frames must be at least the number of intervals.")
    total_gap = sum(gaps_seconds)
    if total_gap <= 0:
        raise RuntimeError("Observed timestamps must be unique so every interval has positive length.")
    exact = [total_frames * gap / total_gap for gap in gaps_seconds]
    allocation = [max(1, math.floor(value)) for value in exact]
    remainder = total_frames - sum(allocation)
    surplus_order = sorted(range(count), key=lambda index: (-(exact[index] - math.floor(exact[index])), index))
    position = 0
    while remainder > 0:
        allocation[surplus_order[position % count]] += 1
        position += 1
        remainder -= 1
    deficit_order = sorted(range(count), key=lambda index: (allocation[index] - exact[index], index))
    while remainder < 0:
        victim = next(index for index in deficit_order if allocation[index] > 1)
        allocation[victim] -= 1
        remainder += 1
    return allocation


def fetch_data_for_animation(
    parameter: str, start_date: str, end_date: str, file_path: str | Path
) -> pd.DataFrame:
    """Load and filter observations for an animation window.

    Synchronous CPU work (file parse, normalization): callers must run it off
    the event loop, e.g. via ``asyncio.to_thread``.
    """
    observations = normalize_observations(read_tabular_file(file_path))
    available = observations["parameter"].drop_duplicates().tolist()
    if parameter and parameter in available:
        observations = observations.loc[observations["parameter"] == parameter].copy()
    elif len(available) > 1:
        raise DataValidationError(f"Unknown parameter '{parameter}'. Available parameters: {', '.join(available)}")
    return filter_date_range(observations, start_date, end_date)


def _video_frame(png: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    background = Image.new("RGB", image.size, "white")
    background.paste(image, mask=image.getchannel("A"))
    width, height = background.size
    width -= width % 2
    height -= height % 2
    return np.asarray(background.resize((width, height)))


def generate_spatiotemporal_video(
    frame: pd.DataFrame,
    fps: int,
    frames_per_transition: int,
    colormap: str,
    boundary_path: str | Path,
    method: str = "idw",
    idw_power: float = 2.0,
    kde_bandwidth_km: float = 2.0,
) -> bytes:
    if frame.empty:
        raise DataValidationError("No observations are available for the selected range.")
    if not 1 <= fps <= 30:
        raise DataValidationError("FPS must be between 1 and 30.")
    if not 1 <= frames_per_transition <= 30:
        raise DataValidationError("Transition frames must be between 1 and 30.")

    frame = frame.copy()
    frame["sampled_at"] = pd.to_datetime(frame["sampled_at"])
    timestamps = sorted(frame["sampled_at"].drop_duplicates().tolist())
    if len(timestamps) < 2:
        raise DataValidationError("Animation requires at least two observed timestamps.")
    transition_count = len(timestamps) - 1
    frame_count = transition_count * frames_per_transition + 1
    if frame_count > MAX_VIDEO_FRAMES:
        raise DataValidationError(f"Animation exceeds the {MAX_VIDEO_FRAMES}-frame prototype limit.")
    gaps_seconds = [
        (timestamps[index + 1] - timestamps[index]).total_seconds() for index in range(transition_count)
    ]
    allocations = allocate_transition_frames(gaps_seconds, transition_count * frames_per_transition)

    boundary = load_boundary(boundary_path)[0]
    minimum = float(frame["value"].min())
    maximum = float(frame["value"].max())
    fields: list[np.ndarray] = []
    extent = None
    for timestamp in timestamps:
        subset = frame.loc[frame["sampled_at"] == timestamp]
        surface, extent, _ = interpolate_surface(
            subset["longitude"].to_numpy(float),
            subset["latitude"].to_numpy(float),
            subset["value"].to_numpy(float),
            boundary,
            method=method,
            resolution=ANIMATION_RESOLUTION,
            power=idw_power,
            bandwidth_km=kde_bandwidth_km,
        )
        fields.append(surface)
    if extent is None:
        raise RuntimeError("Spatial interpolation did not produce an output extent.")

    rendered: list[np.ndarray] = []
    for index in range(len(fields) - 1):
        start = timestamps[index]
        end = timestamps[index + 1]
        steps = allocations[index]
        for step in range(steps):
            alpha = step / steps
            surface = fields[index] * (1 - alpha) + fields[index + 1] * alpha
            moment = start + (end - start) * alpha
            status = "Observed" if step == 0 else "Interpolated"
            label = f"{moment:%Y-%m-%d} | {status}"
            rendered.append(_video_frame(render_surface_png(surface, extent, minimum, maximum, colormap, label)))
    rendered.append(
        _video_frame(
            render_surface_png(
                fields[-1], extent, minimum, maximum, colormap, f"{timestamps[-1]:%Y-%m-%d} | Observed"
            )
        )
    )

    temporary = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temporary.close()
    output_path = Path(temporary.name)
    try:
        writer = cast(
            _FrameWriter,
            imageio.get_writer(output_path, fps=fps, codec="libx264", quality=7, macro_block_size=2),
        )
        try:
            for rendered_frame in rendered:
                writer.append_data(rendered_frame)
        finally:
            writer.close()
        video = output_path.read_bytes()
        if len(video) < 1_000:
            raise RuntimeError("Video encoder produced an invalid output.")
        return video
    finally:
        output_path.unlink(missing_ok=True)
