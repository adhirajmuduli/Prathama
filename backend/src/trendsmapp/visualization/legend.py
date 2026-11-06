"""Unit-aware legends with observed/interpolated disclosure."""

from __future__ import annotations

import hashlib
import io
from typing import Final

import numpy as np

from trendsmapp.visualization.palettes import PaletteSpec

__all__ = ["render_legend_png"]

#: Legend size in pixels.
_LEGEND_SIZE: Final[tuple[int, int]] = (240, 720)


def render_legend_png(
    *,
    vmin: float,
    vmax: float,
    unit: str,
    palette: PaletteSpec,
    title: str,
    frame_statuses: tuple[str, ...] = (),
) -> bytes:
    """Render a vertical colorbar legend PNG with unit and status disclosure."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    figure, axis = plt.subplots(figsize=(_LEGEND_SIZE[0] / 100, _LEGEND_SIZE[1] / 100), dpi=100)
    axis.imshow(gradient, aspect="auto", cmap=palette.cmap, extent=(0, 1, vmin, vmax))
    axis.set_ylabel(unit)
    axis.set_title(title)
    axis.set_xticks([])
    if frame_statuses:
        axis.set_xlabel("frames: " + ", ".join(sorted(set(frame_statuses))))
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    return buffer.getvalue()


def digest_of(payload: bytes) -> str:
    """Return the SHA-256 of a payload."""
    return hashlib.sha256(payload).hexdigest()
