"""Normalized IR node types (canvas mode). All EMU; immutable pydantic models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True)


class Rgba(BaseModel):
    """An 8-bit RGB colour with float alpha in ``[0, 1]``."""

    model_config = _FROZEN

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

    model_config = _FROZEN

    x: int
    y: int
    width: int
    height: int


# --------------------------------------------------------------------------- fills


class SolidFill(BaseModel):
    """A flat colour fill (``a:solidFill``)."""

    model_config = _FROZEN

    kind: Literal["solid"] = "solid"
    color: Rgba


class GradientStop(BaseModel):
    """One colour stop of a gradient; ``pos`` is a fraction in ``[0, 1]``."""

    model_config = _FROZEN

    pos: float = Field(ge=0.0, le=1.0)
    color: Rgba


class GradientFill(BaseModel):
    """A linear or radial gradient (``a:gradFill``). ``angle_deg`` is the CSS angle
    (clockwise from 12 o'clock) for linear fills; ignored when ``radial``."""

    model_config = _FROZEN

    kind: Literal["gradient"] = "gradient"
    stops: tuple[GradientStop, ...] = Field(min_length=2)
    angle_deg: float = 180.0
    radial: bool = False


class PictureFill(BaseModel):
    """A bitmap fill (``a:blipFill``). ``data`` is the raw image bytes; ``ext`` is the
    lower-case file extension (``png``/``jpeg``/``gif``). Used for native ``<img>`` and
    ``background-image:url()`` as well as the raster fallback for un-mappable elements."""

    model_config = _FROZEN

    kind: Literal["picture"] = "picture"
    data: bytes
    ext: str = "png"


type Fill = Annotated[SolidFill | GradientFill | PictureFill, Field(discriminator="kind")]


# --------------------------------------------------------------------------- stroke / effects


class Line(BaseModel):
    """A shape outline (``a:ln``). ``width_emu`` > 0; ``dash`` maps CSS border-style."""

    model_config = _FROZEN

    color: Rgba
    width_emu: int = Field(gt=0)
    dash: Literal["solid", "dash", "dot"] = "solid"


class Shadow(BaseModel):
    """A drop shadow (``a:outerShdw``/``a:innerShdw``) from CSS ``box-shadow``."""

    model_config = _FROZEN

    color: Rgba
    blur_emu: int = Field(ge=0)
    distance_emu: int = Field(ge=0)
    direction_deg: float = 90.0  # OOXML angle: 0 = right, 90 = down
    inset: bool = False


# --------------------------------------------------------------------------- text / shapes


class TextRun(BaseModel):
    """A run of text with its resolved typography."""

    model_config = _FROZEN

    text: str
    font_family: str
    size_pt: float = Field(gt=0)
    bold: bool = False
    italic: bool = False
    color: Rgba = Rgba(r=0, g=0, b=0)
    align: Literal["left", "center", "right", "justify"] = "left"


type Geometry = Literal["rect", "roundRect", "ellipse"]


class ShapeNode(BaseModel):
    """One positioned element. Stacking is the order within :attr:`SlideIR.shapes`."""

    model_config = _FROZEN

    box: Box
    geom: Geometry = "rect"
    fill: Fill | None = None
    line: Line | None = None
    shadow: Shadow | None = None
    corner_radius_emu: int = 0
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    text: TextRun | None = None


class SlideIR(BaseModel):
    """A single slide as a canvas of positioned shapes, sized in EMUs."""

    model_config = _FROZEN

    width: int
    height: int
    shapes: tuple[ShapeNode, ...]
