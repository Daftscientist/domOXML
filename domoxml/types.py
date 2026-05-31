"""Public types for domOXML — enums, input models, and result objects.

Everything here is a pydantic model (``frozen=True``) or a ``StrEnum``. Inputs the caller
supplies (``Slide``, ``Theme``, …) are validated at the boundary; results the library
produces (``RenderResult``, ``CoverageReport``, …) are immutable, validated value objects.
"""

from __future__ import annotations

import json
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
    """How a source feature was represented across a conversion boundary."""

    NATIVE = "native"
    PARTIAL = "partial"
    RASTER = "raster"
    PRESERVED = "preserved"
    UNSUPPORTED = "unsupported"


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


class HtmlAsset(BaseModel):
    """One asset referenced by emitted HTML/CSS."""

    model_config = ConfigDict(frozen=True)

    path: str
    data: bytes


class HtmlSlide(BaseModel):
    """One deterministic browser-renderable slide fragment."""

    model_config = ConfigDict(frozen=True)

    html: str
    width_px: int
    height_px: int


class PreservedFragment(BaseModel):
    """Source OOXML retained when the reverse adapter cannot map it yet."""

    model_config = ConfigDict(frozen=True)

    part: str
    kind: str
    xml: str


class HtmlPresentation(BaseModel):
    """Per-slide HTML/CSS and assets emitted from a presentation canvas IR."""

    model_config = ConfigDict(frozen=True)

    slides: tuple[HtmlSlide, ...]
    css: str
    assets: tuple[HtmlAsset, ...] = ()
    warnings: tuple[ConversionWarning, ...] = ()
    preserved: tuple[PreservedFragment, ...] = ()

    def save(self, directory: Path) -> None:
        """Write HTML slides, shared CSS, and assets below ``directory``."""
        slides_dir = directory / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)
        (directory / "shared.css").write_text(self.css, encoding="utf-8")
        for index, slide in enumerate(self.slides, start=1):
            (slides_dir / f"slide-{index:02d}.html").write_text(slide.html, encoding="utf-8")
        for asset in self.assets:
            path = directory / asset.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(asset.data)
        if self.warnings or self.preserved:
            metadata = {
                "warnings": [warning.model_dump() for warning in self.warnings],
                "preserved": [fragment.model_dump() for fragment in self.preserved],
            }
            (directory / "metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )


class RenderResult(BaseModel):
    """The artifacts of a render. A format's field is ``None`` when it wasn't requested."""

    model_config = ConfigDict(frozen=True)

    pptx: bytes | None
    pngs: tuple[bytes, ...]
    html: HtmlPresentation | None
    coverage: CoverageReport
    warnings: tuple[ConversionWarning, ...]

    def save(self, directory: Path) -> None:
        """Write every produced artifact into ``directory``."""
        directory.mkdir(parents=True, exist_ok=True)
        if self.pptx is not None:
            (directory / "deck.pptx").write_bytes(self.pptx)
        for index, png in enumerate(self.pngs, start=1):
            (directory / f"slide-{index:02d}.png").write_bytes(png)
        if self.html is not None:
            self.html.save(directory / "html")
