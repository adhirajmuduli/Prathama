"""The versioned analysis recipe contract.

A recipe is the request document of one analysis run. It is versioned, extra
fields are forbidden, and its canonical JSON hash is recorded on every run so a
result can always be traced to the exact recipe that produced it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trendsmapp.contracts.versions import RECIPE_SCHEMA_VERSION, ensure_supported_recipe_schema
from trendsmapp.domain.enums import SpatialMethod, TemporalInterpolation
from trendsmapp.spatial.base import SpatialMethodSpec
from trendsmapp.spatial.pipeline import SpatialRecipe
from trendsmapp.temporal.pipeline import TemporalRecipe

__all__ = ["RECIPE_SCHEMA_VERSION", "Recipe", "SpatialSection", "TemporalSection", "recipe_hash"]

#: The recipe schema version this build speaks.
# Re-exported from contracts.versions for convenience.


class SpatialSection(BaseModel):
    """The spatial configuration of a recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    methods: tuple[dict[str, Any], ...] = Field(min_length=1)
    grid_resolution_m: float = Field(gt=0)
    max_grid_cells: int = Field(ge=1000, le=250_000)
    analysis_crs: str = "EPSG:32644"
    validation: str = "leave_one_station_out"
    selection_rule: str = "none"
    permitted_qc_statuses: tuple[str, ...] = ("pass", "warning")

    @model_validator(mode="after")
    def _check_methods(self) -> SpatialSection:
        """Reject method identifiers this build does not implement."""
        allowed = {method.value for method in SpatialMethod}
        seen: set[str] = set()
        for item in self.methods:
            name = item.get("method")
            if name not in allowed:
                raise ValueError(
                    f"The spatial method '{name}' is not implemented; "
                    f"implemented methods are {sorted(allowed)}."
                )
            if name in seen:
                raise ValueError(f"The method '{name}' is configured twice.")
            seen.add(name)
        if self.validation not in {"leave_one_station_out", "spatial_block", "none"}:
            raise ValueError(f"Unknown validation '{self.validation}'.")
        if self.selection_rule not in {"none", "best_rmse"}:
            raise ValueError(f"Unknown selection rule '{self.selection_rule}'.")
        return self

    def to_spatial_recipe(self) -> SpatialRecipe:
        """Return the validated spatial pipeline recipe."""
        specs = tuple(
            SpatialMethodSpec(
                method=SpatialMethod(item["method"]),
                params=dict(item.get("params") or {}),
            )
            for item in self.methods
        )
        return SpatialRecipe(
            methods=specs,
            grid_resolution_m=self.grid_resolution_m,
            max_grid_cells=self.max_grid_cells,
            analysis_crs=self.analysis_crs,
            validation=self.validation,
            selection_rule=self.selection_rule,
            permitted_qc_statuses=tuple(self.permitted_qc_statuses),
        )


class TemporalSection(BaseModel):
    """The temporal configuration of a recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution: str = "day"
    interpolation: str = "linear"
    max_gap_days: float = Field(default=60.0, gt=0)
    allow_extrapolation: bool = False
    frame_count: int = Field(default=0, ge=0, le=900)
    compute_trends: bool = True
    compute_change_points: bool = False

    def to_temporal_recipe(self, *, seed: int) -> TemporalRecipe:
        """Return the validated temporal pipeline recipe."""
        from trendsmapp.temporal.alignment import TimeResolution
        from trendsmapp.temporal.pipeline import TemporalRecipe

        return TemporalRecipe(
            resolution=TimeResolution(self.resolution),
            interpolation=TemporalInterpolation(self.interpolation),
            max_gap_days=self.max_gap_days,
            allow_extrapolation=self.allow_extrapolation,
            frame_count=self.frame_count,
            compute_trends=self.compute_trends,
            compute_change_points=self.compute_change_points,
            seed=seed,
        )


class Recipe(BaseModel):
    """One analysis recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = RECIPE_SCHEMA_VERSION
    dataset_version_id: str = Field(min_length=1)
    seed: int = Field(default=0, ge=0)
    spatial: SpatialSection
    temporal: TemporalSection | None = None

    @model_validator(mode="after")
    def _check_version(self) -> Recipe:
        """Reject a recipe schema version this build does not support."""
        ensure_supported_recipe_schema(self.schema_version)
        return self

    def canonical_json(self) -> str:
        """Return the deterministic canonical JSON of the recipe."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def recipe_hash(recipe: Recipe) -> str:
    """Return the SHA-256 of the recipe's canonical JSON."""
    return hashlib.sha256(recipe.canonical_json().encode("utf-8")).hexdigest()
