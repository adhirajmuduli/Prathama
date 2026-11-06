"""Approved perceptually suitable palettes and reversal rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from trendsmapp.errors import ValidationError

__all__ = ["PALETTES", "PaletteName", "PaletteSpec", "resolve_palette"]


class PaletteName(StrEnum):
    """The approved palettes."""

    VIRIDIS = "viridis"
    CIVIDIS = "cividis"
    MAGMA = "magma"
    PLASMA = "plasma"
    INFERNO = "inferno"


#: The approved palettes, all perceptually uniform and colorblind-safe where noted.
PALETTES: Final[dict[PaletteName, str]] = {
    PaletteName.VIRIDIS: "viridis (perceptually uniform, colorblind-safe)",
    PaletteName.CIVIDIS: "cividis (colorblind-safe)",
    PaletteName.MAGMA: "magma (perceptually uniform)",
    PaletteName.PLASMA: "plasma (perceptually uniform)",
    PaletteName.INFERNO: "inferno (perceptually uniform)",
}


@dataclass(frozen=True, slots=True)
class PaletteSpec:
    """A resolved palette."""

    name: PaletteName
    cmap: str
    reversed: bool


def resolve_palette(name: str, *, reversed: bool = False) -> PaletteSpec:
    """Resolve a palette name, rejecting unapproved ones."""
    try:
        palette = PaletteName(name)
    except ValueError as exc:
        raise ValidationError(
            f"The palette '{name}' is not approved.",
            details={"approved": sorted(p.value for p in PALETTES)},
        ) from exc
    cmap = palette.value + ("_r" if reversed else "")
    return PaletteSpec(name=palette, cmap=cmap, reversed=reversed)
