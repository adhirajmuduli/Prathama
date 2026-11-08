"""Outer/inner split generators with deterministic, leakage-safe folds.

Every generator returns ``(train_idx, test_idx)`` pairs with disjoint test
groups, ordered by sorted key so the same data always produces the same folds.
Random row splitting exists only for the missing-reconstruction setting, which
the task contract restricts (see `SETTING_SPLIT_FAMILIES`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from trendsmapp.domain.enums import SplitStrategy
from trendsmapp.errors import ValidationError

__all__ = ["Fold", "FrameTable", "generate_splits"]

#: A split fold: train and test index arrays.
Fold = tuple[np.ndarray, np.ndarray]


@dataclass(frozen=True, slots=True)
class FrameTable:
    """The per-row arrays a split generator needs."""

    station_ids: list[str]
    years: list[int]
    sectors: list[str]
    coords_m: np.ndarray  # (N, 2) projected coordinates
    timestamps: list[datetime | None]

    def __post_init__(self) -> None:
        n = len(self.station_ids)
        if not (len(self.years) == len(self.sectors) == n):
            raise ValidationError("FrameTable columns must align.")
        if self.coords_m.shape != (n, 2):
            raise ValidationError("coords_m must be (N, 2).")


def generate_splits(
    strategy: SplitStrategy,
    table: FrameTable,
    *,
    seed: int = 0,
    test_fraction: float = 0.2,
    block_size_m: float = 5_000.0,
) -> list[Fold]:
    """Generate deterministic folds for the given strategy."""
    if strategy is SplitStrategy.STATION_GROUP:
        return _group_folds(table.station_ids, "station")
    if strategy is SplitStrategy.SPATIAL_BLOCK:
        blocks = _spatial_block_ids(table.coords_m, block_size_m)
        return _group_folds([str(b) for b in blocks], "spatial block")
    if strategy is SplitStrategy.LEAVE_YEAR_OUT:
        return _group_folds([str(y) for y in table.years], "year")
    if strategy is SplitStrategy.SECTOR:
        return _group_folds(table.sectors, "sector")
    if strategy is SplitStrategy.COMBINED:
        keys = [f"{sector}|{year}" for sector, year in zip(table.sectors, table.years, strict=True)]
        return _group_folds(keys, "sector-year")
    if strategy is SplitStrategy.ROLLING_ORIGIN:
        return _rolling_origin(table.years)
    if strategy is SplitStrategy.RANDOM_ROW:
        return _random_row(len(table.station_ids), seed=seed, test_fraction=test_fraction)
    raise ValidationError(f"Unknown split strategy '{getattr(strategy, 'value', strategy)}'.")


def _group_folds(keys: list[str], label: str) -> list[Fold]:
    """Leave one group out per fold, ordered by sorted group key."""
    unique = sorted(set(keys))
    if len(unique) < 2:
        raise ValidationError(
            f"Split '{label}' needs at least two groups; found {len(unique)}.",
            details={"groups": len(unique), "label": label},
        )
    n = len(keys)
    key_index: dict[str, list[int]] = {}
    for index, key in enumerate(keys):
        key_index.setdefault(key, []).append(index)
    folds: list[Fold] = []
    for key in unique:
        test_idx = np.asarray(sorted(key_index[key]), dtype=int)
        train_idx = np.asarray(sorted(i for i in range(n) if keys[i] != key), dtype=int)
        folds.append((train_idx, test_idx))
    return folds


def _rolling_origin(years: list[int]) -> list[Fold]:
    """Train on all years before each test year."""
    unique = sorted(set(years))
    if len(unique) < 2:
        raise ValidationError("Rolling origin needs at least two years.")
    n = len(years)
    year_index: dict[int, list[int]] = {}
    for index, year in enumerate(years):
        year_index.setdefault(year, []).append(index)
    folds: list[Fold] = []
    for year in unique[1:]:
        test_idx = np.asarray(sorted(year_index[year]), dtype=int)
        train_idx = np.asarray(sorted(i for i in range(n) if years[i] < year), dtype=int)
        folds.append((train_idx, test_idx))
    return folds


def _random_row(n: int, *, seed: int, test_fraction: float) -> list[Fold]:
    """One seeded random row split; only allowed for missing-reconstruction."""
    if n < 10:
        raise ValidationError("Random row split needs at least ten rows.")
    if not 0.0 < test_fraction < 1.0:
        raise ValidationError("test_fraction must be between zero and one.")
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    test_size = max(1, round(n * test_fraction))
    test_idx = np.sort(order[:test_size])
    train_idx = np.sort(order[test_size:])
    return [(train_idx, test_idx)]


def _spatial_block_ids(coords_m: np.ndarray, block_size_m: float) -> list[int]:
    """Dense deterministic block ids from projected coordinates."""
    if block_size_m <= 0:
        raise ValidationError("block_size_m must be positive.")
    blocks = (np.asarray(coords_m, dtype=float) // block_size_m).astype(np.int64)
    _unique, inverse = np.unique(blocks, axis=0, return_inverse=True)
    return [int(value) for value in inverse]
