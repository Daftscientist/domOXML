"""Assemble a list of :class:`SlideIR` into a valid, editable ``.pptx`` (bytes)."""

from __future__ import annotations

import hashlib
import posixpath
import warnings
from xml.sax.saxutils import escape

from defusedxml import ElementTree

from domoxml.core.connector_geometry import connector_box
from domoxml.core.drawingml import can_emit_picture, line_xml, picture_xml, shape_xml, table_xml
from domoxml.core.drawingml.identity import (
    alt_text_attr,
    node_identity_ext_xml,
    node_identity_xml,
)
from domoxml.core.fonts import FontFace, load_faces
from domoxml.core.ir.group import group_pptx_write_error
from domoxml.core.ir.model import (
    Blur,
    Box,
    Connector,
    FillOverlay,
    GroupNode,
    Hyperlink,
    MediaNode,
    PatternFill,
    PictureFill,
    PreservationPart,
    PreservationRelationship,
    PreservedNode,
    ShapeNode,
    SlideIR,
    TableNode,
    TextBody,
)
from domoxml.core.media import MEDIA_CONTENT_TYPES, default_poster
from domoxml.core.opc import (
    relationship_part_name,
    relationships_xml,
    rewrite_root_xml,
    write_package,
)
from domoxml.core.units import emu_to_px
from domoxml.slides import _templates as t
from domoxml.slides.background import background_xml
from domoxml.slides.media_read import WEB_VIEWER_ID
from domoxml.slides.notes import (
    NOTES_MASTER,
    NOTES_MASTER_CT,
    NOTES_MASTER_RELS,
    NOTES_SLIDE_CT,
    notes_slide_rels,
    notes_slide_xml,
)
from domoxml.slides.transition import transition_xml
from domoxml.slides.validation import validate_pptx_package

_PML = "application/vnd.openxmlformats-officedocument.presentationml"
_THEME_CT = "application/vnd.openxmlformats-officedocument.theme+xml"
_RELS_CT = "application/vnd.openxmlformats-package.relationships+xml"
_FONT_CT = "application/x-fontdata"
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_IMAGE_CT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    **MEDIA_CONTENT_TYPES,
}
_SVG_CT = "image/svg+xml"
_PML_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_MEDIA_REL = "http://schemas.microsoft.com/office/2007/relationships/media"

# (face, in-package part path, relationship id) for each embedded font.
type FontRel = tuple[FontFace, str, str]
_SLOT_ORDER = ("regular", "bold", "italic", "boldItalic")


def _attr(value: str) -> str:
    """Escape a string for an XML attribute (double-quoted)."""
    return escape(value, {'"': "&quot;"})


def _uses_pptx_source_fallback(node: PreservedNode, *, is_only_visual: bool) -> bool:
    """Whether source export should pair the retained native shape with its picture fallback."""
    if node.fallback_representation == "element_layer":
        return True
    if node.fallback_representation != "rasterized" or not is_only_visual:
        return False
    root = ElementTree.fromstring(node.payload.root_xml)
    return any(
        element.tag.rsplit("}", 1)[-1] in {"prstShdw", "effectDag"} for element in root.iter()
    )


def _override(part: str, content_type: str) -> str:
    return f'<Override PartName="{part}" ContentType="{content_type}"/>'


def _content_types(
    n_slides: int,
    *,
    notes_slides: tuple[int, ...] = (),
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
    if notes_slides:
        overrides += [
            _override("/ppt/notesMasters/notesMaster1.xml", NOTES_MASTER_CT),
            _override("/ppt/theme/theme2.xml", _THEME_CT),
            *(
                _override(f"/ppt/notesSlides/notesSlide{i}.xml", NOTES_SLIDE_CT)
                for i in notes_slides
            ),
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


def _presentation(
    width_emu: int,
    height_emu: int,
    n_slides: int,
    font_rels: list[FontRel],
    notes_master_rid: str | None = None,
) -> str:
    # rId1 is the master; slide i uses rId(i+1) and sldId 255+i.
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n_slides + 1))
    embed_attr = ' embedTrueTypeFonts="1"' if font_rels else ""
    notes_master_list = (
        f'<p:notesMasterIdLst><p:notesMasterId r:id="{notes_master_rid}"/></p:notesMasterIdLst>'
        if notes_master_rid
        else ""
    )
    return (
        f"{t.XML_DECL}<p:presentation {t.NS}{embed_attr}>"
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"{notes_master_list}"
        f"<p:sldIdLst>{ids}</p:sldIdLst>"
        f'<p:sldSz cx="{width_emu}" cy="{height_emu}"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        f"{_embedded_font_lst(font_rels)}</p:presentation>"
    )


