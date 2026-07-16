"""Read PresentationML into PowerPoint canvas IR."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from domoxml.core.fontsread import ReverseFontFace, read_embedded_fonts
from domoxml.core.ir.model import (
    Box,
    ClosePath,
    CubicTo,
    CustomGeometry,
    Geometry,
    GeometryKind,
    GroupNode,
    Hyperlink,
    LineTo,
    MoveTo,
    Node,
    PathCommand,
    Point,
    QuadTo,
    ShapeNode,
    SlideIR,
    Transform,
)
from domoxml.core.opc import OpcPackage
from domoxml.slides.appearance_read import (
    DEFAULT_THEME_COLORS,
    ThemeColors,
)
from domoxml.slides.appearance_read import (
    fill as _fill,
)
from domoxml.slides.appearance_read import (
    line as _line,
)
from domoxml.slides.appearance_read import (
    line_element as _line_element,
)
from domoxml.slides.appearance_read import (
    picture as _picture,
)
from domoxml.slides.appearance_read import (
    rgb_hex as _rgb_hex,
)
from domoxml.slides.appearance_read import (
    rgba as _rgba,
)
from domoxml.slides.background import parse_background
from domoxml.slides.connector_read import read_connector
from domoxml.slides.effect_read import read_effects
from domoxml.slides.graphic_frame import read_graphic_frame
from domoxml.slides.inherit import (
    PlaceholderContext,
    ThemeContext,
    build_placeholder_context,
    inherit_sppr_child,
    inherit_xfrm,
    parse_theme_fonts,
)
from domoxml.slides.media_read import read_media
from domoxml.slides.text_read import read_text_body, read_text_run
from domoxml.slides.transition import parse_transition
from domoxml.types import ConversionWarning, PreservedFragment

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A, "p": _P, "r": _R}
_RID = f"{{{_R}}}id"
_LINK = f"{{{_R}}}link"
_RASTER_MARKER_PREFIX = "domoxml-raster:"
_OFFICE_DOCUMENT_REL = f"{_R}/officeDocument"
_HYPERLINK_REL = f"{_R}/hyperlink"
_SLIDE_REL = f"{_R}/slide"
_SLIDE_JUMP_ACTION = "ppaction://hlinksldjump"
_SLIDE_LAYOUT_REL = f"{_R}/slideLayout"
_SLIDE_MASTER_REL = f"{_R}/slideMaster"
_THEME_REL = f"{_R}/theme"


# ---------------------------------------------------------------------------
# Per-slide inheritance context (layout/master/theme XML roots).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SlideInheritCtx:
    """Pre-parsed layout and master XML roots for one slide, plus theme context.

    Used by ``_shape`` and the text adapter to resolve placeholder inheritance."""

    layout_root: Element | None
    master_root: Element | None
    theme_ctx: ThemeContext


@dataclass(frozen=True)
class PptxReadResult:
    """Canvas slides plus reverse-adapter diagnostics and retained OOXML."""

    slides: tuple[SlideIR, ...]
    warnings: tuple[ConversionWarning, ...] = ()
    preserved: tuple[PreservedFragment, ...] = ()
    embedded_fonts: tuple[ReverseFontFace, ...] = ()


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    value = element.get(name)
    return int(value) if value is not None else default


def _related_part_by_type(
    package: OpcPackage, source_part: str, relationship_type: str
) -> str | None:
    try:
        return package.related_part_by_type(source_part, relationship_type)
    except KeyError:
        return None


def _custGeom(element: Element) -> CustomGeometry | None:
    """Parse ``a:custGeom`` from a shape's ``spPr`` and return a :class:`CustomGeometry`."""
    path_el = element.find(f"{{{_A}}}pathLst/{{{_A}}}path")
    if path_el is None:
        return None
    width_emu_raw = path_el.get("w")
    height_emu_raw = path_el.get("h")
    if width_emu_raw is None or height_emu_raw is None:
        return None
    try:
        width_emu = int(width_emu_raw)
        height_emu = int(height_emu_raw)
    except ValueError:
        return None
    if width_emu <= 0 or height_emu <= 0:
        return None
    commands: list[PathCommand] = []
    for child in path_el:
        local = child.tag.rsplit("}", 1)[-1]
        if local == "moveTo":
            pt = child.find(f"{{{_A}}}pt")
            if pt is not None:
                commands.append(MoveTo(to=Point(x=int(pt.get("x", 0)), y=int(pt.get("y", 0)))))
        elif local == "lnTo":
            pt = child.find(f"{{{_A}}}pt")
            if pt is not None:
                commands.append(LineTo(to=Point(x=int(pt.get("x", 0)), y=int(pt.get("y", 0)))))
        elif local == "cubicBezTo":
            pts = child.findall(f"{{{_A}}}pt")
            if len(pts) >= 3:
                commands.append(
                    CubicTo(
                        c1=Point(x=int(pts[0].get("x", 0)), y=int(pts[0].get("y", 0))),
                        c2=Point(x=int(pts[1].get("x", 0)), y=int(pts[1].get("y", 0))),
                        to=Point(x=int(pts[2].get("x", 0)), y=int(pts[2].get("y", 0))),
                    )
                )
        elif local == "quadBezTo":
            pts = child.findall(f"{{{_A}}}pt")
            if len(pts) >= 2:
                commands.append(
                    QuadTo(
                        c1=Point(x=int(pts[0].get("x", 0)), y=int(pts[0].get("y", 0))),
                        to=Point(x=int(pts[1].get("x", 0)), y=int(pts[1].get("y", 0))),
                    )
                )
        elif local == "close":
            commands.append(ClosePath())
    return CustomGeometry(width_emu=width_emu, height_emu=height_emu, path=tuple(commands))


