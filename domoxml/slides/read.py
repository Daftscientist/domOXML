"""Read PresentationML into PowerPoint canvas IR."""

from __future__ import annotations

import contextlib
import copy
import math
import posixpath
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal, cast
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from defusedxml import ElementTree
from PIL import Image, ImageChops

from domoxml.core.drawingml.identity import NAMESPACE as IDENTITY_NAMESPACE
from domoxml.core.drawingml.preset_geometry import outline_leaves_box, preset_geometry
from domoxml.core.fontsread import ReverseFontFace, read_embedded_fonts
from domoxml.core.images import crop_slide_region
from domoxml.core.ir.effect_payload import EffectPayload, decode_effect_payload
from domoxml.core.ir.effect_projection import effect_list_position, project_native_effects
from domoxml.core.ir.gradient import drawingml_gradient_projection
from domoxml.core.ir.group import group_html_roundtrip_error, group_pptx_write_error
from domoxml.core.ir.model import (
    Animation,
    ArcTo,
    Box,
    CanvasNode,
    ClosePath,
    CubicTo,
    CustomGeometry,
    Effect,
    Fill,
    FillOverlay,
    Geometry,
    GeometryKind,
    GradientFill,
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
    Shadow,
    ShapeNode,
    SlideBackground,
    SlideIR,
    SolidFill,
    SourceProvenance,
    Transform,
)
from domoxml.core.opc import OpcPackage, capture_payload
from domoxml.core.opc.preservation import relationship_part_name
from domoxml.core.opc.reader import Relationship
from domoxml.slides.animation import read_animations
from domoxml.slides.appearance_read import (
    DEFAULT_THEME_COLORS,
    ThemeColors,
)
from domoxml.slides.appearance_read import (
    fill as _fill,
)
from domoxml.slides.appearance_read import (
    fill_overlay_gradient as _fill_overlay_gradient,
)
from domoxml.slides.appearance_read import (
    line as _line,
)
from domoxml.slides.appearance_read import (
    line_element as _line_element,
)
from domoxml.slides.appearance_read import (
    pattern_fill as _pattern_fill,
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
from domoxml.slides.chart_read import chart_picture
from domoxml.slides.connector_read import read_connector
from domoxml.slides.diagram_read import diagram_shapes
from domoxml.slides.effect_read import effect_container_kind, effect_source_ref, read_effects
from domoxml.slides.geometry_guides import evaluate_guides, resolve_guide
from domoxml.slides.graphic_frame import read_graphic_frame
from domoxml.slides.inherit import (
    PlaceholderContext,
    ThemeContext,
    build_placeholder_context,
    inherit_sppr_child,
    inherit_xfrm,
    parse_theme_fonts,
)
from domoxml.slides.media_read import read_media, read_model_frame, read_web_viewer
from domoxml.slides.notes import read_notes
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
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
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
    described = non_visual.get("descr") if non_visual is not None else None
    alt_text = described if described and not described.startswith(_RASTER_MARKER_PREFIX) else None
    return output.model_copy(
        update={"node_id": node_id, "provenance": provenance, "alt_text": alt_text}
    )


def _declared_effect_intent(element: Element) -> EffectPayload | None:
    """Read private effect intent attached to a generated native shape."""
    metadata = element.find("./*/p:nvPr/p:extLst/p:ext/dx:node", _NS)
    return decode_effect_payload(metadata.get("effectIntent") if metadata is not None else None)


def _matching_effect_intent(
    element: Element,
    native_effects: tuple[Effect, ...],
    box: Box,
) -> EffectPayload | None:
    """Recover private effect intent only while its generated native projection is unchanged."""
    payload = _declared_effect_intent(element)
    if payload is None:
        return None

    intent_effects = project_native_effects(payload.effects, payload.native_projection)
    if len(intent_effects) != len(native_effects):
        return None

    projected: list[Effect] = []
    for effect in intent_effects:
        if isinstance(effect, Shadow):
            projected_color = effect.color.model_copy(
                update={
                    "a": (
                        1.0 if effect.color.a >= 1.0 else round(effect.color.a * 100_000) / 100_000
                    )
                }
            )
            projected_blur = (
                max(0, effect.blur_emu + effect.spread_emu)
                if effect.inset and effect.spread_emu != 0
                else effect.blur_emu
            )
            projected_spread = effect.spread_emu
            if not effect.inset and effect.spread_emu != 0 and box.width > 0 and box.height > 0:
                scale_x = round((box.width + 2 * effect.spread_emu) / box.width * 100_000)
                scale_y = round((box.height + 2 * effect.spread_emu) / box.height * 100_000)
                spread_x = (scale_x / 100_000 - 1) * box.width / 2
                spread_y = (scale_y / 100_000 - 1) * box.height / 2
                projected_spread = round((spread_x + spread_y) / 2)
            projected.append(
                effect.model_copy(
                    update={
                        "blur_emu": projected_blur,
                        "color": projected_color,
                        "direction_deg": round((effect.direction_deg % 360.0) * 60_000) / 60_000,
                        "spread_emu": 0 if effect.inset else projected_spread,
                    }
                )
            )
        elif isinstance(effect, FillOverlay) and isinstance(effect.fill, GradientFill):
            projected.append(
                effect.model_copy(
                    update={
                        "fill": drawingml_gradient_projection(effect.fill, box=box),
                    }
                )
            )
        else:
            projected.append(effect)
    if payload.container == "list":
        projected.sort(key=effect_list_position)
    return payload if tuple(projected) == native_effects else None


def _related_part_by_type(
    package: OpcPackage, source_part: str, relationship_type: str
) -> str | None:
    try:
        return package.related_part_by_type(source_part, relationship_type)
    except KeyError:
        return None


def _custGeom(element: Element, box: Box) -> CustomGeometry | None:
    """Parse ``a:custGeom`` from a shape's ``spPr`` and return a :class:`CustomGeometry`."""
    path_el = element.find(f"{{{_A}}}pathLst/{{{_A}}}path")
    if path_el is None:
        return None
    try:
        width_emu = int(path_el.get("w", str(box.width)))
        height_emu = int(path_el.get("h", str(box.height)))
    except ValueError:
        return None
    if width_emu <= 0 or height_emu <= 0:
        return None
    formulas = tuple(
        (guide.get("name", ""), guide.get("fmla", ""))
        for guide in element.findall(f"{{{_A}}}avLst/{{{_A}}}gd")
        + element.findall(f"{{{_A}}}gdLst/{{{_A}}}gd")
        if guide.get("name") and guide.get("fmla")
    )
    try:
        guides = evaluate_guides(formulas, width=box.width, height=box.height)
    except ValueError:
        return None

    def point(source: Element) -> Point:
        return Point(
            x=resolve_guide(source.get("x"), guides),
            y=resolve_guide(source.get("y"), guides),
        )

    commands: list[PathCommand] = []
    try:
        for child in path_el:
            local = child.tag.rsplit("}", 1)[-1]
            if local == "moveTo":
                pt = child.find(f"{{{_A}}}pt")
                if pt is not None:
                    commands.append(MoveTo(to=point(pt)))
            elif local == "lnTo":
                pt = child.find(f"{{{_A}}}pt")
                if pt is not None:
                    commands.append(LineTo(to=point(pt)))
            elif local == "cubicBezTo":
                pts = child.findall(f"{{{_A}}}pt")
                if len(pts) >= 3:
                    commands.append(CubicTo(c1=point(pts[0]), c2=point(pts[1]), to=point(pts[2])))
            elif local == "quadBezTo":
                pts = child.findall(f"{{{_A}}}pt")
                if len(pts) >= 2:
                    commands.append(QuadTo(c1=point(pts[0]), to=point(pts[1])))
            elif local == "arcTo":
                commands.append(
                    ArcTo(
                        width_radius=resolve_guide(child.get("wR"), guides),
                        height_radius=resolve_guide(child.get("hR"), guides),
                        start_angle=resolve_guide(child.get("stAng"), guides),
                        sweep_angle=resolve_guide(child.get("swAng"), guides),
                    )
                )
            elif local == "close":
                commands.append(ClosePath())
    except ValueError:
        return None
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
    allow_private_over: bool = False,
    portable_fallback: PortableFallback | None = None,
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
    if geom == "roundRect":
        # A roundRect with no ``adj`` guide uses the preset's default, one sixth of the short side.
        adjust = 16_667
        if formula.startswith("val "):
            try:
                adjust = int(formula.removeprefix("val "))
            except (TypeError, ValueError):
                adjust = 16_667
        corner = round(adjust / 100_000 * min(box.width, box.height))
    declared_effect_intent = _declared_effect_intent(element) if allow_private_over else None
    expected_over = next(
        (
            effect
            for effect in (declared_effect_intent.effects if declared_effect_intent else ())
            if isinstance(effect, FillOverlay) and effect.blend == "over"
        ),
        None,
    )
    shape_effects, effect_warns, effect_preserved = read_effects(
        properties,
        lambda element: _rgba(element, colors),
        box=box,
        gradient_for=lambda element: _fill_overlay_gradient(element, colors),
        pattern_for=lambda element: _pattern_fill(element, colors),
        expected_over=expected_over,
    )
    effect_intent = _matching_effect_intent(element, shape_effects, box)
    applied_effect_intent = (
        effect_intent
        if effect_intent is not None and effect_intent.native_projection == "complete"
        else None
    )
    if applied_effect_intent is not None:
        shape_effects = applied_effect_intent.effects
    custgeom_el = properties.find(f"{{{_A}}}custGeom")
    custom_geom = _custGeom(custgeom_el, box) if custgeom_el is not None else None
    if (
        custom_geom is None
        and geometry is not None
        and geom_name not in _valid_geom_kinds
        and _outline_survives_html(element, properties)
    ):
        custom_geom, _complete = _preset_outline(
            geometry, box, picture_beside_paint=_picture_beside_paint(element, properties)
        )

    return (
        _with_pptx_identity(
            ShapeNode(
                box=box,
                geom=geom,
                custom_geom=custom_geom,
                fill=_shape_picture_role(_fill(properties, package, slide_part, colors), element),
                line=_line(properties, colors),
                effects=shape_effects,
                effect_container=(
                    applied_effect_intent.container
                    if applied_effect_intent is not None
                    else effect_container_kind(properties)
                ),
                effect_source_ref=(
                    applied_effect_intent.source_ref
                    if applied_effect_intent is not None
                    else effect_source_ref(properties)
                ),
                native_effect_projection=(
                    applied_effect_intent.native_projection
                    if applied_effect_intent is not None
                    else "complete"
                ),
                portable_fallback=portable_fallback,
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


def _shape_picture_role(fill: Fill | None, element: Element) -> Fill | None:
    """Restore the raster-role marker the writer leaves on a picture-filled ``p:sp``."""
    if not isinstance(fill, PictureFill) or fill.raster_role is not None:
        return fill
    cnvpr = element.find("p:nvSpPr/p:cNvPr", _NS)
    descr = cnvpr.get("descr", "") if cnvpr is not None else ""
    if not descr.startswith(_RASTER_MARKER_PREFIX):
        return fill
    return fill.model_copy(update={"raster_role": descr.removeprefix(_RASTER_MARKER_PREFIX)})


def _cropped(fill: PictureFill) -> PictureFill:
    """``fill`` with its ``a:srcRect`` applied to the pixels, so a plain ``<img>`` shows it."""
    crop = fill.crop
    if crop is None:
        return fill
    try:
        with Image.open(BytesIO(fill.data)) as image:
            width, height = image.size
            box = (
                round(crop.left * width),
                round(crop.top * height),
                round(width - crop.right * width),
                round(height - crop.bottom * height),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                return fill.model_copy(update={"crop": None})
            buffer = BytesIO()
            image.crop(box).save(buffer, "PNG")
    except OSError:
        return fill.model_copy(update={"crop": None})
    return fill.model_copy(update={"data": buffer.getvalue(), "ext": "png", "crop": None})


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
    modifier = fill.find("a:blip/a:alphaModFix", _NS)
    opacity = 1.0
    if modifier is not None:
        with contextlib.suppress(ValueError):
            opacity = min(1.0, max(0.0, int(modifier.get("amt", "100000")) / 100_000))
    return _with_pptx_identity(
        ShapeNode(
            box=Box(
                x=_int_attr(offset, "x"),
                y=_int_attr(offset, "y"),
                width=_int_attr(extent, "cx"),
                height=_int_attr(extent, "cy"),
            ),
            fill=picture,
            opacity=opacity,
            transform=_xfrm_transform(transform),
        ),
        element,
        slide_part,
    )


def _matches_flat_over_fallback(
    picture: PictureFill,
    base: SolidFill,
    overlay: FillOverlay,
) -> bool:
    """Whether a generated picture still paints the declared flat CSS-normal composite."""
    if (
        not isinstance(overlay.fill, SolidFill)
        or base.color.a != 1.0
        or picture.ext != "png"
        or picture.crop is not None
        or picture.mode != "stretch"
        or picture.svg_data is not None
    ):
        return False
    alpha = overlay.fill.color.a
    expected = tuple(
        round(over * alpha + under * (1.0 - alpha))
        for over, under in zip(
            (
                overlay.fill.color.r,
                overlay.fill.color.g,
                overlay.fill.color.b,
            ),
            (base.color.r, base.color.g, base.color.b),
            strict=True,
        )
    )
    try:
        with Image.open(BytesIO(picture.data)) as image:
            rgba = image.convert("RGBA")
            if rgba.width < 1 or rgba.height < 1:
                return False
            if rgba.getchannel("A").getextrema() != (255, 255):
                return False
            rgb = rgba.convert("RGB")
            reference = Image.new("RGB", rgb.size, expected)
            extrema = cast(
                tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
                ImageChops.difference(rgb, reference).getextrema(),
            )
            return all(upper <= 1 for _lower, upper in extrema)
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


def _private_over_choice_is_current(
    native: Element,
    fallback_shape: ShapeNode,
    effect_intent: EffectPayload | None,
    package: OpcPackage,
    slide_part: str,
    colors: ThemeColors,
) -> bool:
    """Admit generated CSS-normal intent only while all exact-subset projections still agree."""
    if (
        effect_intent is None
        or len(effect_intent.effects) != 1
        or not isinstance(effect_intent.effects[0], FillOverlay)
        or effect_intent.effects[0].blend != "over"
        or not isinstance(fallback_shape.fill, PictureFill)
        or fallback_shape.fill.raster_role != "portable-effect-fallback"
    ):
        return False
    non_visual = native.find("p:nvSpPr/p:cNvPr", _NS)
    properties = native.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    geometry = properties.find("a:prstGeom", _NS) if properties is not None else None
    effect_list = properties.find("a:effectLst", _NS) if properties is not None else None
    native_effects = tuple(effect_list) if effect_list is not None else ()
    if (
        non_visual is None
        or non_visual.get("hidden") != "1"
        or properties is None
        or transform is None
        or offset is None
        or extent is None
        or transform.get("rot") is not None
        or transform.get("flipH") is not None
        or transform.get("flipV") is not None
        or geometry is None
        or geometry.get("prst") != "rect"
        or properties.find("a:custGeom", _NS) is not None
        or properties.find("a:ln", _NS) is not None
        or native.find("p:txBody", _NS) is not None
        or len(native_effects) != 1
        or _local_name(native_effects[0]) != "fillOverlay"
        or native_effects[0].get("blend") != "over"
        or properties.find("a:effectDag", _NS) is not None
    ):
        return False
    native_box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )
    base = _fill(properties, package, slide_part, colors)
    return (
        native_box == fallback_shape.box
        and isinstance(base, SolidFill)
        and _matches_flat_over_fallback(
            fallback_shape.fill,
            base,
            effect_intent.effects[0],
        )
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


def _picture_beside_paint(element: Element, properties: Element) -> bool:
    """Whether a picture fill shares its shape with a stroke or text."""
    outlined = properties.find("a:ln", _NS) is not None and (
        properties.find("a:ln/a:noFill", _NS) is None
    )
    has_text = any((run.text or "").strip() for run in element.iterfind(".//a:t", _NS))
    return properties.find("a:blipFill", _NS) is not None and (outlined or has_text)


def _outline_survives_html(element: Element, properties: Element) -> bool:
    """Whether an outline drawn from a preset keeps all of the shape's paint in HTML.

    Custom geometry reaches HTML as an SVG (solid or gradient fill, and stroke) with any text laid
    over it, or, for a picture fill, a clipped picture with the stroke and text layered over it. A
    hatch pattern beside a stroke or text has no form there yet.
    """
    has_text = any((run.text or "").strip() for run in element.iterfind(".//a:t", _NS))
    outlined = properties.find("a:ln", _NS) is not None and (
        properties.find("a:ln/a:noFill", _NS) is None
    )
    # Only a hatch pattern still has no form beside a stroke or text; a picture is layered.
    pattern = properties.find("a:pattFill", _NS) is not None
    # A layered picture cannot carry a native effect, so those keep the rectangle too.
    effects = properties.find("a:effectLst", _NS)
    has_effects = (effects is not None and len(effects) > 0) or (
        properties.find("a:effectDag", _NS) is not None
    )
    picture_with_effects = properties.find("a:blipFill", _NS) is not None and has_effects
    return not (pattern and (outlined or has_text)) and not (
        picture_with_effects and (outlined or has_text)
    )


def _preset_outline(
    geometry: Element, box: Box, *, picture_beside_paint: bool = False
) -> tuple[CustomGeometry | None, bool]:
    """A preset the IR has no named geometry for, drawn from the standard's definition.

    A picture is painted only inside the shape's box, so a picture-filled outline with a stroke or
    text that leaves it (a callout's tail, a cloud's last bubble) keeps its rectangle.
    """
    adjusts: dict[str, float] = {}
    for guide in geometry.findall("a:avLst/a:gd", _NS):
        formula = guide.get("fmla", "")
        if formula.startswith("val "):
            with contextlib.suppress(ValueError):
                adjusts[guide.get("name", "")] = float(formula.removeprefix("val "))
    outline, complete = preset_geometry(
        geometry.get("prst", "rect"), box.width, box.height, adjusts
    )
    if outline is not None and picture_beside_paint and outline_leaves_box(outline):
        return None, False
    return outline, complete


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
            transform = element.find("p:spPr/a:xfrm/a:ext", _NS)
            properties = element.find("p:spPr", _NS)
            outline, complete = (
                _preset_outline(
                    geometry,
                    Box(
                        x=0,
                        y=0,
                        width=_int_attr(transform, "cx"),
                        height=_int_attr(transform, "cy"),
                    ),
                    picture_beside_paint=_picture_beside_paint(element, properties),
                )
                if transform is not None
                and properties is not None
                and _outline_survives_html(element, properties)
                else (None, False)
            )
            if outline is None:
                reasons.append(f"unsupported preset geometry {name!r} mapped to a rectangle")
                retention = SourceRetention.LOST
            elif not complete:
                reasons.append(
                    f"preset {name!r} outline drawn; its stroke-only or shaded parts dropped"
                )
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
    if not has_preserved_children:
        return _native_reverse_coverage(slide_part, element)
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


_EXACT_CONNECTORS = frozenset({"line", "straightConnector1", "bentConnector3", "curvedConnector3"})


def _connector_reverse_coverage(slide_part: str, element: Element) -> CoverageItem:
    geometry = element.find("p:spPr/a:prstGeom", _NS)
    preset = geometry.get("prst", "line") if geometry is not None else "line"
    adjusted = geometry is not None and any(
        guide.get("name") != "adj1" for guide in geometry.findall("a:avLst/a:gd", _NS)
    )
    if preset in _EXACT_CONNECTORS and not adjusted:
        return _native_reverse_coverage(slide_part, element)
    reason = (
        f"connector {preset!r} drawn as a single-elbow route; its adjust handle is not kept"
        if adjusted
        else f"connector {preset!r} drawn as a single-elbow route"
    )
    return CoverageItem(
        element=_visual_label(slide_part, element),
        representation=Representation.APPROXIMATED,
        editability=Editability.SEMANTIC,
        source_retention=SourceRetention.LOST,
        reason=reason,
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


def _has_source_only_effect(element: Element) -> bool:
    """Whether a shape has an effect container that must retain source markup."""
    properties = element.find("p:spPr", _NS)
    if properties is None:
        return False
    if properties.find("a:effectLst/a:prstShdw", _NS) is not None:
        return True
    return (
        properties.find("a:effectDag", _NS) is not None
        and effect_container_kind(properties) != "sibling"
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


def _slide_background(
    package: OpcPackage, slide_part: str, slide: Element, colors: ThemeColors
) -> SlideBackground | None:
    """The slide's background: its own, else the layout's, else the master's.

    A background is a fill (``bgPr``) or a reference to one of the theme's background fills
    (``bgRef``, whose own colour stands in for the style's ``phClr`` placeholder).
    """
    layout_part = _related_part_by_type(package, slide_part, _SLIDE_LAYOUT_REL)
    master_part = (
        _related_part_by_type(package, layout_part, _SLIDE_MASTER_REL) if layout_part else None
    )
    levels: list[tuple[Element, str]] = [(slide, slide_part)]
    for part in (layout_part, master_part):
        if part is None:
            continue
        with contextlib.suppress(KeyError, ElementTree.ParseError):
            levels.append((ElementTree.fromstring(package.read(part)), part))
    for level, (root, part) in enumerate(levels):
        background = root.find("p:cSld/p:bg", _NS)
        if background is None:
            continue
        properties = background.find("p:bgPr", _NS)
        if properties is not None:
            fill = _fill(properties, package, part, colors)
        else:
            fill = _background_reference_fill(
                background.find("p:bgRef", _NS), package, master_part, colors
            )
        if fill is None:
            return None
        return SlideBackground(fill=fill, inherited=level > 0)
    return None


def _background_reference_fill(
    reference: Element | None, package: OpcPackage, master_part: str | None, colors: ThemeColors
) -> Fill | None:
    """The theme background fill a ``bgRef`` points at, painted in the reference's colour."""
    if reference is None or master_part is None:
        return None
    theme_part = _related_part_by_type(package, master_part, _THEME_REL)
    if theme_part is None:
        return None
    try:
        theme = ElementTree.fromstring(package.read(theme_part))
        index = int(reference.get("idx", "0"))
    except (KeyError, ValueError, ElementTree.ParseError):
        return None
    styles = theme.find("a:themeElements/a:fmtScheme/a:bgFillStyleLst", _NS)
    position = index - 1001
    if styles is None or not 0 <= position < len(styles):
        return None
    style = copy.deepcopy(styles[position])
    colour = next(iter(reference), None)
    if colour is not None:
        for parent in style.iter():
            for child_index, child in enumerate(list(parent)):
                if child.tag == f"{{{_A}}}schemeClr" and child.get("val") == "phClr":
                    # The style's own colour transforms (alpha, tint...) apply to the reference's.
                    replacement = copy.deepcopy(colour)
                    replacement.extend(copy.deepcopy(transform) for transform in child)
                    parent[child_index] = replacement
    holder = Element("holder")
    holder.append(style)
    return _fill(holder, package, theme_part, colors)


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
    default_text_style: Element | None = None
    with contextlib.suppress(KeyError, ValueError, ElementTree.ParseError):
        presentation = ElementTree.fromstring(
            package.read(package.related_part_by_type(None, _OFFICE_DOCUMENT_REL))
        )
        default_text_style = presentation.find("p:defaultTextStyle", _NS)
    theme_ctx = ThemeContext(
        major_latin=major_latin,
        minor_latin=minor_latin,
        colors=colors,
        default_text_style=default_text_style,
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
    with_inherited: bool = True,
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
    renderer_fallback: PictureFill | None = None
    renderer_fallback_owner_node_id: str | None = None

    # --- Slide-level: background (p:cSld/p:bg) ---
    background = _slide_background(package, slide_part, root, colors)
    # An inherited background is the layout's or master's own, not an element of this slide.
    if (
        background is not None
        and not background.inherited
        and (root.find("p:cSld/p:bg/p:bgPr", _NS) is not None)
    ):
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
        timing_notice: tuple[ConversionWarning, PreservedFragment] | None = (warn, frag)
    else:
        timing_notice = None

    if tree is not None:
        tree_elements = tuple(tree)
        initial_visuals = tuple(
            element
            for element in tree_elements
            if _local_name(element) not in {"nvGrpSpPr", "grpSpPr", "extLst"}
        )
        if len(initial_visuals) == 1 and _local_name(initial_visuals[0]) == "AlternateContent":
            alternate = initial_visuals[0]
            alternate_children = tuple(alternate)
            exact_branches = (
                len(alternate_children) == 2
                and alternate_children[0].tag == f"{{{_MC}}}Choice"
                and alternate_children[1].tag == f"{{{_MC}}}Fallback"
            )
            choice = alternate_children[0] if exact_branches else None
            fallback_branch = alternate_children[1] if exact_branches else None
            fallback_children = tuple(fallback_branch) if fallback_branch is not None else ()
            fallback_element = fallback_children[0] if len(fallback_children) == 1 else None
            fallback_shape = (
                _picture_shape(fallback_element, package, slide_part)
                if fallback_element is not None and _local_name(fallback_element) == "pic"
                else None
            )
            if (
                choice is not None
                and fallback_shape is not None
                and isinstance(fallback_shape.fill, PictureFill)
                and fallback_shape.fill.raster_role == "pptx-slide-rasterized"
                and fallback_shape.box == Box(x=0, y=0, width=width, height=height)
            ):
                renderer_fallback = fallback_shape.fill
                flattened: list[Element] = []
                for child in tree_elements:
                    if child is alternate:
                        flattened.extend(choice)
                    else:
                        flattened.append(child)
                tree_elements = tuple(flattened)
        visual_elements = tuple(
            element
            for element in tree_elements
            if _local_name(element) not in {"nvGrpSpPr", "grpSpPr", "extLst"}
        )
        source_only_effect_visuals = tuple(
            element
            for element in visual_elements
            if _local_name(element) == "sp" and _has_source_only_effect(element)
        )
        group_results = {
            id(element): _group_node(
                element,
                package,
                slide_part,
                colors,
                hyperlink_for,
                inherit_ctx=inherit_ctx,
            )
            for element in visual_elements
            if _local_name(element) == "grpSp"
        }
        has_unsupported_group = any(
            group is None
            or bool(group_preserved)
            or group_pptx_write_error(group) is not None
            # Source-only effects (preset shadows) are painted only by the slide raster, so a
            # slide that has them keeps it for any group the structural HTML cannot carry.
            or (bool(source_only_effect_visuals) and group_html_roundtrip_error(group) is not None)
            for group, _group_warns, group_preserved in group_results.values()
        )
        if (
            renderer_fallback is None
            and fallback_png is not None
            and (
                (len(visual_elements) > 1 and len(source_only_effect_visuals) == 1)
                or has_unsupported_group
            )
        ):
            renderer_fallback = _fallback_picture(
                fallback_png,
                Box(x=0, y=0, width=width, height=height),
                slide_width=width,
                slide_height=height,
            )
        only_visual = visual_elements[0] if len(visual_elements) == 1 else None
        for element in tree_elements:
            kind = _local_name(element)
            chart_drawn = False
            preserved_owner_id: str | None = None
            preserve_whole_node = True
            use_slide_renderer_fallback = False
            owns_slide_renderer_fallback = False
            fallback_representation: Literal["element_layer", "rasterized"] = "element_layer"
            fallback_box_override: Box | None = None
            source_poster_fill: PictureFill | None = None
            fallback_mask: tuple[tuple[float, float], ...] | None = None
            reason = f"preserved unsupported reverse slide node: {kind}"
            if kind in {"nvGrpSpPr", "grpSpPr"}:
                continue
            if kind == "AlternateContent":
                model_frame = read_model_frame(element, package, slide_part)
                if model_frame is not None:
                    model_node, model_owner = model_frame
                    contents.append(_with_pptx_identity(model_node, model_owner, slide_part))
                    coverage.append(_native_reverse_coverage(slide_part, model_owner))
                    continue
                choice = next((child for child in element if _local_name(child) == "Choice"), None)
                fallback_branch = next(
                    (child for child in element if _local_name(child) == "Fallback"), None
                )
                choice_children = tuple(choice) if choice is not None else ()
                native = choice_children[0] if choice_children else None
                fallback_children = tuple(fallback_branch) if fallback_branch is not None else ()
                fallback_element = fallback_children[0] if fallback_children else None
                if (
                    native is not None
                    and _local_name(native) == "graphicFrame"
                    and fallback_element is not None
                    and _local_name(fallback_element) == "pic"
                ):
                    # A frame this reader does not model (a 3-D model) that PowerPoint saved with
                    # its own poster picture: the poster is the visual, the frame stays attached.
                    try:
                        poster = _picture_shape(fallback_element, package, slide_part)
                    except (KeyError, ValueError):
                        poster = None  # a dangling picture leaves the frame without a visual
                    if poster is not None and isinstance(poster.fill, PictureFill):
                        fallback_box_override = poster.box
                        source_poster_fill = _cropped(poster.fill)
                        reason = (
                            "frame shown as the poster picture saved with it; the source frame "
                            "stays attached for exact PPTX re-emission"
                        )
                if (
                    native is not None
                    and _local_name(native) == "sp"
                    and fallback_element is not None
                    and _local_name(fallback_element) == "pic"
                ):
                    fallback_shape = _picture_shape(fallback_element, package, slide_part)
                    choice_fallback_shape = (
                        _picture_shape(choice_children[1], package, slide_part)
                        if len(choice_children) == 2 and _local_name(choice_children[1]) == "pic"
                        else None
                    )
                    private_effect_intent = _declared_effect_intent(native)
                    private_over_declared = private_effect_intent is not None and any(
                        isinstance(effect, FillOverlay) and effect.blend == "over"
                        for effect in private_effect_intent.effects
                    )
                    private_over_choice = (
                        len(fallback_children) == 1
                        and choice_fallback_shape is not None
                        and fallback_shape is not None
                        and isinstance(fallback_shape.fill, PictureFill)
                        and choice_fallback_shape.box == fallback_shape.box
                        and choice_fallback_shape.fill == fallback_shape.fill
                        and _private_over_choice_is_current(
                            native,
                            fallback_shape,
                            private_effect_intent,
                            package,
                            slide_part,
                            colors,
                        )
                    )
                    stale_private_over = private_over_declared and not private_over_choice
                    private_over_fallback: PortableFallback | None = None
                    if (
                        private_over_choice
                        and fallback_shape is not None
                        and isinstance(fallback_shape.fill, PictureFill)
                    ):
                        private_over_fallback = PortableFallback(
                            box=fallback_shape.box,
                            picture=fallback_shape.fill,
                        )
                    shape, shape_warns, shape_preserved = _shape(
                        native,
                        package,
                        slide_part,
                        colors,
                        hyperlink_for,
                        inherit_ctx=inherit_ctx,
                        allow_private_over=private_over_choice,
                        portable_fallback=private_over_fallback,
                    )
                    if (
                        shape is not None
                        and fallback_shape is not None
                        and isinstance(fallback_shape.fill, PictureFill)
                    ):
                        preserved_kinds = {fragment.kind for fragment in shape_preserved}
                        fallback_role = fallback_shape.fill.raster_role
                        if fallback_role == "pptx-slide-rasterized":
                            reason = (
                                "tagged slide fallback was not an exact whole-slide branch; "
                                "retained as one rasterized source visual"
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
                                        box=fallback_shape.box,
                                        fill=fallback_shape.fill,
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
                                        box=fallback_shape.box,
                                        payload=payload,
                                        fallback=fallback_shape.fill,
                                        fallback_representation="rasterized",
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
                                    representation=Representation.RASTERIZED,
                                    editability=Editability.NONE,
                                    source_retention=source_retention,
                                    raster_area_emu2=(
                                        fallback_shape.box.width * fallback_shape.box.height
                                    ),
                                    reason=reason,
                                )
                            )
                            continue
                        recover_owned = stale_private_over or "fillOverlay" in preserved_kinds
                        rasterized_candidate = (
                            fallback_role == "pptx-source-rasterized"
                            and preserved_kinds in ({"prstShdw"}, {"effectDag"})
                        )
                        recover_rasterized = rasterized_candidate and element is only_visual
                        if (shape_preserved or stale_private_over) and (
                            recover_owned or recover_rasterized
                        ):
                            source_fallback = fallback_role == "pptx-source-fallback"
                            fallback_representation = (
                                "rasterized" if recover_rasterized else "element_layer"
                            )
                            fallback_box = (
                                _positioned_box(native) if source_fallback else None
                            ) or fallback_shape.box
                            reason = (
                                (
                                    "source effect has no exact CSS mapping; retained as a "
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
                        if rasterized_candidate:
                            contents.append(shape)
                            warnings.extend(shape_warns)
                            reason = (
                                "full-slide source-effect fallback requires a sole visual; "
                                "native shape retained without the detached source-only effect"
                            )
                            warning, fragment = _preserve(slide_part, element, reason)
                            warnings.append(warning)
                            preserved.append(fragment)
                            coverage.append(
                                _shape_reverse_coverage(
                                    slide_part,
                                    native,
                                    has_preserved_effects=True,
                                )
                            )
                            continue
                        declared_effect_intent = _declared_effect_intent(native)
                        matching_subset_intent = (
                            _matching_effect_intent(native, shape.effects, shape.box)
                            if (
                                fallback_role == "portable-effect-fallback"
                                and declared_effect_intent is not None
                                and declared_effect_intent.native_projection == "schema_subset"
                            )
                            else None
                        )
                        if (
                            fallback_role == "portable-effect-fallback"
                            and declared_effect_intent is not None
                            and declared_effect_intent.native_projection == "schema_subset"
                            and matching_subset_intent is None
                        ):
                            contents.append(shape)
                            warnings.extend(shape_warns)
                            preserved.extend(shape_preserved)
                            coverage.append(
                                _shape_reverse_coverage(
                                    slide_part,
                                    native,
                                    has_preserved_effects=bool(shape_preserved),
                                )
                            )
                            continue
                        portable_fallback = PortableFallback(
                            box=fallback_shape.box,
                            picture=fallback_shape.fill,
                        )
                        shape_updates: dict[str, object] = {"portable_fallback": portable_fallback}
                        if matching_subset_intent is not None:
                            shape_updates.update(
                                {
                                    "effects": matching_subset_intent.effects,
                                    "effect_container": matching_subset_intent.container,
                                    "effect_source_ref": matching_subset_intent.source_ref,
                                    "native_effect_projection": (
                                        matching_subset_intent.native_projection
                                    ),
                                }
                            )
                        contents.append(shape.model_copy(update=shape_updates))
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
                if source_poster_fill is None:
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
                        and preserved_kinds in ({"prstShdw"}, {"effectDag"})
                        and renderer_fallback is not None
                    ):
                        reason = (
                            "source-only effect retained as exact native markup under one "
                            "slide-level renderer fallback"
                        )
                        box = _positioned_box(element) or shape.box
                        try:
                            payload = capture_payload(
                                package,
                                slide_part,
                                element,
                                kind=kind,
                                ambient_theme_part=inherit_ctx.theme_part,
                            )
                        except (KeyError, ValueError):
                            contents.append(shape)
                            owner_node_id = shape.node_id
                            reason += "; dependent OPC graph could not be attached"
                            if renderer_fallback_owner_node_id is None:
                                renderer_fallback_owner_node_id = shape.node_id
                            else:
                                coverage.append(
                                    _failed_reverse_coverage(
                                        slide_part,
                                        element,
                                        reason
                                        + "; slide fallback is owned by another source visual",
                                        SourceRetention.DETACHED,
                                    )
                                )
                        else:
                            preserved_node = _with_pptx_identity(
                                PreservedNode(box=box, payload=payload),
                                element,
                                slide_part,
                            )
                            contents.append(preserved_node)
                            owner_node_id = preserved_node.node_id
                            if renderer_fallback_owner_node_id is None:
                                renderer_fallback_owner_node_id = preserved_node.node_id
                            else:
                                coverage.append(
                                    _failed_reverse_coverage(
                                        slide_part,
                                        element,
                                        reason
                                        + "; slide fallback is owned by another source visual",
                                        SourceRetention.ATTACHED,
                                    )
                                )
                        warning, fragment = _preserve(slide_part, element, reason)
                        warnings.append(warning)
                        preserved.append(
                            fragment.model_copy(update={"owner_node_id": owner_node_id})
                        )
                        continue
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
                        and preserved_kinds in ({"prstShdw"}, {"effectDag"})
                        and element is only_visual
                    ):
                        fallback_representation = "rasterized"
                        fallback_box_override = Box(x=0, y=0, width=width, height=height)
                        reason = (
                            "source effect has no exact CSS mapping; retained as a full-slide "
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
                group, group_warns, group_preserved = group_results[id(element)]
                group_roundtrip_error = (
                    group_html_roundtrip_error(group) if group is not None else None
                )
                if group is not None and not group_preserved and group_roundtrip_error is None:
                    contents.append(group)
                    warnings.extend(group_warns)
                    coverage.append(
                        _group_reverse_coverage(
                            slide_part,
                            element,
                            group,
                            has_preserved_children=bool(group_preserved),
                        )
                    )
                    continue
                if (
                    group is not None
                    and not group_preserved
                    and group_pptx_write_error(group) is None
                    and not source_only_effect_visuals
                ):
                    # Transformed, nested or connector-bearing groups have no structural HTML
                    # projection, but every child is native: the serializer lays them out in a
                    # wrapper that carries the group transform, so nothing needs a raster.
                    contents.append(group)
                    warnings.extend(group_warns)
                    shapes = _group_output_count(group)
                    coverage.append(
                        _native_reverse_coverage(slide_part, element)
                        if shapes <= 1
                        else CoverageItem(
                            element=_visual_label(slide_part, element),
                            representation=Representation.DECOMPOSED,
                            editability=Editability.COMPONENTS,
                            source_retention=SourceRetention.LOST,
                            output_count=shapes,
                            reason=f"group flattened into positioned HTML children: "
                            f"{group_roundtrip_error}",
                        )
                    )
                    continue
                fallback_representation = "rasterized"
                use_slide_renderer_fallback = renderer_fallback is not None
                fallback_detail = (
                    "source retained under one slide-owned composite raster"
                    if use_slide_renderer_fallback
                    else "source retained; no renderer pixels were supplied"
                )
                reason = (
                    f"group contains unsupported children; {fallback_detail}"
                    if group_preserved
                    else f"{group_roundtrip_error}; {fallback_detail}"
                    if group_roundtrip_error is not None
                    else "preserved group that the reverse adapter could not map"
                )
            elif kind == "graphicFrame":
                web = read_web_viewer(element, package, slide_part)
                if web is not None:
                    contents.append(_with_pptx_identity(web, element, slide_part))
                    coverage.append(_native_reverse_coverage(slide_part, element))
                    continue
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
                diagram = diagram_shapes(element, package, slide_part)
                if diagram is not None:
                    drawing, drawing_part = diagram
                    pieces: list[ShapeNode] = []
                    piece_warnings: list[ConversionWarning] = []
                    complete = True
                    for part in drawing:
                        # The shapes belong to the drawing part: relationships resolve there.
                        piece, piece_warns, kept = _shape(
                            part,
                            package,
                            drawing_part,
                            colors,
                            hyperlink_for,
                            inherit_ctx=None,
                        )
                        piece_warnings.extend(piece_warns)
                        if piece is None or kept:
                            complete = False
                            break
                        pieces.append(_with_pptx_identity(piece, part, drawing_part))
                    if complete and pieces:
                        contents.extend(pieces)
                        warnings.extend(piece_warnings)
                        coverage.append(
                            CoverageItem(
                                element=_visual_label(slide_part, element),
                                representation=(
                                    Representation.DECOMPOSED
                                    if len(pieces) > 1
                                    else Representation.NATIVE
                                ),
                                editability=(
                                    Editability.COMPONENTS
                                    if len(pieces) > 1
                                    else Editability.SEMANTIC
                                ),
                                source_retention=SourceRetention.LOST,
                                output_count=len(pieces),
                                reason=(
                                    "SmartArt converted to the shapes PowerPoint drew for it "
                                    "(as Convert to Shapes does); its data model and layout "
                                    "rules are not kept"
                                ),
                            )
                        )
                        continue
                reason = frame.reason or "preserved unsupported graphicFrame"
                # An embedded object (OLE) is saved with the picture PowerPoint shows for it.
                preview = element.find(".//p:oleObj//p:blipFill", _NS)
                if preview is not None:
                    try:
                        shown = _picture(preview, package, slide_part)
                    except (KeyError, ValueError):
                        shown = None
                    if shown is not None:
                        source_poster_fill = _cropped(shown)
                        reason = (
                            "embedded object shown as its preview picture; the object stays "
                            "attached for exact PPTX re-emission"
                        )
            elif kind == "oleObj":
                reason = "p:oleObj (OLE object) has no HTML mapping; preserved as fragment"
            elif source_poster_fill is None:
                reason = f"preserved unsupported reverse slide node: {kind}"
            if preserve_whole_node:
                box = fallback_box_override or _positioned_box(element)
                source_retention = SourceRetention.DETACHED
                has_visual_layer = False
                if box is not None:
                    fallback = (
                        None
                        if use_slide_renderer_fallback
                        else source_poster_fill
                        or _fallback_picture(
                            fallback_png,
                            box,
                            slide_width=width,
                            slide_height=height,
                            mask_polygon=fallback_mask,
                        )
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
                        if (
                            fallback is None
                            and kind == "graphicFrame"
                            and not use_slide_renderer_fallback
                        ):
                            drawn = chart_picture(payload, box, colors)
                            if drawn is not None:
                                fallback = drawn
                                chart_drawn = True
                                reason = (
                                    "chart redrawn as vector SVG from its data; the native chart "
                                    "part stays attached for exact PPTX re-emission"
                                )
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
                        if use_slide_renderer_fallback:
                            if renderer_fallback_owner_node_id is None:
                                renderer_fallback_owner_node_id = preserved_node.node_id
                                owns_slide_renderer_fallback = True
                            else:
                                reason += "; slide fallback is owned by another source visual"
                    has_visual_layer = fallback is not None and preserved_owner_id is not None
                if use_slide_renderer_fallback and owns_slide_renderer_fallback:
                    pass
                elif chart_drawn and has_visual_layer and box is not None:
                    coverage.append(
                        CoverageItem(
                            element=_visual_label(slide_part, element),
                            representation=Representation.APPROXIMATED,
                            editability=Editability.COMPONENTS,
                            source_retention=source_retention,
                            reason=reason,
                        )
                    )
                elif has_visual_layer and box is not None:
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
    if renderer_fallback is not None:
        coverage.append(
            CoverageItem(
                element=f"{slide_part}:renderer-fallback",
                representation=Representation.RASTERIZED,
                editability=Editability.NONE,
                source_retention=(
                    SourceRetention.ATTACHED
                    if renderer_fallback_owner_node_id is not None
                    else SourceRetention.DETACHED
                ),
                raster_area_emu2=width * height,
                reason="one slide-level renderer fallback above retained native contents",
            )
        )
    animations: tuple[Animation, ...] = ()
    if timing_el is not None and timing_notice is not None:
        present = {n.node_id for n in contents if n.node_id}
        shape_nodes: dict[str, str] = {}
        for element in tree if tree is not None else ():
            non_visual = element.find("./*/p:cNvPr", _NS)
            metadata = element.find("./*/p:nvPr/p:extLst/p:ext/dx:node", _NS)
            if non_visual is None or non_visual.get("id") is None:
                continue
            node_id = (metadata.get("id") if metadata is not None else None) or (
                f"pptx-{non_visual.get('id')}"
            )
            if node_id in present:
                shape_nodes[non_visual.get("id", "")] = node_id
        mapped = read_animations(timing_el, shape_nodes)
        if mapped is not None:
            # Every effect is one the IR carries, so the timing is no longer opaque source.
            animations = mapped
            warnings.remove(timing_notice[0])
            preserved.remove(timing_notice[1])
    return (
        SlideIR(
            width=width,
            height=height,
            animations=animations,
            contents=(
                *(
                    _inherited_shapes(
                        package,
                        slide_part,
                        root,
                        width=width,
                        height=height,
                        slide_index_by_part=slide_index_by_part,
                    )
                    if with_inherited
                    else ()
                ),
                *contents,
            ),
            transition=transition,
            background=background,
            renderer_fallback=renderer_fallback,
            renderer_fallback_owner_node_id=renderer_fallback_owner_node_id,
            notes=read_notes(package, slide_part),
        ),
        tuple(warnings),
        tuple(preserved),
        tuple(coverage),
    )


def _is_false(value: str | None) -> bool:
    """Whether an OOXML boolean attribute is spelled false (``0`` or ``false``)."""
    return value is not None and value.strip().lower() in ("0", "false")


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _is_placeholder(element: Element) -> bool:
    return element.find(".//p:nvPr/p:ph", _NS) is not None


def _renamed(node: Node, identity: str) -> Node:
    """``node`` under a new id of its own, with no source identity to collide with the slide's."""
    update: dict[str, object] = {"node_id": identity, "provenance": None}
    if isinstance(node, GroupNode):
        update["children"] = tuple(
            _renamed(child, f"{identity}.{index}")  # type: ignore[misc]
            for index, child in enumerate(node.children, start=1)
        )
    return node.model_copy(update=update)


def _inherited_shapes(
    package: OpcPackage,
    slide_part: str,
    slide: Element,
    *,
    width: int,
    height: int,
    slide_index_by_part: dict[str, int],
) -> list[Node]:
    """The shapes a slide shows from its layout and master (logos, bands, footers' art).

    The master's non-placeholder shapes sit under the layout's, which sit under the slide's own;
    ``showMasterSp="0"`` on a layout hides the master's, on the slide hides both. Each source part
    is read as if it were a slide of its own (placeholders removed), so every shape kind the slide
    reader maps is mapped here too, and the results carry no identity of their own.
    """
    layout_part = _related_part_by_type(package, slide_part, _SLIDE_LAYOUT_REL)
    if layout_part is None or _is_false(slide.get("showMasterSp")):
        return []
    master_part = _related_part_by_type(package, layout_part, _SLIDE_MASTER_REL)
    try:
        layout_root = ElementTree.fromstring(package.read(layout_part))
    except (KeyError, ElementTree.ParseError):
        return []
    sources = [layout_part]
    if master_part is not None and not _is_false(layout_root.get("showMasterSp")):
        sources.insert(0, master_part)
    shapes: list[Node] = []
    for number, part in enumerate(sources):
        try:
            root = ElementTree.fromstring(package.read(part))
        except (KeyError, ElementTree.ParseError):
            continue
        tree = root.find("p:cSld/p:spTree", _NS)
        if tree is None:
            continue
        for child in list(tree):
            if _is_placeholder(child):
                tree.remove(child)
        if not any(
            _local_name(child) in {"sp", "pic", "grpSp", "cxnSp", "graphicFrame"} for child in tree
        ):
            continue
        name = f"ppt/slides/__inherited_{slide_part.rsplit('/', 1)[-1]}_{number}.xml"
        layout_target = posixpath.relpath(layout_part, "ppt/slides")

        def target(relationship: Relationship, source: str = part) -> str:
            # Internal targets are relative to the source part; the copy sits in ppt/slides.
            if relationship.target_mode != "Internal":
                return relationship.target
            resolved = package.resolve(source, relationship)
            return posixpath.relpath(resolved, "ppt/slides")

        rels = "".join(
            f'<Relationship Id="{_attr(r.id)}" Type="{_attr(r.type)}" Target="{_attr(target(r))}"'
            + ("" if r.target_mode == "Internal" else ' TargetMode="External"')
            + "/>"
            for r in package.relationships(part)
            if r.type != _SLIDE_LAYOUT_REL
        )
        rels += (
            f'<Relationship Id="rIdInheritedLayout" Type="{_SLIDE_LAYOUT_REL}" '
            f'Target="{_attr(layout_target)}"/>'
        )
        parts = {item: package.read(item) for item in package.parts}
        parts[name] = ElementTree.tostring(root)
        parts[relationship_part_name(name)] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>"
        ).encode()
        read, _warnings, _preserved, _coverage = _slide(
            OpcPackage(parts),
            name,
            width=width,
            height=height,
            slide_index_by_part=slide_index_by_part,
            with_inherited=False,
        )
        kept = [node for node in read.contents if not isinstance(node, PreservedNode)]
        shapes.extend(
            _renamed(node, f"inherited-{number}-{index}") for index, node in enumerate(kept, 1)
        )
    return shapes


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
