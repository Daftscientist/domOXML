"""Assemble a list of :class:`SlideIR` into a valid, editable ``.pptx`` (bytes)."""

from __future__ import annotations

from domoxml.core.drawingml import shape_xml
from domoxml.core.ir.model import SlideIR
from domoxml.core.opc import write_package
from domoxml.slides import _templates as t

_PML = "application/vnd.openxmlformats-officedocument.presentationml"
_THEME_CT = "application/vnd.openxmlformats-officedocument.theme+xml"
_RELS_CT = "application/vnd.openxmlformats-package.relationships+xml"
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _override(part: str, content_type: str) -> str:
    return f'<Override PartName="{part}" ContentType="{content_type}"/>'


def _content_types(n_slides: int) -> str:
    overrides = [
        _override("/ppt/presentation.xml", f"{_PML}.presentation.main+xml"),
        _override("/ppt/slideMasters/slideMaster1.xml", f"{_PML}.slideMaster+xml"),
        _override("/ppt/slideLayouts/slideLayout1.xml", f"{_PML}.slideLayout+xml"),
        _override("/ppt/theme/theme1.xml", _THEME_CT),
    ]
    overrides += [
        _override(f"/ppt/slides/slide{i}.xml", f"{_PML}.slide+xml") for i in range(1, n_slides + 1)
    ]
    return (
        f'{t.XML_DECL}<Types xmlns="{_CT_NS}">'
        f'<Default Extension="rels" ContentType="{_RELS_CT}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}</Types>"
    )


def _presentation(width_emu: int, height_emu: int, n_slides: int) -> str:
    # rId1 is the master; slide i uses rId(i+1) and sldId 255+i.
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n_slides + 1))
    return (
        f"{t.XML_DECL}<p:presentation {t.NS}>"
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{ids}</p:sldIdLst>"
        f'<p:sldSz cx="{width_emu}" cy="{height_emu}"/>'
        '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    )


def _presentation_rels(n_slides: int) -> str:
    slides = "".join(
        f'<Relationship Id="rId{i + 1}" Type="{_REL_TYPE}/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, n_slides + 1)
    )
    return (
        f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_TYPE}/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
        f"{slides}</Relationships>"
    )


def _slide(slide: SlideIR) -> str:
    # Shape ids start at 2 (id 1 is the slide's group shape).
    shapes = "".join(shape_xml(node, shape_id=i) for i, node in enumerate(slide.shapes, start=2))
    return (
        f"{t.XML_DECL}<p:sld {t.NS}><p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
        f"{shapes}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def build_pptx(slides: list[SlideIR]) -> bytes:
    """Build a complete, editable ``.pptx`` from the slide IR. Needs at least one slide."""
    if not slides:
        raise ValueError("cannot build a .pptx with no slides — add at least one slide")

    # All slides share one presentation size; use the first slide's dimensions.
    width, height = slides[0].width, slides[0].height
    n = len(slides)

    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types(n),
        "_rels/.rels": t.ROOT_RELS,
        "ppt/presentation.xml": _presentation(width, height, n),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(n),
        "ppt/theme/theme1.xml": t.THEME,
        "ppt/slideMasters/slideMaster1.xml": t.SLIDE_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": t.SLIDE_MASTER_RELS,
        "ppt/slideLayouts/slideLayout1.xml": t.SLIDE_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": t.SLIDE_LAYOUT_RELS,
    }
    for i, slide in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{i}.xml"] = _slide(slide)
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = t.SLIDE_RELS
    return write_package(parts)
