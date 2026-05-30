"""Normalized IR node types (canvas mode). All EMU; immutable pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Rgba(BaseModel):
    """An 8-bit RGB colour with float alpha in ``[0, 1]``."""

    model_config = ConfigDict(frozen=True)

    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)
    a: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def hex(self) -> str:
        """Uppercase 6-digit hex (``RRGGBB``), no ``#`` — DrawingML's ``srgbClr`` form."""
        return f"{self.r:02X}{self.g:02X}{self.b:02X}"


class Box(BaseModel):
    """An axis-aligned position and size, in EMUs."""

    model_config = ConfigDict(frozen=True)

    x: int
    y: int
    width: int
    height: int


class TextRun(BaseModel):
    """A run of text with its resolved typography."""

    model_config = ConfigDict(frozen=True)

    text: str
    font_family: str
    size_pt: float
    bold: bool = False
    italic: bool = False
    color: Rgba = Rgba(r=0, g=0, b=0)
    align: str = "left"  # left | center | right | justify


class ShapeNode(BaseModel):
    """One positioned element. Stacking is the order within :attr:`SlideIR.shapes`."""

    model_config = ConfigDict(frozen=True)

    box: Box
    fill: Rgba | None = None
    corner_radius_emu: int = 0
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    text: TextRun | None = None


class SlideIR(BaseModel):
    """A single slide as a canvas of positioned shapes, sized in EMUs."""

    model_config = ConfigDict(frozen=True)

    width: int
    height: int
    shapes: tuple[ShapeNode, ...]
