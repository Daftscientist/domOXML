"""Public types for domOXML — enums, input models, and result objects.

Everything here is a pydantic model (``frozen=True``) or a ``StrEnum``. Inputs the caller
supplies (``Slide``, ``Theme``, …) are validated at the boundary; results the library
produces (``RenderResult``, ``CoverageReport``, …) are immutable, validated value objects.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- enums


class OutputFormat(StrEnum):
    """A render target. v0 emits PPTX, PNG, and normalized HTML."""

    PPTX = "pptx"
    PNG = "png"
    HTML = "html"


class SlideSize(StrEnum):
    """A standard PowerPoint slide preset."""

    WIDE_16_9 = "16:9"
    STANDARD_4_3 = "4:3"
    WIDE_16_10 = "16:10"

    @property
    def dimensions_in(self) -> tuple[float, float]:
        """Slide ``(width, height)`` in inches."""
        return _SLIDE_DIMENSIONS_IN[self]


_SLIDE_DIMENSIONS_IN: dict[SlideSize, tuple[float, float]] = {
    SlideSize.WIDE_16_9: (13.333, 7.5),
    SlideSize.STANDARD_4_3: (10.0, 7.5),
    SlideSize.WIDE_16_10: (10.0, 6.25),
}


class Transition(StrEnum):
    """A slide transition (compiled into the PresentationML, not authored in CSS)."""

    NONE = "none"
    FADE = "fade"
    PUSH = "push"
    WIPE = "wipe"
    COVER = "cover"
    SPLIT = "split"
    CUT = "cut"
    ZOOM = "zoom"
    DISSOLVE = "dissolve"
    MORPH = "morph"


class Disposition(StrEnum):
    """Whether an element mapped to a native OOXML object or had to be rasterised."""

    NATIVE = "native"
    RASTER = "raster"


# --------------------------------------------------------------------------- input models


class CustomSize(BaseModel):
    """A custom slide size in inches, validated against PowerPoint's 56in limit."""

    width_in: float = Field(gt=0, le=56.0)
    height_in: float = Field(gt=0, le=56.0)


type SizeSpec = SlideSize | CustomSize


class Palette(BaseModel):
    """Design-token colour palette — any CSS colour string."""

    background: str = "#ffffff"
    foreground: str = "#0b0b0c"
    accent: str = "#4f46e5"
    muted: str = "#6b7280"


class Fonts(BaseModel):
    """Font families; resolved (incl. web fonts) and embedded at render time."""

    heading: str = "Inter"
    body: str = "Inter"


class Theme(BaseModel):
    """Structured design tokens, compiled into the shared stylesheet."""

    palette: Palette = Field(default_factory=Palette)
    fonts: Fonts = Field(default_factory=Fonts)


class Slide(BaseModel):
    """One slide, authored as an HTML fragment (styled by the deck theme / CSS)."""

    html: str
    transition: Transition | None = None
    size: SizeSpec | None = None  # per-slide override of the deck size


# --------------------------------------------------------------------------- results


class CoverageItem(BaseModel):
    """How one source element was rendered into the .pptx."""

    model_config = ConfigDict(frozen=True)

    element: str
    disposition: Disposition
    reason: str = ""  # why it rasterised, when applicable


class CoverageReport(BaseModel):
    """Per-element native-vs-raster breakdown for a render."""

    model_config = ConfigDict(frozen=True)

    items: tuple[CoverageItem, ...]

    @property
    def native_ratio(self) -> float:
        """Fraction of elements that mapped to native OOXML (1.0 if empty)."""
        if not self.items:
            return 1.0
        native = sum(1 for item in self.items if item.disposition is Disposition.NATIVE)
        return native / len(self.items)


class ConversionWarning(BaseModel):
    """A non-fatal issue encountered during conversion."""

    model_config = ConfigDict(frozen=True)

    message: str
    element: str = ""


class RenderResult(BaseModel):
    """The artifacts of a render. A format's field is ``None`` when it wasn't requested."""

    model_config = ConfigDict(frozen=True)

    pptx: bytes | None
    pngs: tuple[bytes, ...]
    html: str | None
    coverage: CoverageReport
    warnings: tuple[ConversionWarning, ...]

    def save(self, directory: Path) -> None:
        """Write every produced artifact into ``directory``."""
        raise NotImplementedError