def _presentation_rels(
    n_slides: int, font_rels: list[FontRel], notes_master_rid: str | None = None
) -> str:
    slides = "".join(
        f'<Relationship Id="rId{i + 1}" Type="{_REL_TYPE}/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, n_slides + 1)
    )
    fonts = "".join(
        f'<Relationship Id="{rid}" Type="{_REL_TYPE}/font" Target="{part.removeprefix("ppt/")}"/>'
        for _face, part, rid in font_rels
    )
    notes_master = (
        f'<Relationship Id="{notes_master_rid}" Type="{_REL_TYPE}/notesMaster" '
        'Target="notesMasters/notesMaster1.xml"/>'
        if notes_master_rid
        else ""
    )
    return (
        f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_TYPE}/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
        f"{slides}{fonts}{notes_master}</Relationships>"
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
    extra_rels: list[str] | None = None,
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
        f"{images}{links}{retained}{''.join(extra_rels or [])}</Relationships>"
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


_CONNECTOR_PRESETS = {"straight": "line", "bent": "bentConnector3", "curved": "curvedConnector3"}


def _connector_xml(conn: Connector, *, shape_id: int) -> str:
    """Emit a ``<p:cxnSp>`` element for a connector node."""
    x, y, cx, cy, rotation, flip_h, flip_v = connector_box(
        conn.start, conn.end, conn.vertical_first and conn.kind != "straight"
    )
    attributes = (
        (f' rot="{rotation}"' if rotation else "")
        + (' flipH="1"' if flip_h else "")
        + (' flipV="1"' if flip_v else "")
    )
    line = line_xml(conn.line)
    guides = (
        f'<a:avLst><a:gd name="adj1" fmla="val {round(conn.elbow * 100_000)}"/></a:avLst>'
        if conn.kind != "straight" and conn.elbow != 0.5
        else "<a:avLst/>"
    )
    return (
        f"<p:cxnSp>"
        f"<p:nvCxnSpPr>"
        f'<p:cNvPr id="{shape_id}" name="Connector {shape_id}"{alt_text_attr(conn)}/>'
        f"<p:cNvCxnSpPr/>"
        f"<p:nvPr>{node_identity_xml(conn)}</p:nvPr>"
        f"</p:nvCxnSpPr>"
        f"<p:spPr>"
        f'<a:xfrm{attributes}><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="{_CONNECTOR_PRESETS[conn.kind]}">{guides}</a:prstGeom>'
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
    fallback_rids: dict[int, str] = {}
    svg_rids: dict[int, str] = {}
    group_blip_rids: dict[int, str] = {}
    group_fallback_rids: dict[int, str] = {}
    group_svg_rids: dict[int, str] = {}
    has_svg = False
    next_rid = 2  # rId1 is the layout
    media_rids: dict[str, str] = {}
    slide_part = f"ppt/slides/slide{slide_number}.xml"

    def register_media(data: bytes, ext: str, prefix: str = "image") -> str:
        nonlocal next_rid
        key = (ext, data)
        name = media_registry.get(key)
        if name is None:
            name = f"{prefix}{len(media_registry) + 1}.{ext}"
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

    def register_clip(data: bytes, ext: str) -> str:
        """The part name of an embedded clip; identical clips share one part."""
        key = (ext, data)
        name = media_registry.get(key)
        if name is None:
            name = f"media{len(media_registry) + 1}.{ext}"
            media_registry[key] = name
            media_parts[f"ppt/media/{name}"] = data
        return name

    # Background picture fill: needs its own media part + rel.
    bg_blip_rid: str | None = None
    if slide.background is not None and isinstance(slide.background.fill, PictureFill):
        pic = slide.background.fill
        bg_blip_rid = register_media(pic.data, pic.ext)
    slide_fallback_rid: str | None = None
    if slide.renderer_fallback is not None:
        slide_fallback_rid = register_media(
            slide.renderer_fallback.data,
            slide.renderer_fallback.ext,
        )

    def iter_shapes(nodes: tuple[object, ...]) -> list[ShapeNode]:
        shapes: list[ShapeNode] = []
        for candidate in nodes:
            if isinstance(candidate, ShapeNode):
                shapes.append(candidate)
            elif isinstance(candidate, GroupNode):
                shapes.extend(iter_shapes(candidate.children))
        return shapes

    for position, node in enumerate(slide.contents):
        if isinstance(node, ShapeNode) and isinstance(node.fill, PictureFill):
            blip_rids[position] = register_media(node.fill.data, node.fill.ext)
            # SVG source paired with the PNG: a second media part + rel for the svgBlip ext.
            if node.fill.svg_data is not None:
                svg_rids[position] = register_media(node.fill.svg_data, "svg")
                has_svg = True
        if isinstance(node, ShapeNode) and node.portable_fallback is not None:
            fallback = node.portable_fallback.picture
            fallback_rids[position] = register_media(fallback.data, fallback.ext)
        if (
            isinstance(node, PreservedNode)
            and node.fallback is not None
            and node.payload.kind == "sp"
            and _uses_pptx_source_fallback(node, is_only_visual=len(slide.contents) == 1)
        ):
            fallback_rids[position] = register_media(node.fallback.data, node.fallback.ext)

    media_links: dict[int, tuple[str, str | None, str]] = {}
    extra_rels: list[str] = []
    if slide.notes:
        notes_rid = f"rId{next_rid}"
        next_rid += 1
        extra_rels.append(
            f'<Relationship Id="{notes_rid}" Type="{_REL_TYPE}/notesSlide" '
            f'Target="../notesSlides/notesSlide{slide_number}.xml"/>'
        )
    web_frames: dict[int, str] = {}
    web_parts: list[tuple[str, PreservationPart]] = []
    for position, node in enumerate(slide.contents):
        if not isinstance(node, MediaNode):
            continue
        if node.kind == "web" and node.media_url is not None:
            snapshot = node.poster_fill or default_poster(
                "web", emu_to_px(node.box.width), emu_to_px(node.box.height)
            )
            register_media(snapshot.data, snapshot.ext)
            extension, rid = _web_extension(
                node.media_url,
                f"ppt/webextensions/webextension{slide_number}_{position}.xml",
                f"ppt/media/{media_registry[(snapshot.ext, snapshot.data)]}",
                next_rid,
            )
            next_rid += 1
            web_parts.append((rid, extension))
            web_frames[position] = rid
            continue
        poster = node.poster_fill or default_poster(
            node.kind, emu_to_px(node.box.width), emu_to_px(node.box.height)
        )
        poster_rid = register_media(poster.data, poster.ext)
        kind_type = f"{_REL_TYPE}/{node.kind}"
        link_rid = f"rId{next_rid}"
        next_rid += 1
        embed_rid: str | None = None
        if node.media_data is not None:
            part_name = register_clip(node.media_data, node.media_ext)
            extra_rels.append(
                f'<Relationship Id="{link_rid}" Type="{kind_type}" Target="../media/{part_name}"/>'
            )
            embed_rid = f"rId{next_rid}"
            next_rid += 1
            extra_rels.append(
                f'<Relationship Id="{embed_rid}" Type="{_MEDIA_REL}" '
                f'Target="../media/{part_name}"/>'
            )
        elif node.media_url is not None:
            extra_rels.append(
                f'<Relationship Id="{link_rid}" Type="{kind_type}" '
                f'Target="{_attr(node.media_url)}" TargetMode="External"/>'
            )
        else:
            continue
        media_links[position] = (link_rid, embed_rid, poster_rid)

    for group in (node for node in slide.contents if isinstance(node, GroupNode)):
        for shape in iter_shapes((group,)):
            identity = id(shape)
            if isinstance(shape.fill, PictureFill):
                group_blip_rids[identity] = register_media(shape.fill.data, shape.fill.ext)
                if shape.fill.svg_data is not None:
                    group_svg_rids[identity] = register_media(shape.fill.svg_data, "svg")
                    has_svg = True
            if shape.portable_fallback is not None:
                fallback = shape.portable_fallback.picture
                group_fallback_rids[identity] = register_media(fallback.data, fallback.ext)

    # One slide relationship per run hyperlink, in document order. Identity-keyed so two runs
    # with structurally-equal links still each get their own rel (matching the IR objects).
    hyperlink_rels: list[tuple[str, Hyperlink]] = []
    rid_by_link: dict[int, str] = {}
    for node in iter_shapes(slide.contents):
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

    for web_rid, extension in web_parts:
        preserved_parts[extension.name] = extension
        preserved_rels.append(
            (web_rid, PreservationRelationship(id=web_rid, type=_WEB_REL, target=extension.name))
        )

    def _hyperlink_rid(link: Hyperlink) -> str | None:
        return rid_by_link.get(id(link))

    next_shape_id = 2

    def allocate_shape_id() -> int:
        nonlocal next_shape_id
        shape_id = next_shape_id
        next_shape_id += 1
        return shape_id

    def grouped_shape_xml(node: ShapeNode, *, shape_id: int) -> str:
        identity = id(node)
        blip_rid = group_blip_rids.get(identity)
        svg_rid = group_svg_rids.get(identity)
        if can_emit_picture(node) and blip_rid is not None:
            return picture_xml(
                node,
                shape_id=shape_id,
                blip_rid=blip_rid,
                svg_rid=svg_rid,
            )
        fallback_rid = group_fallback_rids.get(identity)
        choice_has_visible_fallback = (
            node.portable_fallback is not None
            and fallback_rid is not None
            and node.effect_container != "sibling"
            and not _paints_native_backdrop_blur(node)
            and (
                not (
                    node.effects and all(isinstance(effect, FillOverlay) for effect in node.effects)
                )
                or any(
                    isinstance(effect, FillOverlay)
                    and (isinstance(effect.fill, PatternFill) or effect.blend == "over")
                    for effect in node.effects
                )
            )
        )
        native_xml = shape_xml(
            node,
            shape_id=shape_id,
            blip_rid=blip_rid,
            svg_rid=svg_rid,
            hyperlink_rid=_hyperlink_rid,
            hidden=choice_has_visible_fallback,
        )
        if node.portable_fallback is None or fallback_rid is None:
            return native_xml
        fallback_node = node.model_copy(
            update={
                "box": node.portable_fallback.box,
                "geom": "rect",
                "custom_geom": None,
                "fill": node.portable_fallback.picture,
                "line": None,
                "side_lines": None,
                "effects": (),
                "native_effect_projection": "complete",
                "portable_fallback": None,
                "transform": None,
                "corner_radius_emu": 0,
                "opacity": 1.0,
                "text": None,
            }
        )
        choice_fallback_xml = picture_xml(
            fallback_node,
            shape_id=allocate_shape_id(),
            blip_rid=fallback_rid,
        )
        fallback_xml = picture_xml(
            fallback_node,
            shape_id=allocate_shape_id(),
            blip_rid=fallback_rid,
        )
        choice_fallback = choice_fallback_xml if choice_has_visible_fallback else ""
        return (
            "<mc:AlternateContent "
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            'xmlns:p16="http://schemas.microsoft.com/office/powerpoint/2015/main">'
            f'<mc:Choice Requires="p16">{native_xml}{choice_fallback}</mc:Choice>'
            f"<mc:Fallback>{fallback_xml}</mc:Fallback>"
            "</mc:AlternateContent>"
        )

    def group_xml(group: GroupNode, *, shape_id: int) -> str:
        if reason := group_pptx_write_error(group):
            raise ValueError(f"cannot emit native group: {reason}")
        transform_attrs = ""
        if group.transform is not None:
            if group.transform.rotation_deg != 0.0:
                transform_attrs += f' rot="{round(group.transform.rotation_deg * 60_000)}"'
            if group.transform.flip_h:
                transform_attrs += ' flipH="1"'
            if group.transform.flip_v:
                transform_attrs += ' flipV="1"'
        children: list[str] = []
        for child in group.children:
            child_id = allocate_shape_id()
            if isinstance(child, ShapeNode):
                children.append(grouped_shape_xml(child, shape_id=child_id))
            elif isinstance(child, Connector):
                children.append(_connector_xml(child, shape_id=child_id))
            else:
                children.append(group_xml(child, shape_id=child_id))
        return (
            "<p:grpSp><p:nvGrpSpPr>"
            f'<p:cNvPr id="{shape_id}" name="Group {shape_id}"{alt_text_attr(group)}/>'
            f"<p:cNvGrpSpPr/><p:nvPr>{node_identity_xml(group)}</p:nvPr>"
            "</p:nvGrpSpPr><p:grpSpPr>"
            f"<a:xfrm{transform_attrs}>"
            f'<a:off x="{group.box.x}" y="{group.box.y}"/>'
            f'<a:ext cx="{group.box.width}" cy="{group.box.height}"/>'
            f'<a:chOff x="{group.child_box.x}" y="{group.child_box.y}"/>'
            f'<a:chExt cx="{group.child_box.width}" cy="{group.child_box.height}"/>'
            "</a:xfrm></p:grpSpPr>"
            f"{''.join(children)}</p:grpSp>"
        )

    content_parts: list[str] = []
    for position, node in enumerate(slide.contents):
        shape_id = allocate_shape_id()
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
                fallback_rid = fallback_rids.get(position)
                choice_has_visible_fallback = (
                    node.portable_fallback is not None
                    and fallback_rid is not None
                    and node.effect_container != "sibling"
                    and not _paints_native_backdrop_blur(node)
                    and (
                        not (
                            node.effects
                            and all(isinstance(effect, FillOverlay) for effect in node.effects)
                        )
                        or any(
                            isinstance(effect, FillOverlay)
                            and (isinstance(effect.fill, PatternFill) or effect.blend == "over")
                            for effect in node.effects
                        )
                    )
                )
                native_xml = shape_xml(
                    node,
                    shape_id=shape_id,
                    blip_rid=blip_rid,
                    svg_rid=svg_rids.get(position),
                    hyperlink_rid=_hyperlink_rid,
                    hidden=choice_has_visible_fallback,
                )
                if node.portable_fallback is None or fallback_rid is None:
                    content_parts.append(native_xml)
                else:
                    fallback_node = node.model_copy(
                        update={
                            "box": node.portable_fallback.box,
                            "geom": "rect",
                            "custom_geom": None,
                            "fill": node.portable_fallback.picture,
                            "line": None,
                            "side_lines": None,
                            "effects": (),
                            "native_effect_projection": "complete",
                            "portable_fallback": None,
                            "transform": None,
                            "corner_radius_emu": 0,
                            "opacity": 1.0,
                            "text": None,
                        }
                    )
                    choice_fallback_xml = picture_xml(
                        fallback_node,
                        shape_id=allocate_shape_id(),
                        blip_rid=fallback_rid,
                    )
                    fallback_xml = picture_xml(
                        fallback_node,
                        shape_id=allocate_shape_id(),
                        blip_rid=fallback_rid,
                    )
                    choice_fallback = choice_fallback_xml if choice_has_visible_fallback else ""
                    content_parts.append(
                        "<mc:AlternateContent "
                        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                        'xmlns:p16="http://schemas.microsoft.com/office/powerpoint/2015/main">'
                        f'<mc:Choice Requires="p16">{native_xml}{choice_fallback}</mc:Choice>'
                        f"<mc:Fallback>{fallback_xml}</mc:Fallback>"
                        "</mc:AlternateContent>"
                    )
        elif isinstance(node, GroupNode):
            content_parts.append(group_xml(node, shape_id=shape_id))
        elif isinstance(node, Connector):
            content_parts.append(_connector_xml(node, shape_id=shape_id))
        elif isinstance(node, TableNode):
            content_parts.append(table_xml(node, shape_id=shape_id))
        elif isinstance(node, MediaNode):
            if position in web_frames:
                content_parts.append(_web_viewer_xml(node, shape_id, web_frames[position]))
            elif position in media_links:
                content_parts.append(_media_xml(node, shape_id, *media_links[position]))
        else:
            native_xml = rewrite_root_xml(
                node,
                shape_id=shape_id,
                allocate_shape_id=allocate_shape_id,
                relationship_ids=preserved_rids[position],
            )
            fallback_rid = fallback_rids.get(position)
            if node.payload.kind != "sp" or node.fallback is None or fallback_rid is None:
                content_parts.append(native_xml)
            else:
                raster_role = (
                    "pptx-source-rasterized"
                    if node.fallback_representation == "rasterized"
                    else "pptx-source-fallback"
                )
                fallback_node = ShapeNode(
                    box=node.box,
                    fill=node.fallback.model_copy(update={"raster_role": raster_role}),
                )
                fallback_xml = picture_xml(
                    fallback_node,
                    shape_id=allocate_shape_id(),
                    blip_rid=fallback_rid,
                )
                content_parts.append(
                    "<mc:AlternateContent "
                    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                    'xmlns:p16="http://schemas.microsoft.com/office/powerpoint/2015/main">'
                    f'<mc:Choice Requires="p16">{native_xml}</mc:Choice>'
                    f"<mc:Fallback>{fallback_xml}</mc:Fallback>"
                    "</mc:AlternateContent>"
                )
    contents = "".join(content_parts)
    if slide.renderer_fallback is not None and slide_fallback_rid is not None:
        fallback_node = ShapeNode(
            box=Box(x=0, y=0, width=slide.width, height=slide.height),
            fill=slide.renderer_fallback.model_copy(
                update={"raster_role": "pptx-slide-rasterized"}
            ),
        )
        fallback_xml = picture_xml(
            fallback_node,
            shape_id=allocate_shape_id(),
            blip_rid=slide_fallback_rid,
        )
        contents = (
            "<mc:AlternateContent "
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            'xmlns:p16="http://schemas.microsoft.com/office/powerpoint/2015/main">'
            f'<mc:Choice Requires="p16">{contents}</mc:Choice>'
            f"<mc:Fallback>{fallback_xml}</mc:Fallback>"
            "</mc:AlternateContent>"
        )
    # The output has its own master, so a background the slide only inherited from a source
    # master is written onto the slide itself.
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
        _slide_rels(slide_part, image_rels, hyperlink_rels, preserved_rels, extra_rels),
        media_parts,
        has_svg,
        preserved_parts,
        preserved_theme,
    )


