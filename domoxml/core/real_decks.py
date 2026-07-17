"""Manifest models and structural validation for representative external PPTX decks."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domoxml.core.capabilities import CapabilityCoverageBounds, validate_coverage
from domoxml.core.opc import OpcPackage, validate_opc_package
from domoxml.slides.validation import validate_pptx_package
from domoxml.types import HtmlPresentation

_SLIDE_PART = re.compile(r"ppt/slides/slide\d+\.xml$")


class DeckProvenance(BaseModel):
    """Pinned origin and redistribution terms for an external fixture."""

    model_config = ConfigDict(frozen=True)

    source_url: str
    source_revision: str
    license: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeckPackageExpected(BaseModel):
    """Package-level assertions made before conversion."""

    model_config = ConfigDict(frozen=True)

    slides: int = Field(ge=1)
    required_parts: tuple[str, ...] = ()


class PreservedExpected(BaseModel):
    """One unsupported OOXML fragment that must be surfaced intact."""

    model_config = ConfigDict(frozen=True)

    part: str
    kind: str
    xml_contains: str


class DeckReverseExpected(CapabilityCoverageBounds):
    """PPTX-to-HTML structure and diagnostic assertions."""

    model_config = ConfigDict(frozen=True)

    min_assets: int = Field(default=0, ge=0)
    max_warnings: int = Field(default=0, ge=0)
    warning_contains: tuple[str, ...] = ()
    preserved_count: int = Field(default=0, ge=0)
    preserved: tuple[PreservedExpected, ...] = ()
    html_contains: tuple[str, ...] = ()
    roundtrip_xml_contains: tuple[str, ...] = ()
    roundtrip_required_parts: tuple[str, ...] = ()


class DeckVisualExpected(BaseModel):
    """Renderer-independent visual floors for one round-tripped slide."""

    model_config = ConfigDict(frozen=True)

    slide: int = Field(ge=0)
    min_similarity: float = Field(ge=0.0, le=1.0)
    min_regional_similarity: float = Field(ge=0.0, le=1.0)
    min_structural_similarity: float = Field(default=0.0, ge=0.0, le=1.0)


class RealDeckCase(BaseModel):
    """One pinned external deck and its executable round-trip contract."""

    model_config = ConfigDict(frozen=True)

    id: str
    pptx: bytes = Field(exclude=True)
    provenance: DeckProvenance
    package: DeckPackageExpected
    reverse: DeckReverseExpected
    visual: tuple[DeckVisualExpected, ...] = ()
    visual_exclusion: str | None = None

    @model_validator(mode="after")
    def _visual_contract_is_explicit(self) -> RealDeckCase:
        if bool(self.visual) == bool(self.visual_exclusion):
            raise ValueError("real-deck case requires visual floors or one visual_exclusion reason")
        invalid = [item.slide for item in self.visual if item.slide >= self.package.slides]
        if invalid:
            raise ValueError(f"visual slide indices out of range: {invalid}")
        return self


def _load_case(path: Path) -> RealDeckCase:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    pptx_file = raw.pop("pptx_file", None)
    if not isinstance(pptx_file, str):
        raise ValueError(f"{path}: pptx_file must be a string")
    raw["pptx"] = (path.parent / pptx_file).read_bytes()
    return RealDeckCase.model_validate(raw)


def load_real_decks(root: Path) -> list[RealDeckCase]:
    """Load all external-deck manifests below ``root`` in deterministic order."""
    if not root.is_dir():
        raise FileNotFoundError(f"real-deck corpus not found: {root}")
    return [_load_case(path) for path in sorted(root.rglob("case.toml"))]


def validate_real_deck(case: RealDeckCase, html: HtmlPresentation) -> tuple[str, ...]:
    """Validate provenance, package structure, reverse HTML, warnings, and preservation."""
    errors: list[str] = []
    errors.extend(validate_coverage(case.reverse, html.coverage))
    digest = hashlib.sha256(case.pptx).hexdigest()
    if digest != case.provenance.sha256:
        errors.append(f"sha256 {digest} != pinned {case.provenance.sha256}")

    package_errors = validate_opc_package(case.pptx)
    errors.extend(package_errors)
    try:
        package = OpcPackage.from_bytes(case.pptx)
    except ValueError:
        return tuple(errors)
    slide_count = sum(bool(_SLIDE_PART.fullmatch(part)) for part in package.parts)
    if slide_count != case.package.slides:
        errors.append(f"package slide count {slide_count} != expected {case.package.slides}")
    for part in case.package.required_parts:
        if not package.has_part(part):
            errors.append(f"missing required package part {part}")
    if len(html.slides) != case.package.slides:
        errors.append(f"reverse slide count {len(html.slides)} != expected {case.package.slides}")
    if len(html.assets) < case.reverse.min_assets:
        errors.append(f"reverse assets {len(html.assets)} < expected {case.reverse.min_assets}")
    if len(html.warnings) > case.reverse.max_warnings:
        errors.append(
            f"reverse warnings {len(html.warnings)} > expected {case.reverse.max_warnings}"
        )
    for token in case.reverse.warning_contains:
        if not any(token in warning.message for warning in html.warnings):
            errors.append(f"reverse warning missing {token!r}")
    if len(html.preserved) != case.reverse.preserved_count:
        errors.append(
            f"reverse preserved fragments {len(html.preserved)} "
            f"!= expected {case.reverse.preserved_count}"
        )
    for expected in case.reverse.preserved:
        if not any(
            fragment.part == expected.part
            and fragment.kind == expected.kind
            and expected.xml_contains in fragment.xml
            for fragment in html.preserved
        ):
            errors.append(
                f"missing preserved {expected.kind} in {expected.part} "
                f"containing {expected.xml_contains!r}"
            )
    document = html.css + "\n" + "\n".join(slide.html for slide in html.slides)
    for token in case.reverse.html_contains:
        if token not in document:
            errors.append(f"reverse HTML missing {token!r}")
    return tuple(errors)


def validate_real_deck_roundtrip(case: RealDeckCase, pptx: bytes) -> tuple[str, ...]:
    """Validate re-emitted OPC relationships and required editable XML text/content."""
    errors = list(validate_pptx_package(pptx))
    try:
        package = OpcPackage.from_bytes(pptx)
    except ValueError:
        return tuple(errors)
    slide_count = sum(bool(_SLIDE_PART.fullmatch(part)) for part in package.parts)
    if slide_count != case.package.slides:
        errors.append(f"roundtrip slide count {slide_count} != expected {case.package.slides}")
    for part in case.reverse.roundtrip_required_parts:
        if not package.has_part(part):
            errors.append(f"roundtrip missing required package part {part}")
    xml = "\n".join(
        package.read(part).decode("utf-8", errors="replace")
        for part in package.parts
        if part.endswith(".xml")
    )
    for token in case.reverse.roundtrip_xml_contains:
        if token not in xml:
            errors.append(f"roundtrip XML missing {token!r}")
    return tuple(errors)
