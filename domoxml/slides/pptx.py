"""Assemble a list of :class:`SlideIR` into a valid, editable ``.pptx`` (bytes)."""

from __future__ import annotations

import posixpath
import warnings
from xml.sax.saxutils import escape

from domoxml.core.drawingml import can_emit_picture, line_xml, picture_xml, shape_xml, table_xml
from domoxml.core.drawingml.identity import node_identity_xml
from domoxml.core.fonts import FontFace, load_faces
from domoxml.core.ir.model import (
    Connector,
    Hyperlink,
    PictureFill,
    PreservationPart,
    PreservationRelationship,
    PreservedNode,
    ShapeNode,
    SlideIR,
    TableNode,
    TextBody,
)
from domoxml.core.opc import (
    relationship_part_name,
    relationships_xml,
    rewrite_root_xml,
    write_package,
)
from domoxml.slides import _templates as t
from domoxml.slides.background import background_xml
from domoxml.slides.transition import transition_xml
from domoxml.slides.validation import validate_pptx_package

_PML = "application/vnd.openxmlformats-officedocument.presentationml"
_THEME_CT = "application/vnd.openxmlformats-officedocument.theme+xml"
_RELS_CT = "application/vnd.openxmlformats-package.relationships+xml"
_FONT_CT = "application/x-fontdata"
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_IMAGE_CT = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif"}
_SVG_CT = "image/svg+xml"

# (face, in-package part path, relationship id) for each embedded font.
type FontRel = tuple[FontFace, str, str]
_SLOT_ORDER = ("regular", "bold", "italic", "boldItalic")


def _attr(value: str) -> str:
    """Escape a string for an XML attribute (double-quoted)."""
    return escape(value, {'"': "&quot;"})


def _override(part: str, content_type: str) -> str:
    return f'<Override PartName="{part}" ContentType="{content_type}"/>'


def _content_types(
    n_slides: int,
    *,
    has_fonts: bool,
    image_exts: set[str],
    has_svg: bool = False,
    preserved_content_types: dict[str, str] | None = None,
) -> str:
    overrides = [
        _override("/ppt/presentation.xml", f"{_PML}.presentation.main+xml"),
        _override("/ppt/slideMasters/slideMaster1.xml", f"{_PML}.slideMaster+xml"),
        _override("/ppt/slideLayouts/slideLayout1.xml", f"{_PML}.slideLayout+xml"),
        _override("/ppt/theme/theme1.xml", _THEME_CT),
    ]
    overrides += [
        _override(f"/ppt/slides/slide{i}.xml", f"{_PML}.slide+xml") for i in range(1, n_slides + 1)
    ]
    overrides += [
        _override(f"/{part}", content_type)
        for part, content_type in sorted((preserved_content_types or {}).items())
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
    if has_svg:
        defaults.append(f'<Default Extension="svg" ContentType="{_SVG_CT}"/>')
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


def _hyperlink_target(hyperlink: Hyperlink) -> tuple[str, str]:
    """The ``(Type, attrs)`` for a hyperlink relationship: an external URL gets
    ``TargetMode="External"``; an in-deck slide jump targets the destination slide part."""
    if hyperlink.slide_index is not None:
        target = f"slide{hyperlink.slide_index + 1}.xml"
        return f"{_REL_TYPE}/slide", f'Target="{target}"'
    url = _attr(hyperlink.url or "")
    return f"{_REL_TYPE}/hyperlink", f'Target="{url}" TargetMode="External"'


def _slide_rels(
    slide_part: str,
    image_rels: list[tuple[str, str]],
    hyperlink_rels: list[tuple[str, Hyperlink]],
    preserved_rels: list[tuple[str, PreservationRelationship]],
) -> str:
    """Slide relationships: the layout (rId1), one rel per embedded picture, one per hyperlink."""
    images = "".join(
        f'<Relationship Id="{rid}" Type="{_REL_TYPE}/image" Target="../media/{name}"/>'
        for rid, name in image_rels
    )
    links = ""
    for rid, hyperlink in hyperlink_rels:
        rel_type, attrs = _hyperlink_target(hyperlink)
        links += f'<Relationship Id="{rid}" Type="{rel_type}" {attrs}/>'
    retained = ""
    for rid, relationship in preserved_rels:
        target = relationship.target
        mode = ""
        if relationship.target_mode == "Internal":
            target = posixpath.relpath(target, posixpath.dirname(slide_part))
        else:
            mode = ' TargetMode="External"'
        retained += (
            f'<Relationship Id="{_attr(rid)}" Type="{_attr(relationship.type)}" '
            f'Target="{_attr(target)}"{mode}/>'
        )
    return (
        f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_TYPE}/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        f"{images}{links}{retained}</Relationships>"
    )


def _shape_hyperlinks(body: TextBody | None) -> list[Hyperlink]:
    """Every run hyperlink in a text body, in document order."""
    if body is None:
        return []
    return [
        run.hyperlink
        for paragraph in body.paragraphs
        for run in paragraph.runs
        if run.hyperlink is not None
    ]


