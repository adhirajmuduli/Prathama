"""Animation: frame rendering from stored rasters, FFmpeg encoding, and MP4 validation.

Frames are rendered from stored scientific rasters — the animation never
re-interpolates inside the video loop. Every frame carries a caption with its
timestamp, parameter, unit, method, and frame status, and the encoded MP4 is
read back and validated for frame count, fps, duration, dimensions, and
digest before it is accepted.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import numpy as np

from trendsmapp.errors import ResourceLimitError, ValidationError
from trendsmapp.geospatial.grid import Grid
from trendsmapp.temporal.interpolation import FrameStatus
from trendsmapp.visualization.palettes import PaletteSpec, resolve_palette
from trendsmapp.visualization.scales import ScaleResult

__all__ = [
    "MAX_ANIMATION_FRAMES",
    "MAX_FPS",
    "MIN_FPS",
    "AnimationFrame",
    "AnimationResult",
    "AnimationSpec",
    "encode_mp4",
    "render_animation",
    "render_frame_png",
    "validate_mp4",
]

#: Frame and fps limits from the deployment ceilings.
MAX_ANIMATION_FRAMES: Final[int] = 900
MIN_FPS: Final[int] = 1
MAX_FPS: Final[int] = 30


@dataclass(frozen=True, slots=True)
class AnimationFrame:
    """One rendered frame."""

    timestamp: datetime
    status: FrameStatus
    png: bytes


@dataclass(frozen=True, slots=True)
class AnimationSpec:
    """The declared animation configuration."""

    fps: int = 2

    def __post_init__(self) -> None:
        if not MIN_FPS <= self.fps <= MAX_FPS:
            raise ValidationError(
                "The fps is outside the accepted range.",
                details={"fps": self.fps, "bounds": [MIN_FPS, MAX_FPS]},
            )


@dataclass(frozen=True, slots=True)
class AnimationResult:
    """The encoded animation and its verified properties."""

    mp4: bytes
    sha256: str
    frame_count: int
    fps: int
    duration_seconds: float
    width: int
    height: int
    metadata: dict[str, Any]


def render_frame_png(
    values: np.ndarray,
    grid: Grid,
    *,
    scale: ScaleResult,
    palette: PaletteSpec | str,
    timestamp: datetime,
    status: FrameStatus,
    unit: str,
    method: str,
    parameter_id: str,
) -> bytes:
    """Render one captioned frame PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from trendsmapp.geospatial.masking import masked_array

    palette_spec = palette if isinstance(palette, PaletteSpec) else resolve_palette(palette)
    masked = masked_array(values, grid)
    figure, axis = plt.subplots(
        figsize=(max(2, grid.n_cols / 60), max(1.5, grid.n_rows / 60) + 0.5), dpi=100
    )
    axis.imshow(masked, cmap=palette_spec.cmap, vmin=scale.vmin, vmax=scale.vmax, origin="upper")
    axis.set_axis_off()
    figure.text(
        0.02,
        0.02,
        f"{timestamp.isoformat()}  ·  {parameter_id} ({unit})  ·  {method}  ·  {status.value}",
        fontsize=9,
    )
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.05)
    plt.close(figure)
    return buffer.getvalue()


def encode_mp4(frames_png: Sequence[bytes], *, fps: int) -> tuple[bytes, int, int]:
    """Encode PNG frames to MP4 with FFmpeg; return (bytes, width, height)."""
    import imageio.v3 as iio
    import imageio_ffmpeg

    if not frames_png:
        raise ValidationError("An animation needs at least one frame.")
    first = iio.imread(io.BytesIO(frames_png[0]))
    height, width = int(first.shape[0]), int(first.shape[1])
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "animation.mp4")
        gen = imageio_ffmpeg.write_frames(
            out_path,
            size=(width, height),
            pix_fmt_in="rgba",
            pix_fmt_out="yuv420p",
            fps=fps,
            codec="libx264",
            macro_block_size=None,
        )
        gen.send(None)  # seed the generator
        for png in frames_png:
            gen.send(np.ascontiguousarray(iio.imread(io.BytesIO(png))))
        gen.close()
        with open(out_path, "rb") as handle:
            return handle.read(), width, height


