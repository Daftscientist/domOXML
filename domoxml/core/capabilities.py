"""Machine-readable conversion capability fixtures and structural assertions."""

from __future__ import annotations

import importlib
import io
import tomllib
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domoxml.types import (
    ConversionWarning,
    CoverageReport,
    HtmlPresentation,
    RenderResult,
    Representation,
)

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
    "dx": "urn:domoxml:canvas-ir:1",
}


def _xpath_count(xml: bytes, xpath: str) -> int:
    """Evaluate XPath behind one narrow boundary around lxml's missing type stubs."""
    etree: Any = importlib.import_module("lxml.etree")
    root: Any = etree.fromstring(xml)
    matches: list[Any] = list(root.xpath(xpath, namespaces=_NS))
    return len(matches)


class CapabilityDirection(StrEnum):
    """Which conversion direction a fixture exercises."""

    FORWARD = "forward"
    REVERSE = "reverse"
    BOTH = "both"


class XmlExpectation(BaseModel):
    """An XPath assertion against one OOXML package part."""

    model_config = ConfigDict(frozen=True)

    part: str
    xpath: str
    min_count: int = Field(default=1, ge=0)


def _empty_representation_counts() -> dict[Representation, int]:
    return {}


class CapabilityExpected(BaseModel):
    """Structural behavior expected from a capability fixture."""

    model_config = ConfigDict(frozen=True)

    min_representation: dict[Representation, int] = Field(
        default_factory=_empty_representation_counts
    )
    max_representation: dict[Representation, int] = Field(
        default_factory=_empty_representation_counts
    )
    warnings: tuple[str, ...] = ()
    required_parts: tuple[str, ...] = ()
    xml: tuple[XmlExpectation, ...] = ()

    @model_validator(mode="after")
    def _representation_bounds_are_coherent(self) -> CapabilityExpected:
        for bounds in (self.min_representation, self.max_representation):
            if any(count < 0 for count in bounds.values()):
                raise ValueError("representation counts cannot be negative")
        for representation, minimum in self.min_representation.items():
            maximum = self.max_representation.get(representation)
            if maximum is not None and minimum > maximum:
                raise ValueError(f"minimum {representation.value} count cannot exceed its maximum")
        return self


class CapabilityVisual(BaseModel):
    """Optional visual thresholds consumed by fidelity tooling as it grows."""

    model_config = ConfigDict(frozen=True)

    source_to_pptx_min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    source_to_pptx_min_regional_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    source_to_pptx_min_structural_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    pptx_to_html_min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    pptx_to_html_min_regional_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    pptx_to_html_min_structural_similarity: float | None = Field(default=None, ge=0.0, le=1.0)


class CapabilityReverseExpected(BaseModel):
    """Structural behavior required after ingesting the fixture's PPTX."""

    model_config = ConfigDict(frozen=True)

    expected_slides: int = Field(default=1, ge=1)
    html_contains: tuple[str, ...] = ()
    max_warnings: int = Field(default=0, ge=0)
    max_preserved: int = Field(default=0, ge=0)
    roundtrip: bool = True


class CapabilityFixture(BaseModel):
    """One isolated feature probe loaded from ``capability.toml``."""

    model_config = ConfigDict(frozen=True)

    id: str
    direction: CapabilityDirection
    html: str = ""
    pptx: bytes | None = Field(default=None, exclude=True)
    expected: CapabilityExpected = Field(default_factory=CapabilityExpected)
    reverse: CapabilityReverseExpected = Field(default_factory=CapabilityReverseExpected)
    visual: CapabilityVisual = Field(default_factory=CapabilityVisual)
    visual_exclusion: str | None = None

    @model_validator(mode="after")
    def _sources_match_direction(self) -> CapabilityFixture:
        if (
            self.direction in (CapabilityDirection.FORWARD, CapabilityDirection.BOTH)
            and not self.html.strip()
        ):
            raise ValueError(f"{self.direction} fixture requires non-empty HTML")
        if self.direction is CapabilityDirection.REVERSE and self.pptx is None:
            raise ValueError("reverse fixture requires pptx_file")
        reverse_visual = any(
            threshold is not None
            for threshold in (
                self.visual.pptx_to_html_min_similarity,
                self.visual.pptx_to_html_min_regional_similarity,
                self.visual.pptx_to_html_min_structural_similarity,
            )
        )
        if self.direction in (
            CapabilityDirection.REVERSE,
            CapabilityDirection.BOTH,
        ) and reverse_visual == bool(self.visual_exclusion):
            raise ValueError(
                "reverse capability requires visual thresholds or one visual_exclusion"
            )
        return self


