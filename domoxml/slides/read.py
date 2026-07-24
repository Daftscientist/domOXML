"""Read PresentationML into PowerPoint canvas IR."""

from __future__ import annotations

import contextlib
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from domoxml.core.drawingml.identity import NAMESPACE as IDENTITY_NAMESPACE
from domoxml.core.fontsread import ReverseFontFace, read_embedded_fonts
from domoxml.core.images import crop_slide_region
from domoxml.core.ir.model import (
    Box,
    CanvasNode,
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
    PictureFill,
    Point,
    PortableFallback,
    PreservedNode,
    QuadTo,
    ShapeNode,
    SlideIR,
    SolidFill,
    SourceProvenance,
    Transform,
)
from domoxml.core.opc import OpcPackage, capture_payload
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
from domoxml.types import (
    ConversionWarning,
    CoverageItem,
    CoverageReport,
    Editability,
    PreservedFragment,
    Representation,
    SourceRetention,
)

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A, "p": _P, "r": _R, "dx": IDENTITY_NAMESPACE}
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
    theme_part: str | None = None


@dataclass(frozen=True)
class PptxReadResult:
    """Canvas slides plus reverse-adapter diagnostics and retained OOXML."""

    slides: tuple[SlideIR, ...]
    warnings: tuple[ConversionWarning, ...] = ()
    preserved: tuple[PreservedFragment, ...] = ()
    embedded_fonts: tuple[ReverseFontFace, ...] = ()
    coverage: CoverageReport = field(default_factory=lambda: CoverageReport(items=()))


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    value = element.get(name)
    return int(value) if value is not None else default