def _xfrm_transform(xfrm: Element | None) -> Transform | None:
    """Parse ``a:xfrm`` attributes into a :class:`Transform`, or ``None`` for identity.

    OOXML ``rot`` is in 60000ths of a degree, clockwise-positive — same as CSS ``rotate()``.
    ``flipH``/``flipV`` are ``"1"`` when set.
    """
    if xfrm is None:
        return None
    rot_raw = xfrm.get("rot")
    flip_h = xfrm.get("flipH") == "1"
    flip_v = xfrm.get("flipV") == "1"
    rotation_deg = int(rot_raw) / 60_000 if rot_raw is not None else 0.0
    if rotation_deg == 0.0 and not flip_h and not flip_v:
        return None
    return Transform(rotation_deg=rotation_deg, flip_h=flip_h, flip_v=flip_v)


def _shape(
    element: Element,
    package: OpcPackage,
    slide_part: str,
    colors: ThemeColors,
    hyperlink_for: Callable[[Element], Hyperlink | None],
    *,
    inherit_ctx: _SlideInheritCtx | None = None,
) -> tuple[ShapeNode | None, tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    properties = element.find("p:spPr", _NS)

    # Build placeholder context for this shape (used for geometry + text inheritance).
    ph_ctx: PlaceholderContext | None = None
    if inherit_ctx is not None:
        ph_ctx = build_placeholder_context(
            element, inherit_ctx.layout_root, inherit_ctx.master_root
        )

    # Resolve effective a:xfrm: slide spPr first, then layout/master placeholder chain.
    xfrm = properties.find("a:xfrm", _NS) if properties is not None else None

    # Fallback via placeholder inheritance when slide xfrm is absent.
    if xfrm is None and ph_ctx is not None:
        xfrm = inherit_xfrm(properties, ph_ctx)

    offset = xfrm.find("a:off", _NS) if xfrm is not None else None
    extent = xfrm.find("a:ext", _NS) if xfrm is not None else None
    if properties is None or offset is None or extent is None:
        return None, (), ()
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )
    geometry = properties.find("a:prstGeom", _NS)
    # Geometry may also be inherited (e.g. placeholder with no shape of its own).
    if geometry is None and ph_ctx is not None:
        geom_el = inherit_sppr_child("a:prstGeom", properties, ph_ctx)
        geometry = geom_el
    geom_name = geometry.get("prst", "rect") if geometry is not None else "rect"
    # Map the OOXML prstGeom name onto a GeometryKind literal. Any name that is a valid
    # GeometryKind passes through directly; unknown names fall back to "rect" so the shape
    # is still readable (geometry just loses its silhouette).
    _valid_geom_kinds: frozenset[str] = frozenset(GeometryKind.__args__)  # type: ignore[attr-defined]
    geom: Geometry = geom_name if geom_name in _valid_geom_kinds else "rect"  # type: ignore[assignment]
    guide = geometry.find("a:avLst/a:gd", _NS) if geometry is not None else None
    formula = guide.get("fmla", "") if guide is not None else ""
    corner = 0
    if geom == "roundRect" and formula.startswith("val "):
        try:
            corner = round(int(formula.removeprefix("val ")) / 100_000 * min(box.width, box.height))
        except (TypeError, ValueError):
            corner = 0
    shape_effects, effect_warns, effect_preserved = read_effects(
        properties, lambda element: _rgba(element, colors)
    )
    custgeom_el = properties.find(f"{{{_A}}}custGeom")
    custom_geom = _custGeom(custgeom_el) if custgeom_el is not None else None
    return (
        ShapeNode(
            box=box,
            geom=geom,
            custom_geom=custom_geom,
            fill=_fill(properties, package, slide_part, colors),
            line=_line(properties, colors),
            effects=shape_effects,
            corner_radius_emu=corner,
            transform=_xfrm_transform(xfrm),
            text=read_text_body(
                element,
                colors,
                hyperlink_for,
                ph_ctx=ph_ctx,
                theme_ctx=inherit_ctx.theme_ctx if inherit_ctx is not None else None,
            ),
        ),
        effect_warns,
        effect_preserved,
    )