def _load_fixture(path: Path) -> CapabilityFixture:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    html_file = raw.pop("html_file", None)
    if html_file is not None and not isinstance(html_file, str):
        raise ValueError(f"{path}: html_file must be a string")
    html_path = path.parent / (html_file or "slide.html")
    raw["html"] = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    pptx_file = raw.pop("pptx_file", None)
    if pptx_file is not None and not isinstance(pptx_file, str):
        raise ValueError(f"{path}: pptx_file must be a string")
    raw["pptx"] = (path.parent / pptx_file).read_bytes() if pptx_file is not None else None
    return CapabilityFixture.model_validate(raw)


def load_capabilities(root: Path) -> list[CapabilityFixture]:
    """Load every ``capability.toml`` below ``root`` in deterministic path order."""
    if not root.is_dir():
        raise FileNotFoundError(f"capability fixtures not found: {root}")
    return [_load_fixture(path) for path in sorted(root.rglob("capability.toml"))]


def _warning_matches(expected: str, warnings: tuple[ConversionWarning, ...]) -> bool:
    return any(expected in warning.message for warning in warnings)


def _validate_coverage(
    fixture: CapabilityFixture,
    report: CoverageReport,
    *,
    include_minimums: bool,
) -> list[str]:
    errors: list[str] = []
    if include_minimums:
        for representation, expected in fixture.expected.min_representation.items():
            actual = report.count(representation)
            if actual < expected:
                errors.append(
                    f"{representation.value} count {actual} < expected minimum {expected}"
                )
    for representation, expected in fixture.expected.max_representation.items():
        actual = report.count(representation)
        if actual > expected:
            errors.append(f"{representation.value} count {actual} > expected maximum {expected}")
    return errors


def _validate_xml(fixture: CapabilityFixture, pptx: bytes | None) -> list[str]:
    if not fixture.expected.xml:
        return []
    if pptx is None:
        return ["fixture requires OOXML assertions but render produced no PPTX"]
    errors: list[str] = []
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        names = set(archive.namelist())
        for part in fixture.expected.required_parts:
            if part not in names:
                errors.append(f"missing package part {part}")
        for expected in fixture.expected.xml:
            if expected.part not in names:
                errors.append(f"missing package part {expected.part}")
                continue
            count = _xpath_count(archive.read(expected.part), expected.xpath)
            if count < expected.min_count:
                errors.append(
                    f"{expected.part}: xpath {expected.xpath!r} count {count} "
                    f"< expected {expected.min_count}"
                )
    return errors


def validate_capability(fixture: CapabilityFixture, result: RenderResult) -> tuple[str, ...]:
    """Return structural mismatches for one rendered forward capability fixture."""
    errors = _validate_coverage(fixture, result.coverage, include_minimums=True)
    for expected in fixture.expected.warnings:
        if not _warning_matches(expected, result.warnings):
            errors.append(f"missing warning containing {expected!r}")
    errors.extend(_validate_xml(fixture, result.pptx))
    return tuple(errors)


def validate_roundtrip_capability(
    fixture: CapabilityFixture, result: RenderResult
) -> tuple[str, ...]:
    """Validate regenerated output without applying source-tree-specific minima."""
    errors = _validate_coverage(fixture, result.coverage, include_minimums=False)
    errors.extend(_validate_xml(fixture, result.pptx))
    return tuple(errors)


def validate_reverse_capability(
    fixture: CapabilityFixture, result: HtmlPresentation
) -> tuple[str, ...]:
    """Return structural mismatches in PPTX -> HTML capability output."""
    expected = fixture.reverse
    errors: list[str] = []
    if len(result.slides) != expected.expected_slides:
        errors.append(f"slide count {len(result.slides)} != expected {expected.expected_slides}")
    document = result.css + "\n" + "\n".join(slide.html for slide in result.slides)
    for token in expected.html_contains:
        if token not in document:
            errors.append(f"reverse HTML missing {token!r}")
    if len(result.warnings) > expected.max_warnings:
        errors.append(f"reverse warnings {len(result.warnings)} > expected {expected.max_warnings}")
    if len(result.preserved) > expected.max_preserved:
        errors.append(
            f"reverse preserved fragments {len(result.preserved)} "
            f"> expected {expected.max_preserved}"
        )
    return tuple(errors)