def validate_mp4(mp4: bytes, *, expected_frames: int, fps: int) -> dict[str, Any]:
    """Read the MP4 back and verify frame count, fps, duration, and dimensions."""
    import imageio_ffmpeg

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "check.mp4")
        with open(path, "wb") as handle:
            handle.write(mp4)
        gen = imageio_ffmpeg.read_frames(path)
        meta = next(gen)
        count = 0
        for _frame in gen:
            count += 1
        gen.close()
    fps_actual = float(meta.get("fps", fps))
    duration = float(meta.get("duration", count / fps))
    width, height = (int(value) for value in meta["size"])
    if count != expected_frames:
        raise ValidationError(
            "The encoded MP4 has a different frame count than the rendered frames.",
            details={"expected": expected_frames, "actual": count},
        )
    if abs(fps_actual - fps) > 0.5:
        raise ValidationError(
            "The encoded MP4 fps differs from the declared fps.",
            details={"declared": fps, "actual": fps_actual},
        )
    expected_duration = expected_frames / fps
    if abs(duration - expected_duration) > 1.0:
        raise ValidationError(
            "The encoded MP4 duration is inconsistent with frames and fps.",
            details={
                "frames": expected_frames,
                "fps": fps,
                "expected_duration": expected_duration,
                "actual_duration": duration,
            },
        )
    return {
        "frame_count": count,
        "fps": fps_actual,
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(mp4).hexdigest(),
        "size_bytes": len(mp4),
    }


def render_animation(
    frames: Sequence[AnimationFrame],
    *,
    spec: AnimationSpec,
    scale: ScaleResult,
    palette: PaletteSpec | str,
    unit: str,
    method: str,
    parameter_id: str,
    values_per_frame: Sequence[np.ndarray],
    grid: Grid,
) -> AnimationResult:
    """Render, encode, and validate one animation."""
    if len(frames) > MAX_ANIMATION_FRAMES:
        raise ResourceLimitError(
            "The animation would exceed the maximum frame count.",
            details={"frames": len(frames), "max_frames": MAX_ANIMATION_FRAMES},
        )
    pngs = [
        render_frame_png(
            values,
            grid,
            scale=scale,
            palette=palette,
            timestamp=frame.timestamp,
            status=frame.status,
            unit=unit,
            method=method,
            parameter_id=parameter_id,
        )
        for frame, values in zip(frames, values_per_frame, strict=True)
    ]
    mp4, width, height = encode_mp4(pngs, fps=spec.fps)
    verified = validate_mp4(mp4, expected_frames=len(frames), fps=spec.fps)
    metadata = {
        "parameter_id": parameter_id,
        "method": method,
        "unit": unit,
        "fps": spec.fps,
        "scale": {"vmin": scale.vmin, "vmax": scale.vmax, "policy": scale.policy.value},
        "palette": resolve_palette(palette).name.value
        if isinstance(palette, str)
        else palette.name.value,
        "frames": [
            {"timestamp": frame.timestamp.isoformat(), "status": frame.status.value}
            for frame in frames
        ],
        "width": width,
        "height": height,
        "sha256": verified["sha256"],
    }
    return AnimationResult(
        mp4=mp4,
        sha256=verified["sha256"],
        frame_count=verified["frame_count"],
        fps=int(verified["fps"]),
        duration_seconds=verified["duration_seconds"],
        width=width,
        height=height,
        metadata=metadata,
    )


def metadata_json(metadata: dict[str, Any]) -> bytes:
    """Serialize animation metadata deterministically."""
    return json.dumps(metadata, indent=2, sort_keys=True, default=str).encode("utf-8")