_WEB_NS = "http://schemas.microsoft.com/office/webextensions/webextension/2010/11"
_WEB_REL = "http://schemas.microsoft.com/office/2011/relationships/webextension"
_WEB_CT = "application/vnd.ms-office.webextension+xml"


def _web_extension(
    url: str, part_name: str, snapshot_part: str, rid_number: int
) -> tuple[PreservationPart, str]:
    """The Web Viewer extension part for ``url`` (snapshot image included) and its slide rid."""
    digest = hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest().upper()
    guid = f"{{{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}}}"
    xml = (
        f'{t.XML_DECL}<we:webextension xmlns:we="{_WEB_NS}" xmlns:r="{_REL_TYPE}" id="{guid}">'
        f'<we:reference id="{WEB_VIEWER_ID}" version="1.0.0.0" store="en-US" storeType="OMEX"/>'
        '<we:alternateReferences/><we:properties><we:property name="url" '
        f'value="&quot;{_attr(url)}&quot;"/></we:properties><we:bindings/>'
        '<we:snapshot r:embed="rId1"/></we:webextension>'
    )
    part = PreservationPart(
        name=part_name,
        content_type=_WEB_CT,
        data=xml.encode(),
        relationships=(
            PreservationRelationship(id="rId1", type=f"{_REL_TYPE}/image", target=snapshot_part),
        ),
    )
    return part, f"rId{rid_number}"