def _connector_xml(conn: Connector, *, shape_id: int) -> str:
    """Emit a ``<p:cxnSp>`` element for a connector node."""
    x = min(conn.start.x, conn.end.x)
    y = min(conn.start.y, conn.end.y)
    cx = max(1, abs(conn.end.x - conn.start.x))
    cy = max(1, abs(conn.end.y - conn.start.y))
    line = line_xml(conn.line)
    return (
        f"<p:cxnSp>"
        f"<p:nvCxnSpPr>"
        f'<p:cNvPr id="{shape_id}" name="Connector {shape_id}"/>'
        f"<p:cNvCxnSpPr/>"
        f"<p:nvPr>{node_identity_xml(conn)}</p:nvPr>"
        f"</p:nvCxnSpPr>"
        f"<p:spPr>"
        f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
        f"{line}"
        f"</p:spPr>"
        f"</p:cxnSp>"
    )


def _slide(
    slide: SlideIR,
    media_registry: dict[tuple[str, bytes], str],
    slide_count: int,
    slide_number: int,
) -> tuple[
    str,
    str,
    dict[str, bytes],
    bool,
    dict[str, PreservationPart],
    PreservationPart | None,
]:
    """Build one slide.

    Media payloads are registered once across the deck, while each slide retains its own
    relationship IDs.
    """
    media_parts: dict[str, bytes] = {}
    image_rels: list[tuple[str, str]] = []
    blip_rids: dict[int, str] = {}
    svg_rids: dict[int, str] = {}
    has_svg = False
    next_rid = 2  # rId1 is the layout
    media_rids: dict[str, str] = {}
    slide_part = f"ppt/slides/slide{slide_number}.xml"

    def register_media(data: bytes, ext: str) -> str:
        nonlocal next_rid
        key = (ext, data)
        name = media_registry.get(key)
        if name is None:
            name = f"image{len(media_registry) + 1}.{ext}"
            media_registry[key] = name
            media_parts[f"ppt/media/{name}"] = data
        existing_rid = media_rids.get(name)
        if existing_rid is not None:
            return existing_rid
        rid = f"rId{next_rid}"
        image_rels.append((rid, name))
        media_rids[name] = rid
        next_rid += 1
        return rid

    # Warn on node types still without a writer. Supported nodes retain their canonical order.
    for node in slide.contents:
        if not isinstance(node, ShapeNode | Connector | TableNode | PreservedNode):
            warnings.warn(
                f"{type(node).__name__} has no PresentationML writer yet; node dropped",
                stacklevel=2,
            )

    # Background picture fill: needs its own media part + rel.
    bg_blip_rid: str | None = None
    if slide.background is not None and isinstance(slide.background.fill, PictureFill):
        pic = slide.background.fill
        bg_blip_rid = register_media(pic.data, pic.ext)

    for position, node in enumerate(slide.contents):
        if isinstance(node, ShapeNode) and isinstance(node.fill, PictureFill):
            blip_rids[position] = register_media(node.fill.data, node.fill.ext)
            # SVG source paired with the PNG: a second media part + rel for the svgBlip ext.
            if node.fill.svg_data is not None:
                svg_rids[position] = register_media(node.fill.svg_data, "svg")
                has_svg = True

    # One slide relationship per run hyperlink, in document order. Identity-keyed so two runs
    # with structurally-equal links still each get their own rel (matching the IR objects).
    hyperlink_rels: list[tuple[str, Hyperlink]] = []
    rid_by_link: dict[int, str] = {}
    for node in slide.contents:
        if not isinstance(node, ShapeNode):
            continue
        for link in _shape_hyperlinks(node.text):
            if id(link) in rid_by_link:
                continue
            if link.slide_index is not None and not (0 <= link.slide_index < slide_count):
                warnings.warn(
                    f"hyperlink targets slide {link.slide_index + 1} but the deck has "
                    f"{slide_count} slide(s); link dropped to keep the package valid",
                    stacklevel=2,
                )
                continue
            rid = f"rId{next_rid}"
            rid_by_link[id(link)] = rid
            hyperlink_rels.append((rid, link))
            next_rid += 1

    preserved_rels: list[tuple[str, PreservationRelationship]] = []
    preserved_rids: dict[int, dict[str, str]] = {}
    preserved_parts: dict[str, PreservationPart] = {}
    preserved_theme: PreservationPart | None = None
    for position, node in enumerate(slide.contents):
        if not isinstance(node, PreservedNode):
            continue
        relationship_ids: dict[str, str] = {}
        for relationship in node.payload.relationships:
            rid = f"rId{next_rid}"
            next_rid += 1
            relationship_ids[relationship.id] = rid
            preserved_rels.append((rid, relationship))
        preserved_rids[position] = relationship_ids
        if node.payload.ambient_theme is not None:
            if preserved_theme is not None and preserved_theme != node.payload.ambient_theme:
                raise ValueError("conflicting preserved ambient themes on one slide")
            preserved_theme = node.payload.ambient_theme
        for part in node.payload.parts:
            existing = preserved_parts.get(part.name)
            if existing is not None and existing != part:
                raise ValueError(f"conflicting preserved OPC part: {part.name}")
            preserved_parts[part.name] = part

    def _hyperlink_rid(link: Hyperlink) -> str | None:
        return rid_by_link.get(id(link))

    content_parts: list[str] = []
    for position, node in enumerate(slide.contents):
        shape_id = position + 2
        if isinstance(node, ShapeNode):
            blip_rid = blip_rids.get(position)
            if can_emit_picture(node) and blip_rid is not None:
                content_parts.append(
                    picture_xml(
                        node,
                        shape_id=shape_id,
                        blip_rid=blip_rid,
                        svg_rid=svg_rids.get(position),
                    )
                )
            else:
                content_parts.append(
                    shape_xml(
                        node,
                        shape_id=shape_id,
                        blip_rid=blip_rid,
                        svg_rid=svg_rids.get(position),
                        hyperlink_rid=_hyperlink_rid,
                    )
                )
        elif isinstance(node, Connector):
            content_parts.append(_connector_xml(node, shape_id=shape_id))
        elif isinstance(node, TableNode):
            content_parts.append(table_xml(node, shape_id=shape_id))
        elif isinstance(node, PreservedNode):
            content_parts.append(
                rewrite_root_xml(
                    node,
                    shape_id=shape_id,
                    relationship_ids=preserved_rids[position],
                )
            )
    contents = "".join(content_parts)
    bg_xml = background_xml(slide.background, bg_blip_rid) if slide.background is not None else ""
    transition = transition_xml(slide.transition)
    slide_xml = (
        f"{t.XML_DECL}<p:sld {t.NS}><p:cSld>{bg_xml}<p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
        f"{contents}</p:spTree></p:cSld>"
        f"<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>{transition}</p:sld>"
    )
    return (
        slide_xml,
        _slide_rels(slide_part, image_rels, hyperlink_rels, preserved_rels),
        media_parts,
        has_svg,
        preserved_parts,
        preserved_theme,
    )


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
    preserved_parts: dict[str, PreservationPart] = {}
    preserved_theme: PreservationPart | None = None
    image_exts: set[str] = set()
    has_svg = False
    media_registry: dict[tuple[str, bytes], str] = {}
    for i, slide in enumerate(slides, start=1):
        (
            slide_xml,
            slide_rels,
            media_parts,
            slide_has_svg,
            slide_preserved,
            slide_theme,
        ) = _slide(slide, media_registry, n, i)
        has_svg = has_svg or slide_has_svg
        slide_parts[f"ppt/slides/slide{i}.xml"] = slide_xml
        slide_parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = slide_rels
        for part, data in media_parts.items():
            slide_parts[part] = data
            image_exts.add(part.rsplit(".", 1)[-1])
        for part_name, preserved in slide_preserved.items():
            existing = preserved_parts.get(part_name)
            if existing is not None and existing != preserved:
                raise ValueError(f"conflicting preserved OPC part: {part_name}")
            preserved_parts[part_name] = preserved
        if slide_theme is not None:
            if preserved_theme is not None and preserved_theme != slide_theme:
                raise ValueError("conflicting preserved ambient themes across slides")
            preserved_theme = slide_theme
    # The svg extension carries its own content type; never list it among raster _IMAGE_CT.
    image_exts.discard("svg")

    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types(
            n,
            has_fonts=bool(font_rels),
            image_exts=image_exts,
            has_svg=has_svg,
            preserved_content_types={
                part_name: preserved.content_type
                for part_name, preserved in preserved_parts.items()
            },
        ),
        "_rels/.rels": t.ROOT_RELS,
        "ppt/presentation.xml": _presentation(width, height, n, font_rels),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(n, font_rels),
        "ppt/theme/theme1.xml": preserved_theme.data if preserved_theme is not None else t.THEME,
        "ppt/slideMasters/slideMaster1.xml": t.SLIDE_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": t.SLIDE_MASTER_RELS,
        "ppt/slideLayouts/slideLayout1.xml": t.SLIDE_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": t.SLIDE_LAYOUT_RELS,
    }
    for face, part, _rid in font_rels:
        parts[part] = face.data
    parts.update(slide_parts)
    if preserved_theme is not None and preserved_theme.relationships:
        theme_rels_part = relationship_part_name("ppt/theme/theme1.xml")
        parts[theme_rels_part] = relationships_xml(
            "ppt/theme/theme1.xml", preserved_theme.relationships
        )
    for part_name, preserved in preserved_parts.items():
        if part_name in parts:
            raise ValueError(f"preserved OPC part collides with generated part: {part_name}")
        parts[part_name] = preserved.data
        if preserved.relationships:
            rels_part = relationship_part_name(part_name)
            if rels_part in parts:
                raise ValueError(f"preserved OPC relationships collide: {rels_part}")
            parts[rels_part] = relationships_xml(part_name, preserved.relationships)
    pptx = write_package(parts)
    validation_errors = validate_pptx_package(pptx)
    if validation_errors:
        details = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"generated invalid PPTX package:\n{details}")
    return pptx
