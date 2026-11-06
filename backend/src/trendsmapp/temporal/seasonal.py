"""Seasonal labels: calendar month, monsoon, and user-defined seasons."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

__all__ = ["Season", "SeasonSet", "label_for", "monsoon_season"]


@dataclass(frozen=True, slots=True)
class Season:
    """One named seasonal period."""

    name: str
    months: frozenset[int]


#: The default monsoon label for the region of the default boundary.
monsoon_season: Final[Season] = Season(name="monsoon", months=frozenset({6, 7, 8, 9, 10}))

#: The four meteorological seasons as a default set.
DEFAULT_SEASONS: Final[tuple[Season, ...]] = (
    Season(name="winter", months=frozenset({12, 1, 2})),
    Season(name="pre_monsoon", months=frozenset({3, 4, 5})),
    monsoon_season,
    Season(name="post_monsoon", months=frozenset({11})),
)


@dataclass(frozen=True, slots=True)
class SeasonSet:
    """A set of seasons; a month in several seasons is reported ambiguous."""

    seasons: tuple[Season, ...] = DEFAULT_SEASONS

    def label_for(self, moment: datetime) -> str | None:
        """Return the season of a month, or None when ambiguous or uncovered."""
        matches = [season.name for season in self.seasons if moment.month in season.months]
        if len(matches) == 1:
            return matches[0]
        return None


def label_for(moment: datetime, seasons: Sequence[Season] = DEFAULT_SEASONS) -> str | None:
    """Return the season label of a timestamp under the default seasons."""
    return SeasonSet(tuple(seasons)).label_for(moment)