def _web_viewer_xml(node: MediaNode, shape_id: int, rid: str) -> str:
    """A Web Viewer frame: a graphic frame pointing at the page's extension part."""
    return (
        f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{shape_id}" name="Web Viewer {shape_id}"'
        f"{alt_text_attr(node)}/>"
        f"<p:cNvGraphicFramePr/><p:nvPr>{node_identity_xml(node)}</p:nvPr></p:nvGraphicFramePr>"
        f'<p:xfrm><a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/></p:xfrm>'
        f'<a:graphic><a:graphicData uri="{_WEB_NS}">'
        f'<we:webextensionref xmlns:we="{_WEB_NS}" r:id="{rid}"/>'
        "</a:graphicData></a:graphic></p:graphicFrame>"
    )


def _media_xml(
    node: MediaNode, shape_id: int, link_rid: str, embed_rid: str | None, poster_rid: str
) -> str:
    """A video or audio clip: its poster picture carrying the media link PowerPoint plays."""
    tag = "videoFile" if node.kind == "video" else "audioFile"
    extensions = node_identity_ext_xml(node)
    if embed_rid is not None:
        extensions += (
            '<p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}">'
            '<p14:media xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" '
            f'r:embed="{embed_rid}"/></p:ext>'
        )
    extension_list = f"<p:extLst>{extensions}</p:extLst>" if extensions else ""
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="{node.kind.title()} {shape_id}"'
        f"{alt_text_attr(node)}/>"
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        f'<p:nvPr><a:{tag} r:link="{link_rid}"/>{_play_settings(node)}{extension_list}</p:nvPr>'
        "</p:nvPicPr>"
        f'<p:blipFill><a:blip r:embed="{poster_rid}"/><a:stretch><a:fillRect/></a:stretch>'
        "</p:blipFill><p:spPr>"
        f'<a:xfrm><a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )


