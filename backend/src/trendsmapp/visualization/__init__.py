"""Public visualization exports.

The visualization layer converts stored scientific artifacts into web and
publication outputs. It never recalculates the science: it reads rasters and
series that the analysis pipeline already produced and stored.
"""

from __future__ import annotations

from trendsmapp.visualization.animation import (
    MAX_ANIMATION_FRAMES,
    MAX_FPS,
    MIN_FPS,
    AnimationFrame,
    AnimationResult,
    AnimationSpec,
    encode_mp4,
    metadata_json,
    render_animation,
    render_frame_png,
    validate_mp4,
)
from trendsmapp.visualization.figures import trend_figure_png
from trendsmapp.visualization.heatmap import render_heatmap_png
from trendsmapp.visualization.legend import render_legend_png
from trendsmapp.visualization.palettes import PALETTES, PaletteName, PaletteSpec, resolve_palette
from trendsmapp.visualization.scales import (
    ROBUST_PERCENTILE,
    ScalePolicy,
    ScaleResult,
    compute_scale,
)

__all__ = [
    "MAX_ANIMATION_FRAMES",
    "MAX_FPS",
    "MIN_FPS",
    "PALETTES",
    "ROBUST_PERCENTILE",
    "AnimationFrame",
    "AnimationResult",
    "AnimationSpec",
    "PaletteName",
    "PaletteSpec",
    "ScalePolicy",
    "ScaleResult",
    "compute_scale",
    "encode_mp4",
    "metadata_json",
    "render_animation",
    "render_frame_png",
    "render_heatmap_png",
    "render_legend_png",
    "resolve_palette",
    "trend_figure_png",
    "validate_mp4",
]
