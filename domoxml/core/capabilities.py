"""Machine-readable conversion capability fixtures and structural assertions."""

from __future__ import annotations

import importlib
import io
import tomllib
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domoxml.types import ConversionWarning, CoverageReport, Disposition, RenderResult

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
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


class CapabilityExpected(BaseModel):
    """Structural behavior expected from a capability fixture."""

    model_config = ConfigDict(frozen=True)

    min_native: int = Field(default=0, ge=0)
    max_raster: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()
    xml: tuple[XmlExpectation, ...] = ()


class CapabilityVisual(BaseModel):
    """Optional visual thresholds consumed by fidelity tooling as it grows."""

    model_config = ConfigDict(frozen=True)

    source_to_pptx_min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    pptx_to_html_min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)


class CapabilityFixture(BaseModel):
    """One isolated feature probe loaded from ``capability.toml``."""

    model_config = ConfigDict(frozen=True)

    id: str
    direction: CapabilityDirection
    html: str
    expected: CapabilityExpected = Field(default_factory=CapabilityExpected)
    visual: CapabilityVisual = Field(default_factory=CapabilityVisual)


def _load_fixture(path: Path) -> CapabilityFixture:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    html_file = raw.pop("html_file", "slide.html")
    if not isinstance(html_file, str):
        raise ValueError(f"{path}: html_file must be a string")
    raw["html"] = (path.parent / html_file).read_text(encoding="utf-8")
    return CapabilityFixture.model_validate(raw)


def load_capabilities(root: Path) -> list[CapabilityFixture]:
    """Load every ``capability.toml`` below ``root`` in deterministic path order."""
    if not root.is_dir():
        raise FileNotFoundError(f"capability fixtures not found: {root}")
    return [_load_fixture(path) for path in sorted(root.rglob("capability.toml"))]


def _warning_matches(expected: str, warnings: tuple[ConversionWarning, ...]) -> bool:
    return any(expected in warning.message for warning in warnings)


def _validate_coverage(fixture: CapabilityFixture, report: CoverageReport) -> list[str]:
    native = sum(item.disposition is Disposition.NATIVE for item in report.items)
    raster = sum(item.disposition is Disposition.RASTER for item in report.items)
    errors: list[str] = []
    if native < fixture.expected.min_native:
        errors.append(f"native count {native} < expected {fixture.expected.min_native}")
    if raster > fixture.expected.max_raster:
        errors.append(f"raster count {raster} > expected {fixture.expected.max_raster}")
    return errors


def _validate_xml(fixture: CapabilityFixture, pptx: bytes | None) -> list[str]:
    if not fixture.expected.xml:
        return []
    if pptx is None:
        return ["fixture requires OOXML assertions but render produced no PPTX"]
    errors: list[str] = []
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        names = set(archive.namelist())
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
    errors = _validate_coverage(fixture, result.coverage)
    for expected in fixture.expected.warnings:
        if not _warning_matches(expected, result.warnings):
            errors.append(f"missing warning containing {expected!r}")
    errors.extend(_validate_xml(fixture, result.pptx))
    return tuple(errors)