def _raster_role(element: Element) -> str | None:
    """Read the decorative-raster marker the forward writer leaves on ``p:cNvPr descr``."""
    cnvpr = element.find("p:nvPicPr/p:cNvPr", _NS)
    descr = cnvpr.get("descr", "") if cnvpr is not None else ""
    if descr.startswith(_RASTER_MARKER_PREFIX):
        return descr.removeprefix(_RASTER_MARKER_PREFIX) or "decorative"
    return None


def _picture_shape(element: Element, package: OpcPackage, slide_part: str) -> ShapeNode | None:
    properties = element.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    fill = element.find("p:blipFill", _NS)
    if properties is None or offset is None or extent is None or fill is None:
        return None
    picture = _picture(fill, package, slide_part, raster_role=_raster_role(element))
    if picture is None:
        return None
    return ShapeNode(
        box=Box(
            x=_int_attr(offset, "x"),
            y=_int_attr(offset, "y"),
            width=_int_attr(extent, "cx"),
            height=_int_attr(extent, "cy"),
        ),
        fill=picture,
    )


def _local_name(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _preserve(
    slide_part: str, element: Element, reason: str
) -> tuple[ConversionWarning, PreservedFragment]:
    kind = _local_name(element)
    return (
        ConversionWarning(message=reason, element=f"{slide_part}:{kind}"),
        PreservedFragment(
            part=slide_part,
            kind=kind,
            xml=ElementTree.tostring(element, encoding="unicode"),
        ),
    )


def _hyperlink_resolver(
    package: OpcPackage, slide_part: str, slide_index_by_part: dict[str, int]
) -> Callable[[Element], Hyperlink | None]:
    """A resolver from a run's ``a:rPr`` to its :class:`Hyperlink`.

    An external ``a:hlinkClick r:id`` becomes a URL from the rel target; a slide-jump
    (``action="ppaction://hlinksldjump"``) resolves its internal rel to the destination slide
    part and recovers its zero-based deck index. Missing/empty links yield ``None``."""
    relationships = {rel.id: rel for rel in package.relationships(slide_part)}

    def resolve(properties: Element) -> Hyperlink | None:
        click = properties.find("a:hlinkClick", _NS)
        if click is None:
            return None
        rid = click.get(_RID)
        action = click.get("action", "")
        if action == _SLIDE_JUMP_ACTION:
            if rid and rid in relationships:
                target = package.resolve(slide_part, relationships[rid])
                index = slide_index_by_part.get(target)
                if index is not None:
                    return Hyperlink(slide_index=index)
            return None
        if not rid:
            return None
        relationship = relationships.get(rid)
        if relationship is None:
            return None
        if relationship.target_mode != "Internal":
            return Hyperlink(url=relationship.target)
        # An internal slide target without the jump action is still an in-deck jump.
        target = package.resolve(slide_part, relationship)
        index = slide_index_by_part.get(target)
        return Hyperlink(slide_index=index) if index is not None else None

    return resolve


def _build_slide_inherit_ctx(package: OpcPackage, slide_part: str) -> _SlideInheritCtx:
    """Build the per-slide inheritance context (layout/master XML + theme fonts).

    This is called once per slide and the result is shared by all shapes on that slide."""
    layout_root: Element | None = None
    master_root: Element | None = None

    layout_part = _related_part_by_type(package, slide_part, _SLIDE_LAYOUT_REL)
    if layout_part is not None:
        with contextlib.suppress(KeyError):
            layout_root = ElementTree.fromstring(package.read(layout_part))

    master_part: str | None = None
    if layout_part is not None:
        master_part = _related_part_by_type(package, layout_part, _SLIDE_MASTER_REL)
    if master_part is not None:
        with contextlib.suppress(KeyError):
            master_root = ElementTree.fromstring(package.read(master_part))

    # Theme fonts for +mj-lt / +mn-lt sentinel resolution.
    theme_part: str | None = None
    if master_part is not None:
        theme_part = _related_part_by_type(package, master_part, _THEME_REL)
    major_latin = "Calibri Light"
    minor_latin = "Calibri"
    if theme_part is not None:
        with contextlib.suppress(KeyError):
            theme_root = ElementTree.fromstring(package.read(theme_part))
            major_latin, minor_latin = parse_theme_fonts(theme_root)

    # Build colors dict for scheme color resolution in text runs.
    colors = _slide_colors(package, slide_part)
    theme_ctx = ThemeContext(
        major_latin=major_latin,
        minor_latin=minor_latin,
        colors=colors,
    )
    return _SlideInheritCtx(
        layout_root=layout_root,
        master_root=master_root,
        theme_ctx=theme_ctx,
    )


def _group_node(
    element: Element,
    package: OpcPackage,
    slide_part: str,
    colors: ThemeColors,
    hyperlink_for: Callable[[Element], Hyperlink | None],
    *,
    inherit_ctx: _SlideInheritCtx | None = None,
) -> tuple[GroupNode | None, tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    """Parse a ``p:grpSp`` element into a :class:`GroupNode`.

    The group transform is read from ``p:grpSpPr/a:xfrm``.  Children (``p:sp``, ``p:pic``,
    nested ``p:grpSp``) are parsed recursively and returned as the group's ``children`` tuple.
    The child coordinate space (``a:chOff``/``a:chExt``) is stored in ``child_box`` so
    :mod:`domoxml.core.html` can map child positions into slide EMU space.

    ``p:graphicFrame`` and unknown child element types inside the group are preserved.
    """
    grp_spr = element.find("p:grpSpPr", _NS)
    xfrm = grp_spr.find("a:xfrm", _NS) if grp_spr is not None else None
    if xfrm is None:
        return None, (), ()

    offset = xfrm.find("a:off", _NS)
    extent = xfrm.find("a:ext", _NS)
    ch_off = xfrm.find("a:chOff", _NS)
    ch_ext = xfrm.find("a:chExt", _NS)
    if offset is None or extent is None or ch_off is None or ch_ext is None:
        return None, (), ()

    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )
    child_box = Box(
        x=_int_attr(ch_off, "x"),
        y=_int_attr(ch_off, "y"),
        width=_int_attr(ch_ext, "cx"),
        height=_int_attr(ch_ext, "cy"),
    )

    children: list[ShapeNode | GroupNode] = []
    all_warns: list[ConversionWarning] = []
    all_preserved: list[PreservedFragment] = []

    for child in element:
        child_kind = _local_name(child)
        if child_kind in {"nvGrpSpPr", "grpSpPr"}:
            continue
        if child_kind == "sp":
            shape, warns, preserved = _shape(
                child, package, slide_part, colors, hyperlink_for, inherit_ctx=inherit_ctx
            )
            if shape is not None:
                children.append(shape)
            all_warns.extend(warns)
            all_preserved.extend(preserved)
        elif child_kind == "pic":
            pic_shape = _picture_shape(child, package, slide_part)
            if pic_shape is not None:
                children.append(pic_shape)
        elif child_kind == "grpSp":
            nested, warns, preserved = _group_node(
                child, package, slide_part, colors, hyperlink_for, inherit_ctx=inherit_ctx
            )
            if nested is not None:
                children.append(nested)
            all_warns.extend(warns)
            all_preserved.extend(preserved)
        else:
            warn, frag = _preserve(slide_part, child, f"unsupported element in grpSp: {child_kind}")
            all_warns.append(warn)
            all_preserved.append(frag)

    return (
        GroupNode(
            box=box,
            child_box=child_box,
            children=tuple(children),
            transform=_xfrm_transform(xfrm),
        ),
        tuple(all_warns),
        tuple(all_preserved),
    )


def _slide(
    package: OpcPackage,
    slide_part: str,
    *,
    width: int,
    height: int,
    slide_index_by_part: dict[str, int],
) -> tuple[SlideIR, tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    colors = _slide_colors(package, slide_part)
    hyperlink_for = _hyperlink_resolver(package, slide_part, slide_index_by_part)
    root = ElementTree.fromstring(package.read(slide_part))
    tree = root.find("./p:cSld/p:spTree", _NS)
    inherit_ctx = _build_slide_inherit_ctx(package, slide_part)
    shapes: list[ShapeNode] = []
    nodes: list[Node] = []
    warnings: list[ConversionWarning] = []
    preserved: list[PreservedFragment] = []

    # --- Slide-level: background (p:cSld/p:bg) ---
    background = parse_background(
        root, lambda properties: _fill(properties, package, slide_part, colors)
    )

    # --- Slide-level: transition (p:transition, sibling of p:cSld) ---
    transition_el = root.find("p:transition", _NS)
    transition = parse_transition(transition_el) if transition_el is not None else None

    # --- Slide-level: timing/animations (p:timing, sibling of p:cSld) ---
    timing_el = root.find("p:timing", _NS)
    if timing_el is not None:
        warn, frag = _preserve(
            slide_part,
            timing_el,
            "p:timing (slide animations) has no CSS mapping; preserved as fragment",
        )
        warnings.append(warn)
        preserved.append(frag)

    if tree is not None:
        for element in tree:
            kind = _local_name(element)
            if kind in {"nvGrpSpPr", "grpSpPr"}:
                continue
            if kind == "sp":
                shape, shape_warns, shape_preserved = _shape(
                    element,
                    package,
                    slide_part,
                    colors,
                    hyperlink_for,
                    inherit_ctx=inherit_ctx,
                )
                if shape is not None:
                    shapes.append(shape)
                    warnings.extend(shape_warns)
                    preserved.extend(shape_preserved)
                    if not shape_preserved:
                        continue
                reason = "preserved shape that the reverse adapter could not map"
            elif kind == "pic":
                # Video/audio pics carry a media relationship — recover as a MediaNode.
                media = read_media(
                    element,
                    package,
                    slide_part,
                    lambda fill: _picture(fill, package, slide_part),
                )
                if media is not None:
                    nodes.append(media)
                    continue
                shape = _picture_shape(element, package, slide_part)
                if shape is not None:
                    # The crop (a:srcRect) is recovered into the PictureFill and emitted as
                    # background-size/position by the HTML writer, so nothing is preserved.
                    shapes.append(shape)
                    continue
                reason = "preserved picture that the reverse adapter could not map"
            elif kind == "cxnSp":
                connector = read_connector(element, lambda properties: _line(properties, colors))
                if connector is not None:
                    nodes.append(connector)
                    continue
                reason = "preserved connector that the reverse adapter could not map"
            elif kind == "grpSp":
                group, group_warns, group_preserved = _group_node(
                    element,
                    package,
                    slide_part,
                    colors,
                    hyperlink_for,
                    inherit_ctx=inherit_ctx,
                )
                if group is not None:
                    nodes.append(group)
                    warnings.extend(group_warns)
                    preserved.extend(group_preserved)
                    continue
                reason = "preserved group that the reverse adapter could not map"
            elif kind == "graphicFrame":
                frame = read_graphic_frame(
                    element,
                    fill_for=lambda properties: _fill(properties, package, slide_part, colors),
                    line_for=lambda line: _line_element(line, colors),
                    text_run_for=lambda run: read_text_run(run, colors, hyperlink_for),
                    theme_colors=colors,
                    default_font_family=inherit_ctx.theme_ctx.minor_latin,
                )
                if frame.table is not None:
                    nodes.append(frame.table)
                    continue
                reason = frame.reason or "preserved unsupported graphicFrame"
            elif kind == "oleObj":
                reason = "p:oleObj (OLE object) has no HTML mapping; preserved as fragment"
            else:
                reason = f"preserved unsupported reverse slide node: {kind}"
            warning, fragment = _preserve(slide_part, element, reason)
            warnings.append(warning)
            preserved.append(fragment)
    return (
        SlideIR(
            width=width,
            height=height,
            shapes=tuple(shapes),
            nodes=tuple(nodes),
            transition=transition,
            background=background,
        ),
        tuple(warnings),
        tuple(preserved),
    )


def _theme_colors(package: OpcPackage, theme_part: str | None) -> ThemeColors:
    colors = dict(DEFAULT_THEME_COLORS)
    if theme_part is None:
        theme_parts = [part for part in package.parts if part.startswith("ppt/theme/")]
        theme_part = theme_parts[0] if theme_parts else None
    if theme_part is None:
        return colors
    root = ElementTree.fromstring(package.read(theme_part))
    scheme = root.find("a:themeElements/a:clrScheme", _NS)
    if scheme is None:
        return colors
    for element in scheme:
        value = _rgb_hex(element, colors)
        if value is not None:
            colors[element.tag.rsplit("}", 1)[-1]] = value
    return colors


def _color_map(package: OpcPackage, part: str | None, path: str) -> dict[str, str]:
    if part is None:
        return {}
    root = ElementTree.fromstring(package.read(part))
    element = root.find(path, _NS)
    return dict(element.attrib) if element is not None else {}


def _slide_colors(package: OpcPackage, slide_part: str) -> ThemeColors:
    layout_part = _related_part_by_type(package, slide_part, _SLIDE_LAYOUT_REL)
    master_part = (
        _related_part_by_type(package, layout_part, _SLIDE_MASTER_REL)
        if layout_part is not None
        else None
    )
    theme_part = (
        _related_part_by_type(package, master_part, _THEME_REL) if master_part is not None else None
    )
    colors = _theme_colors(package, theme_part)
    mapping = _color_map(package, master_part, "p:clrMap")
    mapping.update(_color_map(package, layout_part, "p:clrMapOvr/a:overrideClrMapping"))
    mapping.update(_color_map(package, slide_part, "p:clrMapOvr/a:overrideClrMapping"))
    return {**colors, **{key: colors.get(value, value) for key, value in mapping.items()}}


def read_pptx_result(pptx: bytes) -> PptxReadResult:
    """Read a PPTX package into ordered canvas slides plus reverse diagnostics."""
    package = OpcPackage.from_bytes(pptx)
    presentation_part = package.related_part_by_type(None, _OFFICE_DOCUMENT_REL)
    root = ElementTree.fromstring(package.read(presentation_part))
    size = root.find("p:sldSz", _NS)
    if size is None:
        raise ValueError("PPTX presentation has no slide size")
    width, height = _int_attr(size, "cx"), _int_attr(size, "cy")
    slide_ids = root.findall("p:sldIdLst/p:sldId", _NS)
    slide_parts = [
        package.related_part(presentation_part, slide_id.attrib[_RID]) for slide_id in slide_ids
    ]
    # Deck-order index per slide part, so a slide-jump rel can recover its zero-based target.
    slide_index_by_part = {part: index for index, part in enumerate(slide_parts)}
    results = [
        _slide(
            package,
            slide_part,
            width=width,
            height=height,
            slide_index_by_part=slide_index_by_part,
        )
        for slide_part in slide_parts
    ]
    font_faces, font_warnings = read_embedded_fonts(package, root, presentation_part)
    all_warnings = tuple(warning for result in results for warning in result[1]) + tuple(
        font_warnings
    )
    return PptxReadResult(
        slides=tuple(result[0] for result in results),
        warnings=all_warnings,
        preserved=tuple(fragment for result in results for fragment in result[2]),
        embedded_fonts=tuple(font_faces),
    )


def read_pptx(pptx: bytes) -> list[SlideIR]:
    """Read a PPTX package into ordered canvas slides."""
    return list(read_pptx_result(pptx).slides)
