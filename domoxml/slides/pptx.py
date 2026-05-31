"""Assemble a list of :class:`SlideIR` into a valid, editable ``.pptx`` (bytes)."""

from __future__ import annotations

from xml.sax.saxutils import escape

from domoxml.core.drawingml import shape_xml
from domoxml.core.fonts import FontFace, load_faces
from domoxml.core.ir.model import PictureFill, SlideIR
from domoxml.core.opc import write_package
from domoxml.slides import _templates as t

_PML = "application/vnd.openxmlformats-officedocument.presentationml"
_THEME_CT = "application/vnd.openxmlformats-officedocument.theme+xml"
_RELS_CT = "application/vnd.openxmlformats-package.relationships+xml"
_FONT_CT = "application/x-fontdata"
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_IMAGE_CT = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif"}

# (face, in-package part path, relationship id) for each embedded font.
type FontRel = tuple[FontFace, str, str]
_SLOT_ORDER = ("regular", "bold", "italic", "boldItalic")


def _override(part: str, content_type: str) -> str:
    return f'<Override PartName="{part}" ContentType="{content_type}"/>'


def _content_types(n_slides: int, *, has_fonts: bool, image_exts: set[str]) -> str:
    overrides = [
        _override("/ppt/presentation.xml", f"{_PML}.presentation.main+xml"),
        _override("/ppt/slideMasters/slideMaster1.xml", f"{_PML}.slideMaster+xml"),
        _override("/ppt/slideLayouts/slideLayout1.xml", f"{_PML}.slideLayout+xml"),
        _override("/ppt/theme/theme1.xml", _THEME_CT),
    ]
    overrides += [
        _override(f"/ppt/slides/slide{i}.xml", f"{_PML}.slide+xml") for i in range(1, n_slides + 1)
    ]
    defaults = [
        f'<Default Extension="rels" ContentType="{_RELS_CT}"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    if has_fonts:
        defaults.append(f'<Default Extension="fntdata" ContentType="{_FONT_CT}"/>')
    defaults += [
        f'<Default Extension="{ext}" ContentType="{_IMAGE_CT[ext]}"/>' for ext in sorted(image_exts)
    ]
    return f'{t.XML_DECL}<Types xmlns="{_CT_NS}">{"".join(defaults)}{"".join(overrides)}</Types>'


def _font_slot(face: FontFace) -> str:
    if face.bold and face.italic:
        return "boldItalic"
    if face.bold:
        return "bold"
    if face.italic:
        return "italic"
    return "regular"


def _embedded_font_lst(font_rels: list[FontRel]) -> str:
    if not font_rels:
        return ""
    by_family: dict[str, dict[str, str]] = {}
    for face, _part, rid in font_rels:
        by_family.setdefault(face.family, {})[_font_slot(face)] = rid
    entries: list[str] = []
    for family, slots in by_family.items():
        variants = "".join(
            f'<p:{slot} r:id="{slots[slot]}"/>' for slot in _SLOT_ORDER if slot in slots
        )
        typeface = escape(family, {'"': "&quot;"})
        entries.append(
            f'<p:embeddedFont><p:font typeface="{typeface}"/>{variants}</p:embeddedFont>'
        )
    return f"<p:embeddedFontLst>{''.join(entries)}</p:embeddedFontLst>"


def _presentation(width_emu: int, height_emu: int, n_slides: int, font_rels: list[FontRel]) -> str:
    # rId1 is the master; slide i uses rId(i+1) and sldId 255+i.
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n_slides + 1))
    embed_attr = ' embedTrueTypeFonts="1"' if font_rels else ""
    return (
        f"{t.XML_DECL}<p:presentation {t.NS}{embed_attr}>"
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{ids}</p:sldIdLst>"
        f'<p:sldSz cx="{width_emu}" cy="{height_emu}"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        f"{_embedded_font_lst(font_rels)}</p:presentation>"
    )


def _presentation_rels(n_slides: int, font_rels: list[FontRel]) -> str:
    slides = "".join(
        f'<Relationship Id="rId{i + 1}" Type="{_REL_TYPE}/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, n_slides + 1)
    )
    fonts = "".join(
        f'<Relationship Id="{rid}" Type="{_REL_TYPE}/font" Target="{part.removeprefix("ppt/")}"/>'
        for _face, part, rid in font_rels
    )
    return (
        f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_TYPE}/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
        f"{slides}{fonts}</Relationships>"
    )