def _with_pptx_identity[T: CanvasNode](output: T, element: Element, slide_part: str) -> T:
    """Recover domOXML metadata or derive identity from PowerPoint's non-visual ID."""
    non_visual = element.find("./*/p:cNvPr", _NS)
    source_id = non_visual.get("id", "unknown") if non_visual is not None else "unknown"
    metadata = element.find("./*/p:nvPr/p:extLst/p:ext/dx:node", _NS)
    node_id = metadata.get("id") if metadata is not None else None
    if not node_id:
        node_id = f"pptx-{source_id}"
    source_format_raw = metadata.get("sourceFormat") if metadata is not None else None
    source_format: Literal["html", "pptx"] = "html" if source_format_raw == "html" else "pptx"
    provenance = SourceProvenance(
        source_format=source_format,
        source_id=(metadata.get("sourceId") if metadata is not None else None) or source_id,
        source_part=metadata.get("sourcePart") if metadata is not None else slide_part,
        owner_node_id=metadata.get("ownerId") if metadata is not None else None,
        role=metadata.get("role") if metadata is not None else None,
    )
    return output.model_copy(update={"node_id": node_id, "provenance": provenance})


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
        properties, lambda element: _rgba(element, colors), box=box
    )
    custgeom_el = properties.find(f"{{{_A}}}custGeom")
    custom_geom = _custGeom(custgeom_el) if custgeom_el is not None else None
    return (
        _with_pptx_identity(
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
            element,
            slide_part,
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
    return _with_pptx_identity(
        ShapeNode(
            box=Box(
                x=_int_attr(offset, "x"),
                y=_int_attr(offset, "y"),
                width=_int_attr(extent, "cx"),
                height=_int_attr(extent, "cy"),
            ),
            fill=picture,
        ),
        element,
        slide_part,
    )


def _local_name(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _visual_label(slide_part: str, element: Element) -> str:
    kind = _local_name(element)
    non_visual = element.find("./*/p:cNvPr", _NS)
    source_id = non_visual.get("id", "unknown") if non_visual is not None else "unknown"
    return f"{slide_part}:{kind}#{source_id}"


def _native_reverse_coverage(slide_part: str, element: Element) -> CoverageItem:
    return CoverageItem(
        element=_visual_label(slide_part, element),
        representation=Representation.NATIVE,
        editability=Editability.SEMANTIC,
    )


def _shape_reverse_coverage(
    slide_part: str,
    element: Element,
    *,
    has_preserved_effects: bool,
) -> CoverageItem:
    reasons: list[str] = []
    retention = SourceRetention.NOT_REQUIRED
    geometry = element.find("p:spPr/a:prstGeom", _NS)
    if geometry is not None:
        name = geometry.get("prst", "rect")
        valid_geometry = frozenset(GeometryKind.__args__)  # type: ignore[attr-defined]
        if name not in valid_geometry:
            reasons.append(f"unsupported preset geometry {name!r} mapped to a rectangle")
            retention = SourceRetention.LOST
    if has_preserved_effects:
        reasons.append("shape has detached source-only effect fragments")
        if retention is SourceRetention.NOT_REQUIRED:
            retention = SourceRetention.DETACHED
    if not reasons:
        return _native_reverse_coverage(slide_part, element)
    return CoverageItem(
        element=_visual_label(slide_part, element),
        representation=Representation.APPROXIMATED,
        editability=Editability.SEMANTIC,
        source_retention=retention,
        reason="; ".join(reasons),
    )


def _failed_reverse_coverage(
    slide_part: str,
    element: Element,
    reason: str,
    retention: SourceRetention,
) -> CoverageItem:
    return CoverageItem(
        element=_visual_label(slide_part, element),
        representation=Representation.FAILED,
        editability=Editability.NONE,
        source_retention=retention,
        output_count=0,
        reason=reason,
    )


def _group_output_count(group: GroupNode) -> int:
    return sum(
        _group_output_count(child) if isinstance(child, GroupNode) else 1
        for child in group.children
    )


def _group_reverse_coverage(
    slide_part: str,
    element: Element,
    group: GroupNode,
    *,
    has_preserved_children: bool,
) -> CoverageItem:
    output_count = _group_output_count(group)
    reason = "PowerPoint group flattened into positioned HTML children"
    if has_preserved_children:
        reason += "; unsupported group children retained as detached source fragments"
    if output_count == 0:
        return _failed_reverse_coverage(
            slide_part,
            element,
            reason,
            SourceRetention.LOST,
        )
    if output_count == 1:
        return CoverageItem(
            element=_visual_label(slide_part, element),
            representation=Representation.APPROXIMATED,
            editability=Editability.COMPONENTS,
            source_retention=SourceRetention.LOST,
            reason=reason,
        )
    return CoverageItem(
        element=_visual_label(slide_part, element),
        representation=Representation.DECOMPOSED,
        editability=Editability.COMPONENTS,
        source_retention=SourceRetention.LOST,
        output_count=output_count,
        reason=reason,
    )


def _connector_reverse_coverage(slide_part: str, element: Element) -> CoverageItem:
    return CoverageItem(
        element=_visual_label(slide_part, element),
        representation=Representation.APPROXIMATED,
        editability=Editability.SEMANTIC,
        source_retention=SourceRetention.LOST,
        reason="connector routing and exact endpoints are approximated from its transform box",
    )


def _positioned_box(element: Element) -> Box | None:
    """Return the axis-aligned paint box for a direct slide-tree visual when it has one."""
    kind = _local_name(element)
    transform = (
        element.find("p:xfrm", _NS)
        if kind in {"graphicFrame", "oleObj"}
        else element.find("p:grpSpPr/a:xfrm", _NS)
        if kind == "grpSp"
        else element.find("p:spPr/a:xfrm", _NS)
    )
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if offset is None or extent is None:
        return None
    assert transform is not None
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=max(1, _int_attr(extent, "cx")),
        height=max(1, _int_attr(extent, "cy")),
    )
    rotation = _int_attr(transform, "rot") / 60_000
    if rotation % 180 == 0:
        return box
    radians = math.radians(rotation)
    painted_width = abs(box.width * math.cos(radians)) + abs(box.height * math.sin(radians))
    painted_height = abs(box.width * math.sin(radians)) + abs(box.height * math.cos(radians))
    center_x = box.x + (box.width / 2)
    center_y = box.y + (box.height / 2)
    left = math.floor(center_x - (painted_width / 2))
    top = math.floor(center_y - (painted_height / 2))
    right = math.ceil(center_x + (painted_width / 2))
    bottom = math.ceil(center_y + (painted_height / 2))
    return Box(x=left, y=top, width=max(1, right - left), height=max(1, bottom - top))


def _rotated_rect_polygon(element: Element) -> tuple[tuple[float, float], ...] | None:
    """Return the rotated rectangle silhouette in slide EMUs, or ``None`` for no rotation."""
    transform = element.find("p:spPr/a:xfrm", _NS)
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if transform is None or offset is None or extent is None:
        return None
    rotation = _int_attr(transform, "rot") / 60_000
    if rotation % 180 == 0:
        return None
    width = max(1, _int_attr(extent, "cx"))
    height = max(1, _int_attr(extent, "cy"))
    center_x = _int_attr(offset, "x") + (width / 2)
    center_y = _int_attr(offset, "y") + (height / 2)
    radians = math.radians(rotation)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return tuple(
        (
            center_x + (x * cosine) - (y * sine),
            center_y + (x * sine) + (y * cosine),
        )
        for x, y in (
            (-width / 2, -height / 2),
            (width / 2, -height / 2),
            (width / 2, height / 2),
            (-width / 2, height / 2),
        )
    )


def _can_own_source_shape_crop(shape: ShapeNode, *, is_only_visual: bool) -> bool:
    """Whether a full-slide crop can be isolated into one independently movable shape layer."""
    return (
        is_only_visual
        and shape.geom == "rect"
        and shape.custom_geom is None
        and shape.corner_radius_emu == 0
        and isinstance(shape.fill, SolidFill)
        and shape.fill.color.a == 1.0
        and shape.opacity == 1.0
        and shape.line is None
        and not shape.effects
    )


def _fallback_picture(
    rendered_png: bytes | None,
    box: Box,
    *,
    slide_width: int,
    slide_height: int,
    mask_polygon: tuple[tuple[float, float], ...] | None = None,
) -> PictureFill | None:
    if rendered_png is None:
        return None
    crop = crop_slide_region(
        rendered_png,
        slide_width=slide_width,
        slide_height=slide_height,
        left=box.x,
        top=box.y,
        width=box.width,
        height=box.height,
        mask_polygon=mask_polygon,
    )
    return PictureFill(data=crop, ext="png") if crop is not None else None


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
        theme_part=theme_part,
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
        _with_pptx_identity(
            GroupNode(
                box=box,
                child_box=child_box,
                children=tuple(children),
                transform=_xfrm_transform(xfrm),
            ),
            element,
            slide_part,
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
    fallback_png: bytes | None = None,
) -> tuple[
    SlideIR,
    tuple[ConversionWarning, ...],
    tuple[PreservedFragment, ...],
    tuple[CoverageItem, ...],
]:
    colors = _slide_colors(package, slide_part)
    hyperlink_for = _hyperlink_resolver(package, slide_part, slide_index_by_part)
    root = ElementTree.fromstring(package.read(slide_part))
    tree = root.find("./p:cSld/p:spTree", _NS)
    inherit_ctx = _build_slide_inherit_ctx(package, slide_part)
    contents: list[Node] = []
    warnings: list[ConversionWarning] = []
    preserved: list[PreservedFragment] = []
    coverage: list[CoverageItem] = []

    # --- Slide-level: background (p:cSld/p:bg) ---
    background = parse_background(
        root, lambda properties: _fill(properties, package, slide_part, colors)
    )
    if background is not None:
        coverage.append(
            CoverageItem(
                element=f"{slide_part}:background",
                representation=Representation.NATIVE,
                editability=Editability.SEMANTIC,
            )
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
        tree_elements = tuple(tree)
        visual_elements = tuple(
            element
            for element in tree_elements
            if _local_name(element) not in {"nvGrpSpPr", "grpSpPr", "extLst"}
        )
        only_visual = visual_elements[0] if len(visual_elements) == 1 else None
        for element in tree_elements:
            kind = _local_name(element)
            preserved_owner_id: str | None = None
            preserve_whole_node = True
            fallback_representation: Literal["element_layer", "rasterized"] = "element_layer"
            fallback_box_override: Box | None = None
            fallback_mask: tuple[tuple[float, float], ...] | None = None
            reason = f"preserved unsupported reverse slide node: {kind}"
            if kind in {"nvGrpSpPr", "grpSpPr"}:
                continue
            if kind == "AlternateContent":
                choice = next((child for child in element if _local_name(child) == "Choice"), None)
                fallback_branch = next(
                    (child for child in element if _local_name(child) == "Fallback"), None
                )
                native = next(iter(choice), None) if choice is not None else None
                fallback_element = (
                    next(iter(fallback_branch), None) if fallback_branch is not None else None
                )
                if (
                    native is not None
                    and _local_name(native) == "sp"
                    and fallback_element is not None
                    and _local_name(fallback_element) == "pic"
                ):
                    shape, shape_warns, shape_preserved = _shape(
                        native,
                        package,
                        slide_part,
                        colors,
                        hyperlink_for,
                        inherit_ctx=inherit_ctx,
                    )
                    fallback_shape = _picture_shape(fallback_element, package, slide_part)
                    if (
                        shape is not None
                        and fallback_shape is not None
                        and isinstance(fallback_shape.fill, PictureFill)
                    ):
                        preserved_kinds = {fragment.kind for fragment in shape_preserved}
                        fallback_role = fallback_shape.fill.raster_role
                        recover_owned = preserved_kinds == {"fillOverlay"}
                        recover_rasterized = (
                            fallback_role == "pptx-source-rasterized"
                            and preserved_kinds == {"prstShdw"}
                        )
                        if shape_preserved and (recover_owned or recover_rasterized):
                            source_fallback = fallback_role == "pptx-source-fallback"
                            fallback_representation = (
                                "rasterized" if recover_rasterized else "element_layer"
                            )
                            fallback_box = (
                                _positioned_box(native) if source_fallback else None
                            ) or fallback_shape.box
                            reason = (
                                (
                                    "preset shadow has no exact CSS mapping; retained as a "
                                    "full-slide rasterized fallback"
                                )
                                if recover_rasterized
                                else (
                                    "shape has unsupported source effects; retained as one owned "
                                    "visual layer"
                                )
                            )
                            try:
                                payload = capture_payload(
                                    package,
                                    slide_part,
                                    element,
                                    kind="AlternateContent",
                                    ambient_theme_part=inherit_ctx.theme_part,
                                )
                            except (KeyError, ValueError):
                                fallback_node = _with_pptx_identity(
                                    ShapeNode(
                                        box=fallback_box,
                                        fill=fallback_shape.fill.model_copy(
                                            update={"raster_role": fallback_role}
                                        ),
                                    ),
                                    native,
                                    slide_part,
                                )
                                contents.append(fallback_node)
                                source_retention = SourceRetention.DETACHED
                                owner_node_id = fallback_node.node_id
                                reason += "; dependent OPC graph could not be attached"
                            else:
                                preserved_node = _with_pptx_identity(
                                    PreservedNode(
                                        box=fallback_box,
                                        payload=payload,
                                        fallback=fallback_shape.fill,
                                        fallback_representation=fallback_representation,
                                    ),
                                    native,
                                    slide_part,
                                )
                                contents.append(preserved_node)
                                source_retention = SourceRetention.ATTACHED
                                owner_node_id = preserved_node.node_id
                            warnings.extend(shape_warns)
                            warning, fragment = _preserve(slide_part, element, reason)
                            warnings.append(warning)
                            preserved.append(
                                fragment.model_copy(update={"owner_node_id": owner_node_id})
                            )
                            coverage.append(
                                CoverageItem(
                                    element=_visual_label(slide_part, native),
                                    representation=(
                                        Representation.RASTERIZED
                                        if recover_rasterized
                                        else Representation.ELEMENT_LAYER
                                    ),
                                    editability=(
                                        Editability.NONE
                                        if recover_rasterized
                                        else Editability.LAYERS
                                    ),
                                    source_retention=source_retention,
                                    raster_area_emu2=(fallback_box.width * fallback_box.height),
                                    reason=reason,
                                )
                            )
                            continue
                        portable_fallback = PortableFallback(
                            box=fallback_shape.box,
                            picture=fallback_shape.fill,
                        )
                        contents.append(
                            shape.model_copy(update={"portable_fallback": portable_fallback})
                        )
                        warnings.extend(shape_warns)
                        preserved.extend(shape_preserved)
                        has_preserved_effects = bool(shape_preserved)
                        reason = "editable native visual with an isolated renderer fallback"
                        if has_preserved_effects:
                            reason += "; shape has detached source-only effect fragments"
                        coverage.append(
                            CoverageItem(
                                element=_visual_label(slide_part, native),
                                representation=Representation.HYBRID,
                                editability=Editability.COMPONENTS,
                                source_retention=(
                                    SourceRetention.DETACHED
                                    if has_preserved_effects
                                    else SourceRetention.NOT_REQUIRED
                                ),
                                output_count=2,
                                raster_area_emu2=(
                                    portable_fallback.box.width * portable_fallback.box.height
                                ),
                                reason=reason,
                            )
                        )
                        if not has_preserved_effects:
                            continue
                        preserve_whole_node = False
                reason = "preserved unsupported markup-compatibility visual"
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
                    warnings.extend(shape_warns)
                    preserved_kinds = {fragment.kind for fragment in shape_preserved}
                    if (
                        shape_preserved
                        and fallback_png is not None
                        and preserved_kinds == {"fillOverlay"}
                    ):
                        if _can_own_source_shape_crop(shape, is_only_visual=element is only_visual):
                            reason = (
                                "shape has unsupported source effects; retained as one owned "
                                "visual layer"
                            )
                            fallback_mask = _rotated_rect_polygon(element)
                        else:
                            fallback_representation = "rasterized"
                            reason = (
                                "shape has unsupported source effects; source-render crop cannot "
                                "prove independent ownership and remains noneditable"
                            )
                    elif (
                        shape_preserved
                        and fallback_png is not None
                        and preserved_kinds == {"prstShdw"}
                    ):
                        fallback_representation = "rasterized"
                        fallback_box_override = Box(x=0, y=0, width=width, height=height)
                        reason = (
                            "preset shadow has no exact CSS mapping; retained as a full-slide "
                            "rasterized fallback"
                        )
                    else:
                        contents.append(shape)
                        preserved.extend(shape_preserved)
                        coverage.append(
                            _shape_reverse_coverage(
                                slide_part,
                                element,
                                has_preserved_effects=bool(shape_preserved),
                            )
                        )
                        if not shape_preserved:
                            continue
                        preserve_whole_node = False
                else:
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
                    contents.append(_with_pptx_identity(media, element, slide_part))
                    coverage.append(_native_reverse_coverage(slide_part, element))
                    continue
                shape = _picture_shape(element, package, slide_part)
                if shape is not None:
                    # The crop (a:srcRect) is recovered into the PictureFill and emitted as
                    # background-size/position by the HTML writer, so nothing is preserved.
                    contents.append(shape)
                    coverage.append(_native_reverse_coverage(slide_part, element))
                    continue
                reason = "preserved picture that the reverse adapter could not map"
            elif kind == "cxnSp":
                connector = read_connector(element, lambda properties: _line(properties, colors))
                if connector is not None:
                    contents.append(_with_pptx_identity(connector, element, slide_part))
                    coverage.append(_connector_reverse_coverage(slide_part, element))
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
                    contents.append(group)
                    warnings.extend(group_warns)
                    preserved.extend(group_preserved)
                    coverage.append(
                        _group_reverse_coverage(
                            slide_part,
                            element,
                            group,
                            has_preserved_children=bool(group_preserved),
                        )
                    )
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
                    contents.append(_with_pptx_identity(frame.table, element, slide_part))
                    coverage.append(_native_reverse_coverage(slide_part, element))
                    continue
                reason = frame.reason or "preserved unsupported graphicFrame"
            elif kind == "oleObj":
                reason = "p:oleObj (OLE object) has no HTML mapping; preserved as fragment"
            else:
                reason = f"preserved unsupported reverse slide node: {kind}"
            if preserve_whole_node:
                box = fallback_box_override or _positioned_box(element)
                source_retention = SourceRetention.DETACHED
                has_visual_layer = False
                if box is not None:
                    fallback = _fallback_picture(
                        fallback_png,
                        box,
                        slide_width=width,
                        slide_height=height,
                        mask_polygon=fallback_mask,
                    )
                    try:
                        payload = capture_payload(
                            package,
                            slide_part,
                            element,
                            kind=kind,
                            ambient_theme_part=inherit_ctx.theme_part,
                        )
                    except (KeyError, ValueError):
                        reason += "; dependent OPC graph could not be attached"
                        if fallback is not None:
                            fallback_node = _with_pptx_identity(
                                ShapeNode(
                                    box=box,
                                    fill=fallback.model_copy(
                                        update={"raster_role": "pptx-source-fallback"}
                                    ),
                                ),
                                element,
                                slide_part,
                            )
                            contents.append(fallback_node)
                            preserved_owner_id = fallback_node.node_id
                            reason += "; visual retained as an element layer"
                    else:
                        source_retention = SourceRetention.ATTACHED
                        preserved_node = _with_pptx_identity(
                            PreservedNode(
                                box=box,
                                payload=payload,
                                fallback=fallback,
                                fallback_representation=fallback_representation,
                            ),
                            element,
                            slide_part,
                        )
                        contents.append(preserved_node)
                        preserved_owner_id = preserved_node.node_id
                    has_visual_layer = fallback is not None and preserved_owner_id is not None
                if has_visual_layer and box is not None:
                    coverage.append(
                        CoverageItem(
                            element=_visual_label(slide_part, element),
                            representation=(
                                Representation.RASTERIZED
                                if fallback_representation == "rasterized"
                                else Representation.ELEMENT_LAYER
                            ),
                            editability=(
                                Editability.NONE
                                if fallback_representation == "rasterized"
                                else Editability.LAYERS
                            ),
                            source_retention=source_retention,
                            raster_area_emu2=box.width * box.height,
                            reason=reason,
                        )
                    )
                else:
                    coverage.append(
                        _failed_reverse_coverage(
                            slide_part,
                            element,
                            reason,
                            source_retention,
                        )
                    )
            warning, fragment = _preserve(slide_part, element, reason)
            if preserved_owner_id is not None:
                fragment = fragment.model_copy(update={"owner_node_id": preserved_owner_id})
            warnings.append(warning)
            preserved.append(fragment)
    return (
        SlideIR(
            width=width,
            height=height,
            contents=tuple(contents),
            transition=transition,
            background=background,
        ),
        tuple(warnings),
        tuple(preserved),
        tuple(coverage),
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


def read_pptx_result(
    pptx: bytes, *, fallback_pngs: Sequence[bytes] | None = None
) -> PptxReadResult:
    """Read a PPTX package into ordered canvas slides plus reverse diagnostics.

    ``fallback_pngs`` may supply one authoritative full-slide render per source slide. Positioned
    source objects without a native reverse adapter receive the smallest reliable crop, or an
    explicitly rasterized full-slide fallback when independent ownership cannot be proved, while
    retaining their exact source payload for PPTX re-emission.
    """
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
    if fallback_pngs is not None and len(fallback_pngs) != len(slide_parts):
        raise ValueError(
            f"fallback PNG count {len(fallback_pngs)} does not match slide count {len(slide_parts)}"
        )
    # Deck-order index per slide part, so a slide-jump rel can recover its zero-based target.
    slide_index_by_part = {part: index for index, part in enumerate(slide_parts)}
    resolved_fallbacks: Sequence[bytes | None] = (
        fallback_pngs if fallback_pngs is not None else (None,) * len(slide_parts)
    )
    results = [
        _slide(
            package,
            slide_part,
            width=width,
            height=height,
            slide_index_by_part=slide_index_by_part,
            fallback_png=fallback_png,
        )
        for slide_part, fallback_png in zip(slide_parts, resolved_fallbacks, strict=True)
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
        coverage=CoverageReport(items=tuple(item for result in results for item in result[3])),
    )


def read_pptx(pptx: bytes, *, fallback_pngs: Sequence[bytes] | None = None) -> list[SlideIR]:
    """Read a PPTX package into ordered canvas slides."""
    return list(read_pptx_result(pptx, fallback_pngs=fallback_pngs).slides)
