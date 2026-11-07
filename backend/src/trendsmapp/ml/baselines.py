"""Baseline models: mean, median, station climatology, seasonal climatology, persistence.

Baselines are implemented here, not imported: they are one-liners over the
training target, and every ML model must be compared against them. Station and
seasonal climatology use the training groups; an unseen group falls back to the
global training mean, which is recorded as a warning by the training loop.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

__all__ = [
    "MeanBaseline",
    "MedianBaseline",
    "PersistenceBaseline",
    "SeasonalClimatology",
    "StationClimatology",
]


class MeanBaseline:
    """Predicts the training mean."""

    def __init__(self) -> None:
        self._value = 0.0

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None:
        """Fit the training mean."""
        self._value = float(np.mean(np.asarray(y, dtype=float)))

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray:
        """Return the training mean for every row."""
        return np.full(len(x), self._value, dtype=float)


class MedianBaseline:
    """Predicts the training median."""

    def __init__(self) -> None:
        self._value = 0.0

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None:
        """Fit the training median."""
        self._value = float(np.median(np.asarray(y, dtype=float)))

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray:
        """Return the training median for every row."""
        return np.full(len(x), self._value, dtype=float)


class PersistenceBaseline:
    """Predicts each row's own last observed value (first feature column)."""

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None:
        """Persistence needs no training."""

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray:
        """Return the first feature column as the prediction."""
        return np.asarray(x, dtype=float)[:, 0]


class StationClimatology:
    """Per-station training mean; unseen stations get the global mean."""

    def __init__(self) -> None:
        self._global = 0.0
        self._by_station: dict[str, float] = {}

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None:
        """Fit per-station means from the training groups."""
        values = np.asarray(y, dtype=float)
        self._global = float(np.mean(values))
        if groups is None:
            return
        sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
        for group, value in zip(groups, values, strict=True):
            entry = sums[group]
            entry[0] += float(value)
            entry[1] += 1
        self._by_station = {group: total / count for group, (total, count) in sums.items()}

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray:
        """Predict per-row using the row's station group when known."""
        if groups is None:
            return np.full(len(x), self._global, dtype=float)
        return np.asarray(
            [self._by_station.get(group, self._global) for group in groups],
            dtype=float,
        )


class SeasonalClimatology(StationClimatology):
    """Per-station per-season training mean."""

    def __init__(self) -> None:
        super().__init__()
        self._by_key: dict[tuple[str, int], float] = {}

    def fit(self, x: np.ndarray, y: np.ndarray, groups: list[str] | None = None) -> None:
        """Fit per (station, season) means; season is the second feature column."""
        values = np.asarray(y, dtype=float)
        features = np.asarray(x, dtype=float)
        self._global = float(np.mean(values))
        if groups is None or features.shape[1] < 2:
            return
        sums: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0])
        for group, season, value in zip(groups, features[:, 1].astype(int), values, strict=True):
            entry = sums[(group, int(season))]
            entry[0] += float(value)
            entry[1] += 1
        self._by_key = {key: total / count for key, (total, count) in sums.items()}

    def predict(self, x: np.ndarray, groups: list[str] | None = None) -> np.ndarray:
        """Predict per-row from the (station, season) key of the prediction rows."""
        features = np.asarray(x, dtype=float)
        if groups is None or features.shape[1] < 2:
            return np.full(len(x), self._global, dtype=float)
        return np.asarray(
            [
                self._by_key.get((group, int(season)), self._by_station.get(group, self._global))
                for group, season in zip(groups, features[:, 1].astype(int), strict=True)
            ],
            dtype=float,
        )