def _slide_rels(image_rels: list[tuple[str, str]]) -> str:
    """Slide relationships: the layout (rId1) plus one rel per embedded picture."""
    images = "".join(
        f'<Relationship Id="{rid}" Type="{_REL_TYPE}/image" Target="../media/{name}"/>'
        for rid, name in image_rels
    )
    return (
        f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_TYPE}/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        f"{images}</Relationships>"
    )


def _slide(slide: SlideIR, media_start: int) -> tuple[str, str, dict[str, bytes], int]:
    """Build one slide. Returns ``(slide_xml, slide_rels_xml, media_parts, next_media_index)``.

    ``media_start`` is the next free ``ppt/media/imageN`` index (unique across the deck).
    """
    media_parts: dict[str, bytes] = {}
    image_rels: list[tuple[str, str]] = []
    blip_rids: dict[int, str] = {}
    media_index = media_start
    next_rid = 2  # rId1 is the layout

    for position, node in enumerate(slide.shapes):
        if isinstance(node.fill, PictureFill):
            name = f"image{media_index}.{node.fill.ext}"
            media_parts[f"ppt/media/{name}"] = node.fill.data
            rid = f"rId{next_rid}"
            image_rels.append((rid, name))
            blip_rids[position] = rid
            media_index += 1
            next_rid += 1

    shapes = "".join(
        shape_xml(node, shape_id=position + 2, blip_rid=blip_rids.get(position))
        for position, node in enumerate(slide.shapes)
    )
    slide_xml = (
        f"{t.XML_DECL}<p:sld {t.NS}><p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
        f"{shapes}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )
    return slide_xml, _slide_rels(image_rels), media_parts, media_index


def build_pptx(slides: list[SlideIR], *, faces: list[FontFace] | None = None) -> bytes:
    """Build a complete, editable ``.pptx`` from the slide IR. Needs at least one slide.

    Fonts the slides use are resolved (web + system) and embedded so exact typography travels
    with the deck; pass ``faces`` to reuse an already-resolved set (e.g. to surface warnings),
    otherwise they are resolved here. Picture fills become native ``ppt/media`` parts.
    """
    if not slides:
        raise ValueError("cannot build a .pptx with no slides — add at least one slide")

    # A .pptx has one presentation size for all slides; they must agree, or we'd silently
    # mis-size every slide but the first.
    width, height = slides[0].width, slides[0].height
    for index, slide in enumerate(slides):
        if (slide.width, slide.height) != (width, height):
            raise ValueError(
                "all slides must share one size for a single .pptx; "
                f"slide {index} is {slide.width}x{slide.height}, expected {width}x{height}"
            )
    n = len(slides)

    resolved_faces = faces if faces is not None else load_faces(slides)
    # rId1 = master, rId2..n+1 = slides, fonts start at rId(n+2).
    font_rels: list[FontRel] = [
        (face, f"ppt/fonts/font{i + 1}.fntdata", f"rId{n + 2 + i}")
        for i, face in enumerate(resolved_faces)
    ]

    slide_parts: dict[str, bytes | str] = {}
    image_exts: set[str] = set()
    media_index = 1
    for i, slide in enumerate(slides, start=1):
        slide_xml, slide_rels, media_parts, media_index = _slide(slide, media_index)
        slide_parts[f"ppt/slides/slide{i}.xml"] = slide_xml
        slide_parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = slide_rels
        for part, data in media_parts.items():
            slide_parts[part] = data
            image_exts.add(part.rsplit(".", 1)[-1])

    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types(n, has_fonts=bool(font_rels), image_exts=image_exts),
        "_rels/.rels": t.ROOT_RELS,
        "ppt/presentation.xml": _presentation(width, height, n, font_rels),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(n, font_rels),
        "ppt/theme/theme1.xml": t.THEME,
        "ppt/slideMasters/slideMaster1.xml": t.SLIDE_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": t.SLIDE_MASTER_RELS,
        "ppt/slideLayouts/slideLayout1.xml": t.SLIDE_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": t.SLIDE_LAYOUT_RELS,
    }
    for face, part, _rid in font_rels:
        parts[part] = face.data
    parts.update(slide_parts)
    return write_package(parts)
