"""Trend and residual figures."""

from __future__ import annotations

import io
from collections.abc import Sequence

import numpy as np

from trendsmapp.temporal.trends import TrendEstimate

__all__ = ["trend_figure_png"]


def trend_figure_png(
    t_days: Sequence[float],
    values: Sequence[float],
    estimate: TrendEstimate,
    *,
    unit: str,
    parameter_id: str,
) -> bytes:
    """Render a trend figure: observations, Theil-Sen line, and CI band."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.asarray(t_days, dtype=float)
    v = np.asarray(values, dtype=float)
    figure, axis = plt.subplots(figsize=(6, 4), dpi=120)
    axis.scatter(t, v, s=18, label="observed")
    line_x = np.array([t.min(), t.max()])
    axis.plot(
        line_x,
        estimate.intercept + estimate.slope_per_day * line_x,
        color="black",
        label="Theil-Sen",
    )
    low, high = estimate.ci95_per_day
    axis.fill_between(
        line_x,
        estimate.intercept + low * line_x,
        estimate.intercept + high * line_x,
        color="grey",
        alpha=0.3,
        label="95% CI",
    )
    axis.set_xlabel("days since first observation")
    axis.set_ylabel(f"{parameter_id} ({unit})")
    axis.legend()
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    return buffer.getvalue()
