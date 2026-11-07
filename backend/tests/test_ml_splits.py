"""Tests for the split generators: disjoint folds, determinism, no leakage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from trendsmapp.domain.enums import SplitStrategy
from trendsmapp.errors import ValidationError
from trendsmapp.ml.splits import FrameTable, generate_splits

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _table() -> FrameTable:
    stations = [f"st{i % 4}" for i in range(24)]
    years = [2022 + (i % 3) for i in range(24)]
    sectors = [f"s{i % 2}" for i in range(24)]
    coords = np.asarray(
        [(960_000 + (i % 6) * 4_000.0, 2_180_000 + (i // 6) * 4_000.0) for i in range(24)]
    )
    timestamps = [T0 + timedelta(days=i) for i in range(24)]
    return FrameTable(
        station_ids=stations, years=years, sectors=sectors, coords_m=coords, timestamps=timestamps
    )


def _assert_disjoint(folds: list) -> None:
    for train_idx, test_idx in folds:
        assert len(np.intersect1d(train_idx, test_idx)) == 0
        assert len(train_idx) + len(test_idx) == 24


class TestSplits:
    def test_station_group_holds_out_whole_stations(self) -> None:
        folds = generate_splits(SplitStrategy.STATION_GROUP, _table())
        assert len(folds) == 4
        _assert_disjoint(folds)
        table = _table()
        for train_idx, test_idx in folds:
            test_stations = {table.station_ids[i] for i in test_idx}
            train_stations = {table.station_ids[i] for i in train_idx}
            assert test_stations.isdisjoint(train_stations)
            assert len(test_stations) == 1

    def test_spatial_block_holds_out_whole_blocks(self) -> None:
        folds = generate_splits(SplitStrategy.SPATIAL_BLOCK, _table(), block_size_m=4_000.0)
        assert len(folds) >= 2
        _assert_disjoint(folds)

    def test_leave_year_out(self) -> None:
        folds = generate_splits(SplitStrategy.LEAVE_YEAR_OUT, _table())
        assert len(folds) == 3
        _assert_disjoint(folds)
        table = _table()
        for train_idx, test_idx in folds:
            assert {table.years[i] for i in test_idx}.isdisjoint(
                {table.years[i] for i in train_idx}
            )

    def test_rolling_origin_never_trains_on_future_years(self) -> None:
        folds = generate_splits(SplitStrategy.ROLLING_ORIGIN, _table())
        table = _table()
        for train_idx, test_idx in folds:
            if len(train_idx) == 0:
                continue
            assert max(table.years[i] for i in train_idx) < min(table.years[i] for i in test_idx)

    def test_sector_and_combined(self) -> None:
        sector_folds = generate_splits(SplitStrategy.SECTOR, _table())
        assert len(sector_folds) == 2
        combined = generate_splits(SplitStrategy.COMBINED, _table())
        assert len(combined) >= 2
        _assert_disjoint(combined)

    def test_random_row_is_seeded_and_single(self) -> None:
        table = _table()
        first = generate_splits(SplitStrategy.RANDOM_ROW, table, seed=5)
        second = generate_splits(SplitStrategy.RANDOM_ROW, table, seed=5)
        assert len(first) == 1
        np.testing.assert_array_equal(first[0][0], second[0][0])
        np.testing.assert_array_equal(first[0][1], second[0][1])
        _assert_disjoint(first)

    def test_deterministic_across_calls(self) -> None:
        table = _table()
        for strategy in (
            SplitStrategy.STATION_GROUP,
            SplitStrategy.SPATIAL_BLOCK,
            SplitStrategy.LEAVE_YEAR_OUT,
            SplitStrategy.ROLLING_ORIGIN,
            SplitStrategy.SECTOR,
            SplitStrategy.COMBINED,
        ):
            first = generate_splits(strategy, table)
            second = generate_splits(strategy, table)
            assert len(first) == len(second)
            for (a_train, a_test), (b_train, b_test) in zip(first, second, strict=True):
                np.testing.assert_array_equal(a_train, b_train)
                np.testing.assert_array_equal(a_test, b_test)

    def test_too_few_groups_rejected(self) -> None:
        table = FrameTable(
            station_ids=["only"] * 10,
            years=[2024] * 10,
            sectors=["s"] * 10,
            coords_m=np.zeros((10, 2)),
            timestamps=[T0] * 10,
        )
        with pytest.raises(ValidationError):
            generate_splits(SplitStrategy.STATION_GROUP, table)

    def test_unknown_strategy_rejected(self) -> None:
        with pytest.raises(ValidationError):
            generate_splits("bogus", _table())  # type: ignore[arg-type]
