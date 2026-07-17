"""Public types for domOXML — enums, input models, and result objects.

Everything here is a pydantic model (``frozen=True``) or a ``StrEnum``. Inputs the caller
supplies (``Slide``, ``Theme``, …) are validated at the boundary; results the library
produces (``RenderResult``, ``CoverageReport``, …) are immutable, validated value objects.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class Representation(StrEnum):
    """How a source visual is represented across a conversion boundary."""

    NATIVE = "native"
    DECOMPOSED = "decomposed"
    HYBRID = "hybrid"
    LAYERED = "layered"
    ELEMENT_LAYER = "element_layer"
    APPROXIMATED = "approximated"
    FAILED = "failed"


class Editability(StrEnum):
    """The strongest editing model retained by a represented source visual."""

    SEMANTIC = "semantic"
    COMPONENTS = "components"
    LAYERS = "layers"
    NONE = "none"


class SourceRetention(StrEnum):
    """How source-only data is retained for a later export to its source format."""

    NOT_REQUIRED = "not_required"
    ATTACHED = "attached"
    DETACHED = "detached"
    IGNORED = "ignored"
    LOST = "lost"


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
    """Representation, editability, and retention for one source visual."""

    model_config = ConfigDict(frozen=True)

    element: str
    representation: Representation
    editability: Editability
    source_retention: SourceRetention = SourceRetention.NOT_REQUIRED
    output_count: int = Field(default=1, ge=0)
    raster_area_emu2: int = Field(default=0, ge=0)
    reason: str = ""

    @model_validator(mode="after")
    def _representation_is_coherent(self) -> CoverageItem:
        representation = self.representation
        if representation is Representation.NATIVE:
            if self.editability is not Editability.SEMANTIC or self.output_count != 1:
                raise ValueError("native representation requires one semantic output")
        elif representation is Representation.DECOMPOSED:
            if self.editability is not Editability.COMPONENTS or self.output_count < 2:
                raise ValueError("decomposed representation requires at least two components")
        elif representation is Representation.HYBRID:
            if self.editability not in (Editability.SEMANTIC, Editability.COMPONENTS):
                raise ValueError("hybrid representation must retain semantic or component editing")
            if self.output_count < 2:
                raise ValueError("hybrid representation requires at least two outputs")
        elif representation is Representation.LAYERED:
            if self.editability is not Editability.LAYERS or self.output_count < 2:
                raise ValueError("layered representation requires at least two editable layers")
        elif representation is Representation.ELEMENT_LAYER:
            if self.editability is not Editability.LAYERS or self.output_count != 1:
                raise ValueError("element-layer representation requires one editable layer")
        elif representation is Representation.APPROXIMATED:
            if self.editability is Editability.NONE or self.output_count < 1:
                raise ValueError("approximated representation requires an editable output")
        elif representation is Representation.FAILED and (
            self.editability is not Editability.NONE or self.output_count != 0
        ):
            raise ValueError("failed representation cannot claim an editable output")

        uses_raster = representation in (
            Representation.HYBRID,
            Representation.LAYERED,
            Representation.ELEMENT_LAYER,
        )
        if uses_raster != (self.raster_area_emu2 > 0):
            raise ValueError("raster area must be positive exactly when raster layers are used")
        if representation is not Representation.NATIVE and not self.reason.strip():
            raise ValueError("non-native representation requires a reason")
        return self


class CoverageReport(BaseModel):
    """Per-source-visual representation and editability breakdown for a render."""

    model_config = ConfigDict(frozen=True)

    items: tuple[CoverageItem, ...]

    @property
    def native_ratio(self) -> float:
        """Fraction represented entirely by native primitives, including decompositions."""
        if not self.items:
            return 1.0
        native = sum(
            item.representation in (Representation.NATIVE, Representation.DECOMPOSED)
            for item in self.items
        )
        return native / len(self.items)

    @property
    def editable_ratio(self) -> float:
        """Fraction retaining semantic or component editing (1.0 if empty)."""
        if not self.items:
            return 1.0
        editable = sum(
            item.editability in (Editability.SEMANTIC, Editability.COMPONENTS)
            for item in self.items
        )
        return editable / len(self.items)

    @property
    def layered_ratio(self) -> float:
        """Fraction using any raster layer representation (0.0 if empty)."""
        if not self.items:
            return 0.0
        layered = sum(
            item.representation
            in (Representation.HYBRID, Representation.LAYERED, Representation.ELEMENT_LAYER)
            for item in self.items
        )
        return layered / len(self.items)

    @property
    def raster_area_emu2(self) -> int:
        """Total rasterized output area in squared EMUs."""
        return sum(item.raster_area_emu2 for item in self.items)

    @property
    def output_count(self) -> int:
        """Total editable and raster outputs produced for all source visuals."""
        return sum(item.output_count for item in self.items)

    def count(self, representation: Representation) -> int:
        """Count source visuals using ``representation``."""
        return sum(item.representation is representation for item in self.items)

    def count_editability(self, editability: Editability) -> int:
        """Count source visuals retaining ``editability``."""
        return sum(item.editability is editability for item in self.items)

    def count_source_retention(self, retention: SourceRetention) -> int:
        """Count source visuals with the requested source-retention state."""
        return sum(item.source_retention is retention for item in self.items)


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
    owner_node_id: str | None = None


class HtmlPresentation(BaseModel):
    """Per-slide HTML/CSS and assets emitted from a presentation canvas IR."""

    model_config = ConfigDict(frozen=True)

    slides: tuple[HtmlSlide, ...]
    css: str
    assets: tuple[HtmlAsset, ...] = ()
    warnings: tuple[ConversionWarning, ...] = ()
    preserved: tuple[PreservedFragment, ...] = ()
    coverage: CoverageReport = Field(default_factory=lambda: CoverageReport(items=()))

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