def _play_settings(node: MediaNode) -> str:
    """The clip's recovered ``p:videoPr``/``p:audioPr``, if it is that element and well formed."""
    if node.play_settings_xml is None:
        return ""
    try:
        root = ElementTree.fromstring(node.play_settings_xml)
    except ElementTree.ParseError:
        return ""
    expected = f"{{{_PML_NS}}}{'videoPr' if node.kind == 'video' else 'audioPr'}"
    return node.play_settings_xml if root.tag == expected else ""


def _paints_native_backdrop_blur(node: ShapeNode) -> bool:
    """Whether ``node`` is the sharp backdrop picture PowerPoint should blur itself.

    Other portable fallbacks show their exact baked picture in PowerPoint as well and keep the
    native shape hidden. A backdrop blur is the opposite: the native, editable blur is the point,
    so only renderers that ignore it fall back to the picture.
    """
    return (
        isinstance(node.fill, PictureFill)
        and node.fill.raster_role == "backdrop-layer"
        and any(isinstance(effect, Blur) for effect in node.effects)
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

    notes_slides = tuple(i for i, slide in enumerate(slides, start=1) if slide.notes)
    notes_master_rid = f"rId{n + 2 + len(font_rels)}" if notes_slides else None
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types(
            n,
            notes_slides=notes_slides,
            has_fonts=bool(font_rels),
            image_exts=image_exts,
            has_svg=has_svg,
            preserved_content_types={
                part_name: preserved.content_type
                for part_name, preserved in preserved_parts.items()
            },
        ),
        "_rels/.rels": t.ROOT_RELS,
        "ppt/presentation.xml": _presentation(width, height, n, font_rels, notes_master_rid),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(n, font_rels, notes_master_rid),
        "ppt/theme/theme1.xml": preserved_theme.data if preserved_theme is not None else t.THEME,
        "ppt/slideMasters/slideMaster1.xml": t.SLIDE_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": t.SLIDE_MASTER_RELS,
        "ppt/slideLayouts/slideLayout1.xml": t.SLIDE_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": t.SLIDE_LAYOUT_RELS,
    }
    for face, part, _rid in font_rels:
        parts[part] = face.data
    parts.update(slide_parts)
    if notes_slides:
        parts["ppt/notesMasters/notesMaster1.xml"] = NOTES_MASTER
        parts["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = NOTES_MASTER_RELS
        parts["ppt/theme/theme2.xml"] = t.THEME
        for i in notes_slides:
            parts[f"ppt/notesSlides/notesSlide{i}.xml"] = notes_slide_xml(slides[i - 1].notes or "")
            parts[f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels"] = notes_slide_rels(i)
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
