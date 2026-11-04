"""Serialize PowerPoint canvas IR to deterministic browser-renderable HTML/CSS."""

from __future__ import annotations

import base64
import hashlib
import math
import re
from collections.abc import Mapping
from contextvars import ContextVar
from html import escape
from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image

from domoxml.core.drawingml.preset_geometry import outline_bounds, outline_leaves_box
from domoxml.core.drawingml.presets import preset_defaults, preset_vertices
from domoxml.core.fillcrop import srcrect_to_background
from domoxml.core.fontsread import ReverseFontFace, font_asset_name, font_face_css
from domoxml.core.ir.effect_calibration import (
    BOX_SHADOW_BLUR_TO_DML,
    CUSTOM_GLOW_ALPHA_TO_DML,
    CUSTOM_GLOW_RADIUS_TO_DML,
    CUSTOM_SHADOW_ALPHA_TO_DML,
    CUSTOM_SHADOW_BLUR_TO_DML,
)
from domoxml.core.ir.effect_payload import encode_effects
from domoxml.core.ir.geometry_payload import encode_custom_geometry
from domoxml.core.ir.group import group_html_roundtrip_error
from domoxml.core.ir.group_payload import encode_group_payload
from domoxml.core.ir.model import (
    SINGLE_LINE_EM,
    Animation,
    ArcTo,
    AutoNumberBullet,
    Blur,
    Box,
    CanvasNode,
    CharBullet,
    ClosePath,
    ColorSpec,
    Connector,
    CubicTo,
    CustomGeometry,
    Fill,
    FillOverlay,
    Glow,
    GradientFill,
    GroupNode,
    Line,
    LineTo,
    MediaNode,
    MoveTo,
    Node,
    PathCommand,
    PatternFill,
    PictureFill,
    Point,
    QuadTo,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideBackground,
    SlideIR,
    SlideTransition,
    SoftEdge,
    SolidFill,
    TableNode,
    TextBody,
    TextParagraph,
    TextRun,
    ThemeColorRef,
    Transform,
)
from domoxml.core.ir.parse import autonum_to_css_list_style, bu_char_to_css_list_style
from domoxml.core.ir.pattern import pattern_to_css
from domoxml.core.ir.table_payload import encode_table_geometry
from domoxml.core.ir.text_payload import encode_text_body
from domoxml.core.media import online_video_url
from domoxml.core.opc import encode_payload
from domoxml.core.svg_path import commands_to_svg_d
from domoxml.core.svg_stroke import svg_dash_lengths
from domoxml.core.units import DRAWINGML_BLUR_RADIUS_PER_CSS_SIGMA, emu_to_px
from domoxml.types import (
    ConversionWarning,
    CoverageReport,
    HtmlAsset,
    HtmlPresentation,
    HtmlSlide,
    PreservedFragment,
)

# Layout rules every emitted element needs. They are inlined on each element, never shipped in a
# stylesheet, so a slide renders correctly wherever its markup lands.
_SLIDE_BASE_STYLE = "position:relative;overflow:hidden;box-sizing:border-box"
_TEXT_BASE_STYLE = "white-space:pre-wrap"
# CSS has no distinct rendering for the heavier OOXML dash presets, so they fold onto the
# nearest CSS border-style (dashed/dotted). The keys cover the whole DashStyle literal.
_CSS_DASH = {
    "solid": "solid",
    "dash": "dashed",
    "dot": "dotted",
    "dashDot": "dashed",
    "lgDash": "dashed",
    "sysDash": "dashed",
}
_SAFE_HYPERLINK_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


def _number(value: float) -> str:
    """Stable compact decimal representation for emitted CSS."""
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _px(value: int) -> str:
    # Blink lays CSS geometry out on a 1/64 px grid. Emit the nearest layout unit explicitly;
    # otherwise decimal truncation can put a value just below its original grid boundary and
    # make every normalized-HTML cycle drift by another 1/64 px.
    layout_px = round(emu_to_px(value) * 64) / 64
    rendered = f"{layout_px:.6f}".rstrip("0").rstrip(".") or "0"
    return f"{rendered}px"


# The slide being serialized: its effects by the node they play on, so the element that carries
# the node's identity also carries its animations (several are space-separated, in play order).
_ANIMATIONS: ContextVar[Mapping[str, tuple[tuple[int, Animation], ...]] | None] = ContextVar(
    "_ANIMATIONS", default=None
)


def _animation_attrs(node: CanvasNode) -> list[tuple[str, str]]:
    plan = _ANIMATIONS.get()
    animations = plan.get(node.node_id) if plan is not None and node.node_id is not None else None
    if not animations:
        return []
    return [
        ("data-animate", " ".join(a.effect for _, a in animations)),
        ("data-animate-step", " ".join(str(a.step) for _, a in animations)),
        ("data-animate-delay", " ".join(str(a.delay_ms) for _, a in animations)),
        ("data-animate-duration", " ".join(str(a.duration_ms) for _, a in animations)),
        ("data-animate-amount", " ".join(f"{a.amount:g}" for _, a in animations)),
        # Where each effect sits in the slide's own sequence, which the elements' order loses.
        ("data-animate-order", " ".join(str(position) for position, _ in animations)),
    ]


def _identity_attrs(node: CanvasNode) -> str:
    """HTML data attributes that carry stable IR identity without affecting rendering."""
    attrs: list[tuple[str, str]] = []
    if node.node_id is not None:
        attrs.append(("data-domoxml-node-id", node.node_id))
        attrs.extend(_animation_attrs(node))
    provenance = node.provenance
    if provenance is not None:
        attrs.extend(
            (
                ("data-domoxml-source-format", provenance.source_format),
                ("data-domoxml-source-id", provenance.source_id),
            )
        )
        if provenance.source_part is not None:
            attrs.append(("data-domoxml-source-part", provenance.source_part))
        if provenance.owner_node_id is not None:
            attrs.append(("data-domoxml-owner-node-id", provenance.owner_node_id))
        if provenance.role is not None:
            attrs.append(("data-domoxml-layer-role", provenance.role))
    if node.alt_text:
        attrs.append(("aria-label", node.alt_text))
    return "".join(f' {name}="{escape(value, quote=True)}"' for name, value in attrs)


def _effect_attrs(node: ShapeNode) -> str:
    """Typed effect metadata carried beside renderer-facing CSS."""
    if not node.effects:
        return ""
    payload = escape(
        encode_effects(
            node.effects,
            container=node.effect_container,
            source_ref=node.effect_source_ref,
            native_projection=node.native_effect_projection,
        ),
        quote=True,
    )
    return f' data-domoxml-effects="{payload}"'


def _custom_geometry_attrs(geometry: CustomGeometry) -> str:
    """Typed geometry metadata carried beside renderer-facing SVG path data."""
    payload = escape(encode_custom_geometry(geometry), quote=True)
    return f' data-domoxml-custom-geometry="{payload}"'


def _text_payload_attrs(node: ShapeNode) -> str:
    """Typed text semantics carried beside renderer-facing HTML spans."""
    if node.text is None:
        return ""
    payload = escape(encode_text_body(node.text), quote=True)
    return f' data-domoxml-text-payload="{payload}"'


def _rgba(color: Rgba, *, opacity: float = 1.0) -> str:
    alpha = color.a * opacity
    return f"rgba({color.r},{color.g},{color.b},{_number(alpha)})"


def _asset(fill: PictureFill) -> HtmlAsset:
    # Vector wins: when an SVG source is present, emit it as the .svg asset so the browser
    # renders the resolution-independent original rather than the PNG fallback.
    if fill.svg_data is not None:
        digest = hashlib.sha256(fill.svg_data).hexdigest()[:16]
        return HtmlAsset(path=f"assets/{digest}.svg", data=fill.svg_data)
    digest = hashlib.sha256(fill.data).hexdigest()[:16]
    return HtmlAsset(path=f"assets/{digest}.{fill.ext}", data=fill.data)


# Default theme-scheme RGB used to resolve an unresolved ThemeColorRef to a concrete colour for
# CSS output (mirrors the reverse reader's _SCHEME_FALLBACK). Pattern fg/bg may carry a theme ref.
_SCHEME_FALLBACK_HEX = {
    "dk1": "000000",
    "lt1": "FFFFFF",
    "dk2": "44546A",
    "lt2": "E7E6E6",
    "accent1": "4472C4",
    "accent2": "ED7D31",
    "accent3": "A5A5A5",
    "accent4": "FFC000",
    "accent5": "5B9BD5",
    "accent6": "70AD47",
    "hlink": "0563C1",
    "folHlink": "954F72",
    "bg1": "FFFFFF",
    "tx1": "000000",
    "bg2": "E7E6E6",
    "tx2": "44546A",
    "phClr": "000000",
}


def _color_spec_hex(color: ColorSpec) -> str:
    """Resolve a :class:`ColorSpec` to a 6-digit hex string (no ``#``) for CSS output. A theme
    reference falls back to the default scheme RGB (transforms are not folded in)."""
    if isinstance(color, ThemeColorRef):
        return _SCHEME_FALLBACK_HEX.get(color.slot, "000000")
    return color.hex


def _gradient(fill: GradientFill, *, opacity: float) -> str:
    stops = ",".join(
        f"{_rgba(stop.color, opacity=opacity)} {_number(stop.pos * 100)}%" for stop in fill.stops
    )
    if fill.radial:
        return f"radial-gradient(circle,{stops})"
    return f"linear-gradient({_number(fill.angle_deg)}deg,{stops})"


def _clip_path_css(geom: str) -> str | None:
    """Return a ``clip-path: polygon(...)`` CSS declaration for a polygon-expressible preset,
    using default adj values.  Returns ``None`` for rect/roundRect/ellipse and unknown kinds."""
    verts = preset_vertices(geom, preset_defaults(geom))
    if verts is None:
        return None
    points = ",".join(f"{_number(x * 100)}% {_number(y * 100)}%" for x, y in verts)
    return f"clip-path:polygon({points})"


def _scaled_px(geometry: CustomGeometry, box: Box) -> tuple[float, float]:
    """px per path unit along x and y: a path's own coordinate space need not be the box's."""
    return (
        emu_to_px(box.width) / geometry.width_emu if geometry.width_emu else 0.0,
        emu_to_px(box.height) / geometry.height_emu if geometry.height_emu else 0.0,
    )


def _polygon_points(geometry: CustomGeometry, box: Box) -> str | None:
    """``geometry`` as CSS ``polygon()`` points in px, or ``None`` if it has curves or holes."""
    scale_x, scale_y = _scaled_px(geometry, box)
    points: list[str] = []
    last = len(geometry.path) - 1
    for index, command in enumerate(geometry.path):
        if (index == 0 and isinstance(command, MoveTo)) or isinstance(command, LineTo):
            points.append(
                f"{_number(command.to.x * scale_x)}px {_number(command.to.y * scale_y)}px"
            )
        elif not (isinstance(command, ClosePath) and index == last):
            return None
    return ", ".join(points) if len(points) >= 3 else None


def _path_px(geometry: CustomGeometry, box: Box) -> str | None:
    """``geometry`` as a CSS ``path()`` string in px of the element's own box, or ``None``."""
    scale_x, scale_y = _scaled_px(geometry, box)
    parts: list[str] = []

    def px(point: Point) -> str:
        return f"{_number(point.x * scale_x)} {_number(point.y * scale_y)}"

    current = (0.0, 0.0)  # in px, to find where an arc's ellipse sits
    start_of_subpath = current
    for command in geometry.path:
        if isinstance(command, MoveTo):
            parts.append(f"M {px(command.to)}")
            current = (command.to.x * scale_x, command.to.y * scale_y)
            start_of_subpath = current
        elif isinstance(command, LineTo):
            parts.append(f"L {px(command.to)}")
            current = (command.to.x * scale_x, command.to.y * scale_y)
        elif isinstance(command, CubicTo):
            parts.append(f"C {px(command.c1)} {px(command.c2)} {px(command.to)}")
            current = (command.to.x * scale_x, command.to.y * scale_y)
        elif isinstance(command, QuadTo):
            parts.append(f"Q {px(command.c1)} {px(command.to)}")
            current = (command.to.x * scale_x, command.to.y * scale_y)
        elif isinstance(command, ArcTo):
            rx, ry = command.width_radius * scale_x, command.height_radius * scale_y
            start = math.radians(command.start_angle / 60_000)
            centre = (current[0] - rx * math.cos(start), current[1] - ry * math.sin(start))
            remaining, angle = command.sweep_angle, command.start_angle
            while remaining:
                segment = max(-10_800_000, min(10_800_000, remaining))
                angle += segment
                end = math.radians(angle / 60_000)
                current = (centre[0] + rx * math.cos(end), centre[1] + ry * math.sin(end))
                parts.append(
                    f"A {_number(rx)} {_number(ry)} 0 0 {int(command.sweep_angle >= 0)} "
                    f"{_number(current[0])} {_number(current[1])}"
                )
                remaining -= segment
        else:
            parts.append("Z")
            current = start_of_subpath
    return f"path('{' '.join(parts)}')" if parts else None


def _fill_layer_needed(node: ShapeNode) -> bool:
    """Whether a faded picture or pattern shares its shape with text, an outline or effects."""
    return bool(node.text or node.line is not None or node.effects)


def _faded_fill_layer(style: str, opacity: float) -> tuple[str, str]:
    """Move a shape's background onto its own faded layer, behind its text.

    CSS ``opacity`` fades the whole element; here only the picture or pattern is faded, the text,
    outline and effects having been faded already. ``isolation`` keeps the layer's negative
    ``z-index`` inside the element.
    """
    kept: list[str] = []
    moved: list[str] = []
    for declaration in style.split(";"):
        (moved if declaration.strip().startswith("background") else kept).append(declaration)
    layer = (
        '<div data-domoxml-fill-layer="true" style="position:absolute;left:0;top:0;width:100%;'
        f"height:100%;border-radius:inherit;pointer-events:none;z-index:-1;{';'.join(moved)};"
        f'opacity:{_number(opacity)}"></div>'
    )
    return ";".join([*kept, "isolation:isolate"]), layer


def _clip_shape(geometry: CustomGeometry, box: Box) -> str | None:
    """The CSS clip for a custom outline: ``polygon()`` when straight, else ``path()``."""
    polygon = _polygon_points(geometry, box)
    return f"polygon({polygon})" if polygon is not None else _path_px(geometry, box)


def _fill_survives_as_polygon_clip(node: ShapeNode) -> bool:
    """Whether a free-form polygon with a gradient or picture fill is a CSS ``clip-path``.

    The SVG form of custom geometry paints only a solid fill, so a gradient or picture would
    vanish on the way to HTML. A polygon-only path is the same shape as a clip over the element's
    own background, which any fill and the round trip back to a native path both survive.
    """
    return (
        node.custom_geom is not None
        and isinstance(node.fill, GradientFill | PictureFill)
        and node.portable_fallback is None
        and not node.effects
        and node.line is None
        and _clip_shape(node.custom_geom, node.box) is not None
    )


def _transform_css(t: Transform | None) -> str | None:
    """Return a CSS ``transform`` value for a :class:`Transform`, or ``None`` for identity.

    OOXML ``rot`` is clockwise-positive in 60000ths of a degree; CSS ``rotate()`` is also
    clockwise-positive in degrees — no sign flip needed.

    ``flipH`` → ``scaleX(-1)``; ``flipV`` → ``scaleY(-1)``.  Rotation is listed first so
    the flip is applied in the shape's own (already-rotated) coordinate system, matching
    how PowerPoint renders combined rot+flip.
    """
    if t is None:
        return None
    parts: list[str] = []
    if t.rotation_deg != 0.0:
        parts.append(f"rotate({_number(t.rotation_deg)}deg)")
    if t.flip_h:
        parts.append("scaleX(-1)")
    if t.flip_v:
        parts.append("scaleY(-1)")
    return " ".join(parts) if parts else None


def _shape_style(
    node: ShapeNode, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]
) -> str:
    styles = [
        "position:absolute",
        "box-sizing:border-box",
        f"left:{_px(node.box.x)}",
        f"top:{_px(node.box.y)}",
        f"width:{_px(node.box.width)}",
        f"height:{_px(node.box.height)}",
    ]
    if isinstance(node.fill, SolidFill):
        styles.append(f"background-color:{_rgba(node.fill.color, opacity=node.opacity)}")
    elif isinstance(node.fill, GradientFill):
        styles.append(f"background-image:{_gradient(node.fill, opacity=node.opacity)}")
    elif isinstance(node.fill, PictureFill) and _is_backdrop_blur_layer(node):
        # The sharp backdrop picture exists only so PowerPoint can blur it. In HTML the element is
        # transparent and `backdrop-filter` blurs whatever really is behind it.
        pass
    elif isinstance(node.fill, PictureFill):
        asset = _asset(node.fill)
        assets.setdefault(asset.path, asset)
        styles.append(f"background-image:url(../{asset.path})")
        if node.fill.crop is not None:
            # A:srcRect crop -> background-size/position percentages (cover-style window).
            crop = node.fill.crop
            size, position = srcrect_to_background((crop.left, crop.top, crop.right, crop.bottom))
            styles.append(f"background-size:{size}")
            styles.append(f"background-position:{position}")
            styles.append("background-repeat:no-repeat")
        else:
            styles.append("background-size:100% 100%")
        if _enlarged_a_lot(node.fill, node.box.width, node.box.height):
            styles.append("image-rendering:pixelated")
    elif isinstance(node.fill, PatternFill):
        # Map a:pattFill to CSS. The six round-trip presets become an exact
        # repeating-linear-gradient; all other presets fall back to an inline SVG tile and warn.
        fg_hex = _color_spec_hex(node.fill.fg)
        bg_hex = _color_spec_hex(node.fill.bg)
        prop, value, approximated = pattern_to_css(fg_hex, bg_hex, node.fill.preset)
        styles.append(f"{prop}:{value}")
        if prop == "background-image":
            styles.append("background-repeat:repeat")
        if approximated:
            warnings.append(
                ConversionWarning(
                    message=(
                        f"a:pattFill preset {node.fill.preset!r} approximated as an SVG tile "
                        "(no exact CSS equivalent)"
                    )
                )
            )
    # ``opacity`` is the fill's alone (the rest of the shape was faded in the IR), so a picture or
    # pattern that is not the only thing painted is faded on its own layer, never the element.
    if (
        isinstance(node.fill, PictureFill | PatternFill)
        and node.opacity < 1.0
        and not _fill_layer_needed(node)
    ):
        styles.append(f"opacity:{_number(node.opacity)}")
    if node.line is not None:
        line = node.line
        border_style = _CSS_DASH.get(line.dash, "dashed")
        if line.gradient is not None:
            # Gradient stroke: emit border-image with a linear-gradient.
            # CSS border-image with slice=1 stretches the gradient across all four sides.
            # NOTE: approximation — border-image does not honour border-radius; a true
            # gradient stroke is only achievable via outline or SVG on the web.
            grad_css = _gradient(line.gradient, opacity=node.opacity)
            styles.append(f"border:{_px(line.width_emu)} {border_style} transparent")
            styles.append(f"border-image:{grad_css} 1")
        else:
            styles.append(f"border:{_px(line.width_emu)} {border_style} {_rgba(line.color)}")
        # Preserve cap/join as CSS custom properties for round-trip fidelity.
        # These have no CSS border equivalent but survive serialization.
        if line.cap != "flat":
            styles.append(f"--domoxml-cap:{line.cap}")
        if line.join != "round":
            styles.append(f"--domoxml-join:{line.join}")
        # Arrowheads: no CSS border equivalent — emit a warning and preserve via data.
        if line.head is not None and line.head.type != "none":
            styles.append(f"--domoxml-head:{line.head.type}/{line.head.width}/{line.head.length}")
            warnings.append(
                ConversionWarning(
                    message="arrowhead present but not rendered in HTML (connectors task pending)"
                )
            )
        if line.tail is not None and line.tail.type != "none":
            styles.append(f"--domoxml-tail:{line.tail.type}/{line.tail.width}/{line.tail.length}")
            warnings.append(
                ConversionWarning(
                    message="arrowhead present but not rendered in HTML (connectors task pending)"
                )
            )
        if line.gradient is not None:
            warnings.append(
                ConversionWarning(
                    message="gradient stroke approximated as border-image"
                    " (border-radius not honoured)"
                )
            )
    if node.geom == "ellipse":
        styles.append("border-radius:50%")
    elif node.geom == "roundRect" and node.corner_radius_emu > 0:
        styles.append(f"border-radius:{_px(node.corner_radius_emu)}")
    elif node.geom not in ("rect", "roundRect", "ellipse"):
        # Polygon-expressible preset: emit clip-path using the shared preset formulas.
        # adj overrides are not round-tripped on the reverse path (default values are used).
        clip = _clip_path_css(node.geom)
        if clip is not None:
            styles.append(clip)
    if _fill_survives_as_polygon_clip(node) and node.custom_geom is not None:
        clip_shape = _clip_shape(node.custom_geom, node.box)
        if clip_shape is not None:
            styles.append(f"clip-path:{clip_shape}")
    # Emit effects
    _append_effect_styles(node, styles, warnings)
    # Emit rotation/flip transform if present.
    transform_css = _transform_css(node.transform)
    if transform_css is not None:
        styles.append(f"transform:{transform_css}")
    return ";".join(styles)


def _is_backdrop_blur_layer(node: ShapeNode) -> bool:
    """Whether ``node`` is a sharp backdrop picture with a native blur (a CSS backdrop filter)."""
    return (
        isinstance(node.fill, PictureFill)
        and node.fill.raster_role == "backdrop-layer"
        and any(isinstance(effect, Blur) for effect in node.effects)
    )


def _append_effect_styles(
    node: ShapeNode,
    styles: list[str],
    warnings: list[ConversionWarning],
) -> None:
    """Append CSS properties for each effect in ``node.effects`` to ``styles``."""
    box_shadows: list[str] = []
    blur_filters: list[str] = []
    soft_edge_masks: list[str] = []

    for effect in node.effects:
        if isinstance(effect, Shadow):
            radians = math.radians(effect.direction_deg)
            offset_x = emu_to_px(round(math.cos(radians) * effect.distance_emu))
            offset_y = emu_to_px(round(math.sin(radians) * effect.distance_emu))
            blur_px = emu_to_px(effect.blur_emu)
            if not effect.inset:
                blur_px /= BOX_SHADOW_BLUR_TO_DML
            spread_px = emu_to_px(effect.spread_emu) if effect.spread_emu else 0.0
            inset_kw = " inset" if effect.inset else ""
            box_shadows.append(
                f"{_number(offset_x)}px {_number(offset_y)}px "
                f"{_number(blur_px)}px {_number(spread_px)}px "
                f"{_rgba(effect.color)}{inset_kw}"
            )
        elif isinstance(effect, Glow):
            # Approximate a:glow as a non-inset, centered box-shadow:
            # offset=0, blur=radius, spread=radius/2 (gives a visible halo around the box).
            rad_px = emu_to_px(effect.radius_emu)
            spread_px = rad_px / 2
            box_shadows.append(
                f"0px 0px {_number(rad_px)}px {_number(spread_px)}px {_rgba(effect.color)}"
            )
        elif isinstance(effect, Blur) and _is_backdrop_blur_layer(node):
            sigma = emu_to_px(effect.radius_emu) / DRAWINGML_BLUR_RADIUS_PER_CSS_SIGMA
            styles.append(f"backdrop-filter:blur({_number(sigma)}px)")
        elif isinstance(effect, Blur):
            blur_filters.append(f"blur({_number(emu_to_px(effect.radius_emu))}px)")
            warnings.append(
                ConversionWarning(
                    message=(
                        "a:blur mapped to CSS filter:blur(); rebuilt PPTX uses an isolated "
                        "renderer fallback"
                    )
                )
            )
        elif isinstance(effect, SoftEdge):
            if effect.radius_emu == 0:
                continue
            rad_px = _number(emu_to_px(effect.radius_emu))
            if node.geom == "ellipse":
                soft_edge_masks.append(
                    "radial-gradient(ellipse closest-side at 50% 50%,"
                    f"black calc(100% - {rad_px}px),transparent 100%)"
                )
            else:
                stops = (
                    f"transparent 0px,black {rad_px}px,"
                    f"black calc(100% - {rad_px}px),transparent 100%"
                )
                soft_edge_masks.extend(
                    (
                        f"linear-gradient(to right,{stops})",
                        f"linear-gradient(to bottom,{stops})",
                    )
                )
            warnings.append(
                ConversionWarning(
                    message=(
                        "a:softEdge mapped to a geometry-aware CSS alpha mask; rebuilt PPTX "
                        "uses an isolated renderer fallback"
                    )
                )
            )
        elif isinstance(effect, Reflection):
            dist_px = _number(emu_to_px(effect.distance_emu))
            if effect.blur_emu == 0:
                gradient = (
                    "linear-gradient(to bottom, "
                    f"rgba(0,0,0,{_number(effect.start_alpha)}) 0%, "
                    f"rgba(0,0,0,{_number(effect.end_alpha)}) 100%)"
                )
                styles.append(f"-webkit-box-reflect:below {dist_px}px {gradient}")
            warnings.append(
                ConversionWarning(
                    message=(
                        (
                            "a:reflection mapped to -webkit-box-reflect; rebuilt PPTX uses an "
                            "isolated renderer fallback"
                        )
                        if effect.blur_emu == 0
                        else (
                            "blurred a:reflection rendered as an owned CSS layer; rebuilt PPTX "
                            "uses an isolated renderer fallback"
                        )
                    )
                )
            )
        else:
            overlay = (
                f"linear-gradient({_rgba(effect.fill.color)},{_rgba(effect.fill.color)})"
                if isinstance(effect.fill, SolidFill)
                else pattern_to_css(
                    _color_spec_hex(effect.fill.fg),
                    _color_spec_hex(effect.fill.bg),
                    effect.fill.preset,
                )[1]
                if isinstance(effect.fill, PatternFill)
                else _gradient(effect.fill, opacity=1.0)
            )
            background_index = next(
                (
                    index
                    for index in range(len(styles) - 1, -1, -1)
                    if styles[index].startswith("background-image:")
                ),
                None,
            )
            if background_index is None:
                styles.append(f"background-image:{overlay}")
                blend_modes = _fill_overlay_blend_css(effect)
            else:
                base_background = styles[background_index].removeprefix("background-image:")
                styles[background_index] = f"background-image:{overlay},{base_background}"
                blend_modes = f"{_fill_overlay_blend_css(effect)},normal"
                for property_name, overlay_value in (
                    ("background-size", "auto"),
                    ("background-position", "0% 0%"),
                    ("background-repeat", "repeat"),
                    ("background-origin", "padding-box"),
                    ("background-clip", "border-box"),
                ):
                    prefix = f"{property_name}:"
                    property_index = next(
                        (
                            index
                            for index in range(len(styles) - 1, -1, -1)
                            if styles[index].startswith(prefix)
                        ),
                        None,
                    )
                    if property_index is not None:
                        base_value = styles[property_index].removeprefix(prefix)
                        styles[property_index] = f"{prefix}{overlay_value},{base_value}"
            styles.append(f"background-blend-mode:{blend_modes}")
            overlay_visible = (
                effect.fill.color.a > 0.0
                if isinstance(effect.fill, SolidFill)
                else any(stop.color.a > 0.0 for stop in effect.fill.stops)
                if isinstance(effect.fill, GradientFill)
                else True
            )
            if overlay_visible:
                warnings.append(
                    ConversionWarning(
                        message=(
                            "a:fillOverlay mapped to CSS background blending; rebuilt PPTX uses "
                            "an isolated renderer fallback"
                        )
                    )
                )

    if box_shadows:
        styles.append(f"box-shadow:{','.join(box_shadows)}")
    if blur_filters:
        styles.append(f"filter:{' '.join(blur_filters)}")
    if soft_edge_masks:
        styles.append(f"mask-image:{','.join(soft_edge_masks)}")
        styles.append("-webkit-mask-image:" + ",".join(soft_edge_masks))
        styles.append("mask-composite:intersect")


def _custom_geometry_filter(
    node: ShapeNode,
    warnings: list[ConversionWarning],
) -> str | None:
    """Return path-aware CSS filters for the custom-geometry effects HTML can paint exactly."""
    filters: list[str] = []
    for effect in node.effects:
        if isinstance(effect, Shadow):
            if effect.inset or effect.spread_emu != 0:
                warnings.append(
                    ConversionWarning(
                        message=(
                            "custom-geometry shadow cannot use a path-aware CSS filter with inset "
                            "or spread; exact typed effect metadata retained"
                        ),
                        element=node.node_id or "custom-geometry",
                    )
                )
                continue
            radians = math.radians(effect.direction_deg)
            offset_x = emu_to_px(round(math.cos(radians) * effect.distance_emu))
            offset_y = emu_to_px(round(math.sin(radians) * effect.distance_emu))
            blur_px = emu_to_px(effect.blur_emu) / CUSTOM_SHADOW_BLUR_TO_DML
            color = effect.color.model_copy(
                update={"a": min(1.0, effect.color.a / CUSTOM_SHADOW_ALPHA_TO_DML)}
            )
            filters.append(
                f"drop-shadow({_number(offset_x)}px {_number(offset_y)}px "
                f"{_number(blur_px)}px {_rgba(color)})"
            )
        elif isinstance(effect, Glow):
            radius_px = emu_to_px(effect.radius_emu) / CUSTOM_GLOW_RADIUS_TO_DML
            color = effect.color.model_copy(
                update={"a": min(1.0, effect.color.a / CUSTOM_GLOW_ALPHA_TO_DML)}
            )
            filters.append(f"drop-shadow(0px 0px {_number(radius_px)}px {_rgba(color)})")
        elif isinstance(effect, Blur):
            filters.append(f"blur({_number(emu_to_px(effect.radius_emu))}px)")
        else:
            warnings.append(
                ConversionWarning(
                    message=(
                        f"{effect.kind} cannot yet paint on custom-geometry HTML; "
                        "exact typed effect metadata retained"
                    ),
                    element=node.node_id or "custom-geometry",
                )
            )
    return " ".join(filters) if filters else None


def _fill_overlay_blend_css(effect: FillOverlay) -> str:
    return {
        "mult": "multiply",
        "screen": "screen",
        "darken": "darken",
        "lighten": "lighten",
        "over": "normal",
    }[effect.blend]


def _blurred_reflection_layer(node: ShapeNode, assets: dict[str, HtmlAsset]) -> tuple[str, str]:
    """Renderer-only child and parent metadata for a reflection with independent blur."""
    reflection = next(
        (
            effect
            for effect in node.effects
            if isinstance(effect, Reflection) and effect.blur_emu > 0
        ),
        None,
    )
    if reflection is None:
        return "", ""

    reflected = node.model_copy(
        update={
            "box": node.box.model_copy(update={"x": 0, "y": 0}),
            "effects": (),
            "portable_fallback": None,
            "transform": None,
        }
    )
    child_style = _shape_style(reflected, assets, [])
    body_css = _text_body_css(
        reflected.text, [], reflected.line.width_emu if reflected.line is not None else 0
    )
    if body_css:
        child_style += ";" + body_css
    distance_px = _number(emu_to_px(reflection.distance_emu))
    blur_px = _number(emu_to_px(reflection.blur_emu))
    mask = (
        "linear-gradient(to bottom, "
        f"rgba(0,0,0,{_number(reflection.end_alpha)}) 0%, "
        f"rgba(0,0,0,{_number(reflection.start_alpha)}) 100%)"
    )
    child_style += (
        f";left:0;top:calc(100% + {distance_px}px);position:absolute;"
        f"transform:scaleY(-1);transform-origin:center;filter:blur({blur_px}px);"
        f"mask-image:{mask};-webkit-mask-image:{mask};pointer-events:none"
    )
    parent_attrs = (
        f' data-domoxml-reflection-distance="{distance_px}"'
        f' data-domoxml-reflection-blur="{blur_px}"'
    )
    child = (
        '<div class="domoxml-reflection-layer" data-domoxml-render-layer="true" '
        f'aria-hidden="true" style="{escape(child_style, quote=True)}">'
        f"{_text_html(reflected.text, [])}</div>"
    )
    return parent_attrs, child


_UNDERLINE_STYLES = {
    "wavy": "wavy",
    "wavyHeavy": "wavy",
    "wavyDbl": "wavy",
    "dotted": "dotted",
    "dottedHeavy": "dotted",
    "dash": "dashed",
    "dashHeavy": "dashed",
    "dashLong": "dashed",
    "dashLongHeavy": "dashed",
    "dbl": "double",
}


def _vertical_align(run: TextRun) -> str:
    """CSS ``vertical-align`` for a lifted run: the keywords for the standard lifts."""
    if run.baseline == 30_000:
        return "super"
    if run.baseline == -25_000:
        return "sub"
    stored_pt = run.size_pt * 1.5  # PowerPoint stores a lifted run at 1.5x the size it draws
    return f"{_number(run.baseline / 100_000 * stored_pt)}pt"


def _decoration_css(run: TextRun) -> str | None:
    """``text-decoration-line`` for the run (underline and/or line-through), or ``None``."""
    lines: list[str] = []
    if run.underline is not False:
        lines.append("underline")
    if run.strike:
        lines.append("line-through")
    return " ".join(lines) if lines else None


_SERIF_FONTS = frozenset(
    {
        "times new roman", "times", "georgia", "cambria", "garamond", "palatino",
        "palatino linotype", "book antiqua", "baskerville", "didot", "constantia", "minion pro",
        "century schoolbook", "bodoni mt", "hoefler text", "iowan old style", "charter",
        "lora", "merriweather", "playfair display", "libre baskerville", "pt serif", "noto serif",
        "source serif pro", "source serif 4", "crimson text", "crimson pro", "eb garamond",
        "cormorant", "cormorant garamond", "roboto serif", "dm serif display", "dm serif text",
        "spectral", "bitter", "domine", "vollkorn", "alegreya", "libre caslon text", "cardo",
        "gelasio", "tinos", "liberation serif", "dejavu serif", "droid serif", "rockwell",
        "sitka", "century", "bookman old style", "perpetua", "calisto mt", "goudy old style",
        "plantin", "sabon", "caslon", "bembo", "abril fatface", "cinzel", "zilla slab",
    }
)  # fmt: skip
_MONO_FONTS = frozenset(
    {
        "courier new", "courier", "consolas", "menlo", "monaco", "lucida console",
        "andale mono", "source code pro", "fira code", "jetbrains mono", "sf mono",
        "roboto mono", "ibm plex mono", "space mono", "dm mono", "inconsolata", "ubuntu mono",
        "cascadia code", "cascadia mono", "liberation mono", "dejavu sans mono", "noto sans mono",
        "fira mono", "courier prime", "pt mono", "anonymous pro", "hack", "droid sans mono",
        "lucida sans typewriter", "ocr a extended",
    }
)  # fmt: skip


def _css_font_family(family: str) -> str:
    """A family with the generic one a browser should fall back to when the font is missing."""
    if "," in family or family.lower() in _GENERIC_FAMILIES:
        return family
    lowered = family.lower()
    generic = (
        "serif"
        if lowered in _SERIF_FONTS or (re.search(r"\bserif\b", lowered) and "sans" not in lowered)
        else "monospace"
        if lowered in _MONO_FONTS or lowered.endswith((" mono", " code", " typewriter"))
        else "sans-serif"
    )
    return f"{family},{generic}"


_GENERIC_FAMILIES = frozenset(
    {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}
)


def _run_html(run: TextRun) -> str:
    styles = [
        f"font-family:{_css_font_family(run.font_family)}",
        f"font-size:{_number(run.size_pt)}pt",
        f"font-weight:{'700' if run.bold else '400'}",
        f"font-style:{'italic' if run.italic else 'normal'}",
        f"color:{_rgba(run.color)}",
    ]
    if run.baseline:
        styles.append(f"vertical-align:{_vertical_align(run)}")
    decoration = _decoration_css(run)
    if decoration is not None:
        styles.append(f"text-decoration-line:{decoration}")
        style = _UNDERLINE_STYLES.get(run.underline) if isinstance(run.underline, str) else None
        if style is not None:
            styles.append(f"text-decoration-style:{style}")
        if run.underline_color is not None and run.underline is not False:
            styles.append(f"text-decoration-color:{_rgba(run.underline_color)}")
    if run.caps == "all":
        styles.append("text-transform:uppercase")
    elif run.caps == "small":
        styles.append("font-variant-caps:small-caps")
    if run.letter_spacing_pt:
        styles.append(f"letter-spacing:{_number(run.letter_spacing_pt)}pt")
    if run.gradient is not None:
        # Gradient text is a gradient background clipped to the glyphs, with the fill made clear.
        styles = [s for s in styles if not s.startswith("color:")]
        styles += [
            f"background-image:{_gradient(run.gradient, opacity=1.0)}",
            "-webkit-background-clip:text",
            "background-clip:text",
            "color:transparent",
        ]
    if run.outline is not None:
        styles.append(
            f"-webkit-text-stroke:{_number(run.outline.width_pt)}pt {_rgba(run.outline.color)}"
        )
    if run.shadow is not None:
        radians = math.radians(run.shadow.direction_deg)
        offset_x = emu_to_px(round(math.cos(radians) * run.shadow.distance_emu))
        offset_y = emu_to_px(round(math.sin(radians) * run.shadow.distance_emu))
        styles.append(
            f"text-shadow:{_number(offset_x)}px {_number(offset_y)}px "
            f"{_number(emu_to_px(run.shadow.blur_emu))}px {_rgba(run.shadow.color)}"
        )
    span = f'<span style="{escape(";".join(styles), quote=True)}">{escape(run.text)}</span>'
    return _wrap_hyperlink(span, run)


def _wrap_hyperlink(inner: str, run: TextRun) -> str:
    """Wrap a run's span in an ``<a href>`` when it carries a hyperlink. An internal slide jump
    uses the ``#slide-N`` (1-based) authoring convention; otherwise the external URL is used."""
    link = run.hyperlink
    if link is None:
        return inner
    if link.slide_index is not None:
        href = f"#slide-{link.slide_index + 1}"
    elif link.url is not None:
        href = link.url
        if (
            not (href.startswith("#slide-") and href[7:].isdigit())
            and urlsplit(href).scheme.lower() not in _SAFE_HYPERLINK_SCHEMES
        ):
            return inner
    else:
        return inner
    return f'<a href="{escape(href, quote=True)}">{inner}</a>'


def _para_spacing_style(paragraph: TextParagraph, *, include_indentation: bool = True) -> str:
    """Return inline CSS for paragraph-level spacing/indent (no trailing semicolon)."""
    styles: list[str] = []
    if paragraph.line_spacing is not None:
        ls = paragraph.line_spacing
        if ls.percent is not None:
            styles.append(f"line-height:{_number(ls.percent * SINGLE_LINE_EM)}")
        elif ls.points is not None:
            styles.append(f"line-height:{_number(ls.points)}pt")
    if paragraph.space_before_pt:
        styles.append(f"margin-top:{_number(paragraph.space_before_pt)}pt")
    if paragraph.space_after_pt:
        styles.append(f"margin-bottom:{_number(paragraph.space_after_pt)}pt")
    if include_indentation:
        if paragraph.indent_pt:
            styles.append(f"text-indent:{_number(paragraph.indent_pt)}pt")
        if paragraph.left_margin_pt:
            styles.append(f"padding-left:{_number(paragraph.left_margin_pt)}pt")
    return ";".join(styles)


def _bullet_list_style(paragraph: TextParagraph) -> str:
    """Return the CSS list-style-type value for a bulleted paragraph."""
    bullet = paragraph.bullet
    if isinstance(bullet, CharBullet):
        css = bu_char_to_css_list_style(bullet.char)
        # For known CSS types return them directly; unknowns need a content workaround
        if css in {"disc", "circle", "square"}:
            return css
        # Custom char: use content via CSS — we approximate with a data URI style trick.
        # Return it as-is; the <li> will get list-style-type:none + ::marker trick.
        return css
    if isinstance(bullet, AutoNumberBullet):
        return autonum_to_css_list_style(bullet.scheme)
    return "disc"


def _text_body_css(
    body: TextBody | None, warnings: list[ConversionWarning], border_emu: int = 0
) -> str:
    """Return inline CSS for text body container (vertical anchor, columns).

    Emits flex properties for non-top anchors; column CSS for multi-column bodies.
    Returns an empty string when no special properties are needed. The insets run from the box's
    edge, so a CSS border on the same element (``border_emu``) is taken out of the padding.
    """
    if body is None:
        return ""
    styles: list[str] = []
    if body.anchor == "middle":
        styles.extend(["display:flex", "flex-direction:column", "justify-content:center"])
    elif body.anchor == "bottom":
        styles.extend(["display:flex", "flex-direction:column", "justify-content:flex-end"])
    if body.vertical != "horz":
        styles.append(
            "writing-mode:vertical-rl" if body.vertical == "vert" else "writing-mode:sideways-lr"
        )
    if body.columns > 1:
        styles.append(f"column-count:{body.columns}")
        styles.append("column-fill:auto")
        styles.append(f"column-gap:{_px(body.column_gap_emu)}")
    if any(body.margins):
        left, top, right, bottom = (max(0, margin - border_emu) for margin in body.margins)
        styles.append(f"padding:{_px(top)} {_px(right)} {_px(bottom)} {_px(left)}")
    return ";".join(styles)


def _plain_text_body(body: TextBody | None) -> bool:
    """Whether emitted block children can safely consolidate back into one text shape."""
    return body is not None and all(paragraph.bullet is None for paragraph in body.paragraphs)


def _text_html(body: TextBody | None, warnings: list[ConversionWarning] | None = None) -> str:
    """Serialize text body to HTML. Consecutive bulleted paragraphs at the same level
    become nested ``<ul>``/``<ol>`` elements; plain paragraphs become ``<div>``.

    When ``warnings`` is provided, emits ``data-domoxml-autofit`` metadata and issues a
    warning when ``a:normAutofit`` has a non-trivial ``fontScale`` (fontScale is not stored
    in the IR yet — the attribute is only encountered on the reverse path from authored
    PPTX, not round-tripped from HTML; no warning is emitted here).
    """
    if body is None:
        return ""

    # We process paragraphs in order, maintaining a list-context stack.
    # Stack entries: (list_tag, level) — "ul" or "ol", nesting depth.
    result: list[str] = []
    # (list_tag, level) → open list tags we need to close
    open_lists: list[tuple[str, int]] = []  # stack of (tag, level)

    def _close_lists_to_level(target_level: int) -> None:
        """Close all open lists above target_level."""
        while open_lists and open_lists[-1][1] > target_level:
            tag, _ = open_lists.pop()
            result.append(f"</{tag}>")

    def _close_all_lists() -> None:
        while open_lists:
            tag, _ = open_lists.pop()
            result.append(f"</{tag}>")

    for paragraph in body.paragraphs:
        bullet = paragraph.bullet
        if bullet is not None:
            # Determine list tag: AutoNumberBullet → ol, CharBullet → ul.
            list_tag = "ol" if isinstance(bullet, AutoNumberBullet) else "ul"
            target_level = paragraph.level + 1  # 1-based for stack comparisons

            # Close lists that are deeper than current level.
            _close_lists_to_level(target_level)

            # Check whether we need to open a new list at this level.
            if not open_lists or open_lists[-1][1] < target_level:
                # Need to open a new list.
                list_style = _bullet_list_style(paragraph)
                start_attr = ""
                if isinstance(bullet, AutoNumberBullet) and bullet.start_at != 1:
                    start_attr = f' start="{bullet.start_at}"'
                marker_gutter_pt = paragraph.left_margin_pt or 13.5
                list_css = (
                    f"list-style-type:{escape(list_style, quote=True)};"
                    f"padding-left:{_number(marker_gutter_pt)}pt"
                )
                result.append(f'<{list_tag} style="{list_css}"{start_attr}>')
                open_lists.append((list_tag, target_level))

            # Emit the <li>
            # CSS's native outside marker implements DrawingML's hanging indent. Applying the
            # paragraph margin/indent again on the <li> would double the gutter on round-trip.
            spacing_style = _para_spacing_style(paragraph, include_indentation=False)
            li_style = f"text-align:{paragraph.align}"
            if spacing_style:
                li_style += ";" + spacing_style
            runs_html = "".join(_run_html(run) for run in paragraph.runs)
            result.append(f'<li style="{escape(li_style, quote=True)}">{runs_html}</li>')
        else:
            # Plain paragraph — close all open lists first.
            _close_all_lists()
            spacing_style = _para_spacing_style(paragraph)
            base = "white-space:pre" if body.wrap == "none" else _TEXT_BASE_STYLE
            div_style = f"{base};text-align:{paragraph.align}"
            if spacing_style:
                div_style += ";" + spacing_style
            runs_html = "".join(_run_html(run) for run in paragraph.runs)
            result.append(
                f'<div class="domoxml-text" style="{escape(div_style, quote=True)}">'
                f"{runs_html}</div>"
            )

    _close_all_lists()
    return "".join(result)


def _group_fallback_html(
    group: GroupNode,
    reason: str,
    assets: dict[str, HtmlAsset],
    warnings: list[ConversionWarning],
) -> str:
    """Visibly flatten a valid group that is outside the structural round-trip subset."""
    if (
        group.box.width <= 0
        or group.box.height <= 0
        or group.child_box.width <= 0
        or group.child_box.height <= 0
    ):
        raise ValueError(f"cannot flatten invalid group: {reason}")
    warnings.append(
        ConversionWarning(
            message=f"group visibly flattened for HTML: {reason}",
            element=group.node_id or "<group>",
        )
    )
    scale_x = group.box.width / group.child_box.width
    scale_y = group.box.height / group.child_box.height

    def local_point(point: Point) -> Point:
        return Point(
            x=round((point.x - group.child_box.x) * scale_x),
            y=round((point.y - group.child_box.y) * scale_y),
        )

    parts: list[str] = []
    projected_children: list[ShapeNode | GroupNode | Connector] = []
    for child in group.children:
        if isinstance(child, ShapeNode | GroupNode):
            box = child.box
            remapped = child.model_copy(
                update={
                    "box": Box(
                        x=round((box.x - group.child_box.x) * scale_x),
                        y=round((box.y - group.child_box.y) * scale_y),
                        width=round(box.width * scale_x),
                        height=round(box.height * scale_y),
                    )
                }
            )
        else:
            remapped = child.model_copy(
                update={"start": local_point(child.start), "end": local_point(child.end)}
            )
        projected_children.append(remapped)
        parts.append(_node_html(remapped, assets, warnings))

    styles = [
        "position:absolute",
        f"left:{_px(group.box.x)}",
        f"top:{_px(group.box.y)}",
        f"width:{_px(group.box.width)}",
        f"height:{_px(group.box.height)}",
        "overflow:visible",
    ]
    if transform := _transform_css(group.transform):
        styles.extend((f"transform:{transform}", "transform-origin:center center"))
    payload = encode_group_payload(
        box=group.box,
        child_box=group.child_box,
        transform=group.transform,
        children=group.children,
        projected_children=tuple(projected_children),
    )
    return (
        f'<div class="domoxml-group-fallback"{_identity_attrs(group)} '
        f'data-domoxml-group="{payload}" '
        f'data-domoxml-group-flattened="{escape(reason, quote=True)}" '
        f'style="{escape(";".join(styles), quote=True)}">'
        f"{''.join(parts)}</div>"
    )


def _group_html(
    group: GroupNode, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]
) -> str:
    """Project an admitted :class:`GroupNode` to normalized HTML.

    OOXML groups define a child coordinate space (``a:chOff``/``a:chExt``) which may differ
    from the group's slide-space extent (``a:off``/``a:ext``).  Each child's position within
    that coordinate space is mapped to absolute slide EMUs using::

        child_slide_x = grp_off_x + (child_x - grp_chOff_x) * scale_x
        child_slide_y = grp_off_y + (child_y - grp_chOff_y) * scale_y
        scale_x       = grp_ext_cx / grp_chExt_cx
        scale_y       = grp_ext_cy / grp_chExt_cy

    The resulting children remain visually flat, but a ``display:contents`` metadata wrapper
    retains group identity and its two coordinate spaces for exact re-ingestion.

    Valid authored groups outside the proven reconstruction boundary visibly flatten with a
    warning. Reverse PPTX ingest converts those groups to preserved source plus a renderer
    fallback before this serializer.
    """
    if reason := group_html_roundtrip_error(group):
        return _group_fallback_html(group, reason, assets, warnings)
    g_off_x = group.box.x
    g_off_y = group.box.y
    g_ext_cx = group.box.width
    g_ext_cy = group.box.height
    ch_off_x = group.child_box.x
    ch_off_y = group.child_box.y
    ch_ext_cx = group.child_box.width
    ch_ext_cy = group.child_box.height

    scale_x = g_ext_cx / ch_ext_cx
    scale_y = g_ext_cy / ch_ext_cy

    parts: list[str] = []
    projected_children: list[ShapeNode] = []
    for child in group.children:
        if not isinstance(child, ShapeNode):
            raise ValueError(
                "cannot serialize native group to normalized HTML: "
                f"unsupported admitted child {type(child).__name__}"
            )
        # Remap child's box from group-child-space to slide space.
        c_box = child.box
        mapped_x = round(g_off_x + (c_box.x - ch_off_x) * scale_x)
        mapped_y = round(g_off_y + (c_box.y - ch_off_y) * scale_y)
        mapped_w = round(c_box.width * scale_x)
        mapped_h = round(c_box.height * scale_y)
        remapped_child = child.model_copy(
            update={"box": Box(x=mapped_x, y=mapped_y, width=mapped_w, height=mapped_h)}
        )
        if (
            group.node_id is not None
            and remapped_child.provenance is not None
            and remapped_child.provenance.owner_node_id is None
        ):
            remapped_child = remapped_child.model_copy(
                update={
                    "provenance": remapped_child.provenance.model_copy(
                        update={"owner_node_id": group.node_id}
                    )
                }
            )
        projected_children.append(remapped_child)
        parts.append(_node_html(remapped_child, assets, warnings))
    payload = encode_group_payload(
        box=group.box,
        child_box=group.child_box,
        transform=group.transform,
        children=group.children,
        projected_children=tuple(projected_children),
    )
    return (
        f'<div class="domoxml-group"{_identity_attrs(group)} '
        f'data-domoxml-group="{payload}" style="display:contents">'
        f"{''.join(parts)}</div>"
    )


# A picture drawn at least this many times larger than its own pixels keeps hard edges, as
# PowerPoint draws it (measured for shape fills, pictures and table cells), instead of the
# browser's smoothing; a modest enlargement stays smooth, as photographs want.
_PIXEL_SCALE = 4.0


def _enlarged_a_lot(fill: PictureFill, width_emu: int, height_emu: int) -> bool:
    """Whether ``fill`` is drawn at several times its own pixel size in a ``width_emu`` box."""
    if fill.svg_data is not None or fill.crop is not None:
        return False
    try:
        with Image.open(BytesIO(fill.data)) as image:
            pixels_w, pixels_h = image.size
    except (OSError, Image.DecompressionBombError):
        return False
    if pixels_w < 1 or pixels_h < 1:
        return False
    return (
        emu_to_px(width_emu) / pixels_w >= _PIXEL_SCALE
        or emu_to_px(height_emu) / pixels_h >= _PIXEL_SCALE
    )


def _fill_css(fill: Fill | None, *, opacity: float = 1.0) -> str | None:
    """Return a CSS ``background-color`` / ``background-image`` value string, or ``None``."""
    if isinstance(fill, SolidFill):
        return f"background-color:{_rgba(fill.color, opacity=opacity)}"
    if isinstance(fill, GradientFill):
        return f"background-image:{_gradient(fill, opacity=opacity)}"
    return None


def _border_side_css(line_val: object) -> str:
    """Return a CSS border shorthand for one side, or ``'none'``."""
    if not isinstance(line_val, Line):
        return "none"
    style = _CSS_DASH.get(line_val.dash, "solid")
    return f"{_px(line_val.width_emu)} {style} {_rgba(line_val.color)}"


def _table_html(
    node: TableNode,
    assets: dict[str, HtmlAsset],
    warnings: list[ConversionWarning],
) -> str:
    """Serialize a :class:`TableNode` to a positioned ``<table>`` element.

    The table is absolutely positioned (matching the graphicFrame box).
    Column widths are emitted via ``<colgroup>``. Cells have inline styles
    for fill, padding, and borders. Merge-continuation cells are skipped;
    origin cells get ``colspan``/``rowspan`` attributes.
    """
    left = _px(node.box.x)
    top = _px(node.box.y)
    w = _px(node.box.width)
    h = _px(node.box.height)
    table_style = (
        f"position:absolute;left:{left};top:{top};"
        f"width:{w};height:{h};"
        "box-sizing:border-box;border-collapse:collapse;table-layout:fixed"
    )

    # colgroup
    cols_html = "".join(f'<col style="width:{_px(cw)}"/>' for cw in node.col_widths_emu)
    colgroup = f"<colgroup>{cols_html}</colgroup>"

    n_cols = len(node.col_widths_emu)

    # Build the full grid to know which slots are continuations.
    # We reuse the same _build_full_grid logic inline here.
    occupied: set[tuple[int, int]] = set()
    # Recompute occupancy grid for HTML emission.
    for row_idx, row in enumerate(node.rows):
        col_cursor = 0
        for cell in row.cells:
            while col_cursor < n_cols and (row_idx, col_cursor) in occupied:
                col_cursor += 1
            if col_cursor >= n_cols:
                break
            cs = max(1, cell.col_span)
            rs = max(1, cell.row_span)
            for dr in range(rs):
                for dc in range(cs):
                    if dr == 0 and dc == 0:
                        continue
                    occupied.add((row_idx + dr, col_cursor + dc))
            col_cursor += cs

    # Build occupied lookup for col indexing. We need to know the current
    # column index for each logical cell in the row. Recompute per-row.
    rows_html = ""
    for row_idx, row in enumerate(node.rows):
        cells_html = ""
        col_cursor = 0
        for cell in row.cells:
            # Skip past continuations.
            while col_cursor < n_cols and (row_idx, col_cursor) in occupied:
                col_cursor += 1
            if col_cursor >= n_cols:
                break

            # The height the cell spans: its own row and those it merges into.
            spanned_height = sum(
                spanned.height_emu for spanned in node.rows[row_idx : row_idx + cell.row_span]
            )

            # Build cell style.
            cell_styles: list[str] = []
            fill_css = _fill_css(cell.fill)
            if fill_css is not None:
                cell_styles.append(fill_css)
            elif isinstance(cell.fill, PictureFill):
                picture = _asset(cell.fill)
                assets.setdefault(picture.path, picture)
                cell_styles.append(f"background-image:url(../{picture.path})")
                if cell.fill.crop is not None:
                    crop = cell.fill.crop
                    size, position = srcrect_to_background(
                        (crop.left, crop.top, crop.right, crop.bottom)
                    )
                    cell_styles.append(f"background-size:{size}")
                    cell_styles.append(f"background-position:{position}")
                else:
                    cell_styles.append("background-size:100% 100%")
                cell_styles.append("background-repeat:no-repeat")
                width = sum(node.col_widths_emu[col_cursor : col_cursor + max(1, cell.col_span)])
                if _enlarged_a_lot(cell.fill, width, spanned_height):
                    cell_styles.append("image-rendering:pixelated")
            # Padding from margins (order: top, right, bottom, left in IR tuple is (L,T,R,B)).
            mar_l, mar_t, mar_r, mar_b = cell.margins
            if any((mar_l, mar_t, mar_r, mar_b)):
                cell_styles.append(f"padding:{_px(mar_t)} {_px(mar_r)} {_px(mar_b)} {_px(mar_l)}")
            # Per-side borders.
            if cell.borders is not None:
                b = cell.borders
                cell_styles.append(f"border-left:{_border_side_css(b.left)}")
                cell_styles.append(f"border-right:{_border_side_css(b.right)}")
                cell_styles.append(f"border-top:{_border_side_css(b.top)}")
                cell_styles.append(f"border-bottom:{_border_side_css(b.bottom)}")

            cell_styles.append(f"vertical-align:{cell.valign}")
            if cell.text is not None and cell.text.vertical != "horz":
                cell_styles.append(
                    "writing-mode:vertical-rl"
                    if cell.text.vertical == "vert"
                    else "writing-mode:sideways-lr"
                )
            td_style = escape(";".join(cell_styles), quote=True)

            # Span attributes.
            span_attrs = ""
            if cell.col_span > 1:
                span_attrs += f' colspan="{cell.col_span}"'
            if cell.row_span > 1:
                span_attrs += f' rowspan="{cell.row_span}"'

            # Cell content.
            inner = _text_html(cell.text, warnings)
            room = spanned_height - mar_t - mar_b
            if cell.text is not None and cell.text.vertical != "horz" and room > 0:
                # Vertical text wraps within the cell's height (all the rows it spans), as
                # PowerPoint draws it, instead of stretching the rows to fit its whole length.
                inner = f'<div style="height:{_px(room)};overflow:hidden">{inner}</div>'
            cells_html += f'<td style="{td_style}"{span_attrs}>{inner}</td>'

            col_cursor += max(1, cell.col_span)

        rows_html += f'<tr style="height:{_px(row.height_emu)}">{cells_html}</tr>'

    return (
        f"<table{_identity_attrs(node)} "
        f'data-domoxml-table-geometry="{encode_table_geometry(node)}" '
        f'style="{escape(table_style, quote=True)}">'
        f"{colgroup}"
        f"<tbody>{rows_html}</tbody>"
        f"</table>"
    )


def _picture_outline_layers(
    node: ShapeNode, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]
) -> str | None:
    """A free-form picture fill with a stroke or text as the picture, its outline and its text.

    The SVG form of custom geometry cannot paint a picture, and a CSS clip hides the border and
    the text, so the three are separate layers over the same box: the clipped picture, a
    stroke-only SVG of the outline, and the text.
    """
    if (
        node.custom_geom is None
        or not isinstance(node.fill, PictureFill)
        or (node.line is None and node.text is None)
        or node.portable_fallback is not None
    ):
        return None
    picture = node.model_copy(update={"line": None, "text": None})
    if not _fill_survives_as_polygon_clip(picture):
        return None
    stretched = _stretched_over_outline(picture)
    picture_html = _node_html(stretched, assets, warnings)
    if stretched.box != picture.box and picture.transform is not None:
        # The outline and the text turn about the shape's own centre, so the larger picture box
        # must too, or an asymmetric tail would swing away from its stroke.
        pivot_x = picture.box.x + picture.box.width / 2 - stretched.box.x
        pivot_y = picture.box.y + picture.box.height / 2 - stretched.box.y
        picture_html = picture_html.replace(
            'style="', f'style="transform-origin:{_px(round(pivot_x))} {_px(round(pivot_y))};', 1
        )
    parts = [picture_html]
    if node.line is not None:
        outline = node.model_copy(
            update={
                "fill": None,
                "text": None,
                "effects": (),
                "opacity": 1.0,
                "node_id": None,
                "provenance": None,
            }
        )
        parts.append(_node_html(outline, assets, warnings))
    if node.text is not None:
        parts.append(_text_layer_html(node, warnings))
    return "".join(parts)


def _stretched_over_outline(node: ShapeNode) -> ShapeNode:
    """``node`` boxed to its outline's own bounds, so a picture reaches a callout's tail.

    PowerPoint stretches a picture over everything the outline draws, not just the shape's box.
    The geometry is re-based on the larger box so the clip stays where it was.
    """
    geometry = node.custom_geom
    bounds = outline_bounds(geometry) if geometry is not None else None
    if geometry is None or bounds is None or not outline_leaves_box(geometry):
        return node
    left, top, right, bottom = bounds
    scale_x = node.box.width / geometry.width_emu
    scale_y = node.box.height / geometry.height_emu

    def shift(point: Point) -> Point:
        return Point(x=round(point.x - left), y=round(point.y - top))

    path: list[PathCommand] = []
    for command in geometry.path:
        if isinstance(command, MoveTo | LineTo):
            path.append(command.model_copy(update={"to": shift(command.to)}))
        elif isinstance(command, CubicTo):
            path.append(
                command.model_copy(
                    update={
                        "c1": shift(command.c1),
                        "c2": shift(command.c2),
                        "to": shift(command.to),
                    }
                )
            )
        elif isinstance(command, QuadTo):
            path.append(
                command.model_copy(update={"c1": shift(command.c1), "to": shift(command.to)})
            )
        else:
            path.append(command)
    width, height = max(1, round(right - left)), max(1, round(bottom - top))
    return node.model_copy(
        update={
            "box": Box(
                x=round(node.box.x + left * scale_x),
                y=round(node.box.y + top * scale_y),
                width=max(1, round(width * scale_x)),
                height=max(1, round(height * scale_y)),
            ),
            "custom_geom": geometry.model_copy(
                update={"width_emu": width, "height_emu": height, "path": tuple(path)}
            ),
        }
    )


_THICK_DASHED_BORDER_EMU = 8 * 9525  # 8 px


def _dashed_rectangle(node: ShapeNode) -> ShapeNode | None:
    """A plain rectangle with a dashed or dotted outline as the stroked path PowerPoint draws.

    A CSS dashed border has its own dash lengths and square ends; a DrawingML dash is a multiple
    of the line width with the line's cap, which only an SVG stroke can reproduce. The path runs
    along the middle of the border band, as a DrawingML stroke is centred.
    """
    line = node.line
    if (
        line is None
        or node.geom != "rect"
        or (line.dash == "solid" and not line.custom_dash)
        # A thin dashed border is the same to the eye as CSS's, and keeps its CSS form; only a
        # thick stroke or a round or square cap shows the difference.
        or (line.cap == "flat" and line.width_emu < _THICK_DASHED_BORDER_EMU)
        or node.box.width <= 0
        or node.box.height <= 0
    ):
        return None
    half = line.width_emu // 2
    left, top = half, half
    right, bottom = node.box.width - half, node.box.height - half
    if right <= left or bottom <= top:
        return None  # a border band too thick to run a path through keeps the CSS border
    path = (
        MoveTo(to=Point(x=left, y=top)),
        LineTo(to=Point(x=right, y=top)),
        LineTo(to=Point(x=right, y=bottom)),
        LineTo(to=Point(x=left, y=bottom)),
        ClosePath(),
    )
    geometry = CustomGeometry(width_emu=node.box.width, height_emu=node.box.height, path=path)
    return node.model_copy(update={"custom_geom": geometry})


def _outlined_polygon_preset(node: ShapeNode) -> ShapeNode:
    """A stroked polygon preset as free-form geometry, so its outline is drawn.

    A CSS ``clip-path`` also clips the element's border, so a star or arrow with a stroke would
    lose it; as an SVG path the same silhouette keeps both.
    """
    if (
        node.line is None
        or node.custom_geom is not None
        or node.corner_radius_emu
        # The SVG paints a solid or gradient fill; a picture or pattern keeps its clipped div.
        or isinstance(node.fill, PictureFill | PatternFill)
    ):
        return node
    dashed = _dashed_rectangle(node)
    if dashed is not None:
        return dashed
    vertices = preset_vertices(node.geom, preset_defaults(node.geom))
    if vertices is None or node.box.width <= 0 or node.box.height <= 0:
        return node
    points = [Point(x=round(x * node.box.width), y=round(y * node.box.height)) for x, y in vertices]
    path = (MoveTo(to=points[0]), *(LineTo(to=point) for point in points[1:]), ClosePath())
    geometry = CustomGeometry(width_emu=node.box.width, height_emu=node.box.height, path=path)
    return node.model_copy(update={"geom": "rect", "custom_geom": geometry})


def _svg_gradient(
    fill: GradientFill, opacity: float, box: Box, geometry: CustomGeometry
) -> tuple[str, str] | None:
    """``(<defs>, fill attribute)`` painting ``fill`` on an outline's SVG, or ``None``.

    The gradient is laid out in the SVG's own units the way CSS lays it over the box, so it only
    applies where the path's units scale the box evenly (a stretched viewBox would skew it).
    """
    width_px, height_px = emu_to_px(box.width), emu_to_px(box.height)
    if width_px <= 0 or height_px <= 0 or geometry.width_emu <= 0 or geometry.height_emu <= 0:
        return None
    scale_x, scale_y = geometry.width_emu / width_px, geometry.height_emu / height_px
    if abs(scale_x - scale_y) > 1e-3 * scale_x:
        return None
    width, height = geometry.width_emu, geometry.height_emu
    stops = "".join(
        f'<stop offset="{_number(stop.pos)}" stop-color="rgb({stop.color.r},{stop.color.g},'
        f'{stop.color.b})" stop-opacity="{_number(stop.color.a * opacity)}"/>'
        for stop in fill.stops
    )
    identity = hashlib.sha1(
        f"{fill.model_dump_json()}{width}{height}{opacity}".encode(), usedforsecurity=False
    ).hexdigest()[:10]
    name = f"grad-{identity}"
    if fill.radial:
        paint = (
            f'<radialGradient id="{name}" gradientUnits="userSpaceOnUse" cx="{_number(width / 2)}"'
            f' cy="{_number(height / 2)}" r="{_number(math.hypot(width, height) / 2)}">{stops}'
            "</radialGradient>"
        )
    else:
        angle = math.radians(fill.angle_deg)
        dx, dy = math.sin(angle), -math.cos(angle)
        half = (abs(width * dx) + abs(height * dy)) / 2
        centre_x, centre_y = width / 2, height / 2
        paint = (
            f'<linearGradient id="{name}" gradientUnits="userSpaceOnUse"'
            f' x1="{_number(centre_x - dx * half)}" y1="{_number(centre_y - dy * half)}"'
            f' x2="{_number(centre_x + dx * half)}" y2="{_number(centre_y + dy * half)}">'
            f"{stops}</linearGradient>"
        )
    return f"<defs>{paint}</defs>", f'fill="url(#{name})"'


def _text_layer_html(node: ShapeNode, warnings: list[ConversionWarning]) -> str:
    """The text of a free-form outline as its own layer over the outline's SVG.

    The SVG form of custom geometry has no text, so the shape's text sits in a transparent box
    placed exactly over it; it follows the outline in z-order and extracts as a text shape.
    """
    styles = [
        "position:absolute",
        "box-sizing:border-box",
        f"left:{_px(node.box.x)}",
        f"top:{_px(node.box.y)}",
        f"width:{_px(node.box.width)}",
        f"height:{_px(node.box.height)}",
    ]
    if body_css := _text_body_css(node.text, warnings):
        styles.append(body_css)
    if (transform_css := _transform_css(node.transform)) is not None:
        styles.append(f"transform:{transform_css}")
    text_html = _text_html(node.text, warnings)
    flipped = node.transform is not None and node.transform.flip_h
    if text_html and flipped != (node.text is not None and node.text.mirror_x):
        text_html = f'<div style="transform:scaleX(-1)">{text_html}</div>'
    text_body_attr = ' data-domoxml-text-body="true"' if _plain_text_body(node.text) else ""
    return (
        f'<div class="domoxml-shape"{_text_payload_attrs(node)}{text_body_attr} '
        f'style="{escape(";".join(styles), quote=True)}">{text_html}</div>'
    )


def _node_html(node: Node, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]) -> str:
    """Serialize one slide node. :class:`ShapeNode`, :class:`MediaNode`, and
    :class:`TableNode` have HTML mappings; others warn and emit nothing."""
    if isinstance(node, ShapeNode):
        layered = _picture_outline_layers(node, assets, warnings)
        if layered is not None:
            return layered
        node = _outlined_polygon_preset(node)
        if (
            isinstance(node.fill, PictureFill)
            and node.fill.svg_data is not None
            and node.fill.crop is None
            and node.fill.mode == "stretch"
            and node.geom == "rect"
            and node.custom_geom is None
            and node.line is None
            and node.side_lines is None
            and not node.effects
            and node.corner_radius_emu == 0
            and node.text is None
        ):
            asset = _asset(node.fill)
            assets.setdefault(asset.path, asset)
            styles = [
                "position:absolute",
                "box-sizing:border-box",
                f"left:{_px(node.box.x)}",
                f"top:{_px(node.box.y)}",
                f"width:{_px(node.box.width)}",
                f"height:{_px(node.box.height)}",
            ]
            if node.opacity < 1.0:
                styles.append(f"opacity:{_number(node.opacity)}")
            transform_css = _transform_css(node.transform)
            if transform_css is not None:
                styles.append(f"transform:{transform_css}")
            return (
                f'<img class="domoxml-shape"{_identity_attrs(node)} '
                f'src="../{escape(asset.path, quote=True)}" alt="" '
                f'style="{escape(";".join(styles), quote=True)}">'
            )
        # Custom geometry: emit an inline SVG instead of a CSS-bordered div.
        if node.custom_geom is not None and not _fill_survives_as_polygon_clip(node):
            cg = node.custom_geom
            left = _px(node.box.x)
            top = _px(node.box.y)
            w_px = _number(emu_to_px(node.box.width))
            h_px = _number(emu_to_px(node.box.height))
            pos_style = (
                f"position:absolute;left:{left};top:{top};"
                f"width:{w_px}px;height:{h_px}px;overflow:visible"
            )
            transform_css = _transform_css(node.transform)
            if transform_css is not None:
                pos_style += f";transform:{transform_css}"
            effect_filter = (
                _custom_geometry_filter(node, warnings) if node.portable_fallback is None else None
            )
            if effect_filter is not None:
                pos_style += f";filter:{effect_filter}"
            vb_w = cg.width_emu
            vb_h = cg.height_emu
            d = commands_to_svg_d(cg.path)
            gradient_defs = ""
            # Fill attribute
            if isinstance(node.fill, SolidFill):
                fill_attr = (
                    f'fill="rgba({node.fill.color.r},{node.fill.color.g},'
                    f'{node.fill.color.b},{_number(node.fill.color.a * node.opacity)})"'
                )
            elif isinstance(node.fill, GradientFill) and (
                paint := _svg_gradient(node.fill, node.opacity, node.box, cg)
            ):
                gradient_defs, fill_attr = paint
            else:
                fill_attr = 'fill="none"'
            # Stroke attributes
            stroke_attrs = ""
            if node.line is not None:
                line = node.line
                stroke_w_px = _number(emu_to_px(line.width_emu))
                stroke_px = emu_to_px(line.width_emu)
                dash_lengths = (
                    tuple(length * stroke_px for length in line.custom_dash)
                    if line.custom_dash
                    else svg_dash_lengths(line.dash, stroke_px)
                )
                dash_attr = (
                    ' stroke-dasharray="'
                    + " ".join(_number(length) for length in dash_lengths)
                    + '"'
                    if dash_lengths
                    else ""
                )
                cap = "butt" if line.cap == "flat" else line.cap
                stroke_attrs = (
                    f' stroke="rgba({line.color.r},{line.color.g},{line.color.b},'
                    f'{_number(line.color.a)})"'
                    f' stroke-width="{stroke_w_px}"'
                    f'{dash_attr} stroke-linecap="{cap}" stroke-linejoin="{line.join}"'
                    ' vector-effect="non-scaling-stroke"'
                )
            fallback_attrs = ""
            fallback_layer = ""
            path_visibility = ""
            if node.portable_fallback is not None:
                fallback = node.portable_fallback
                asset = _asset(fallback.picture)
                assets.setdefault(asset.path, asset)
                fallback_attrs = (
                    ' data-domoxml-raster-bounds="'
                    f"{_number(emu_to_px(fallback.box.x))} "
                    f"{_number(emu_to_px(fallback.box.y))} "
                    f"{_number(emu_to_px(fallback.box.width))} "
                    f'{_number(emu_to_px(fallback.box.height))}"'
                )
                fallback_x = (
                    (fallback.box.x - node.box.x) / node.box.width * vb_w if node.box.width else 0
                )
                fallback_y = (
                    (fallback.box.y - node.box.y) / node.box.height * vb_h if node.box.height else 0
                )
                fallback_width = (
                    fallback.box.width / node.box.width * vb_w if node.box.width else vb_w
                )
                fallback_height = (
                    fallback.box.height / node.box.height * vb_h if node.box.height else vb_h
                )
                fallback_layer = (
                    '<image data-domoxml-render-layer="true" '
                    f'href="../{escape(asset.path, quote=True)}" '
                    f'x="{_number(fallback_x)}" y="{_number(fallback_y)}" '
                    f'width="{_number(fallback_width)}" height="{_number(fallback_height)}" '
                    'preserveAspectRatio="none"/>'
                )
                path_visibility = ' opacity="0"'
                warnings.append(
                    ConversionWarning(
                        message=(
                            "custom geometry displayed with its exact portable effect layer; "
                            "native path and typed effect intent retained"
                        ),
                        element=node.node_id or "custom-geometry",
                    )
                )
            inner = (
                f'<svg xmlns="http://www.w3.org/2000/svg"{_identity_attrs(node)}'
                f"{_custom_geometry_attrs(cg)}{_effect_attrs(node)}"
                f"{fallback_attrs}"
                f' viewBox="0 0 {vb_w} {vb_h}"'
                f' style="{escape(pos_style, quote=True)}">'
                f"{fallback_layer}{gradient_defs}"
                f'<path d="{escape(d, quote=True)}" {fill_attr}{stroke_attrs}'
                f"{path_visibility}/>"
                f"</svg>"
            )
            if node.text is not None and node.portable_fallback is None:
                inner += _text_layer_html(node, warnings)
            return inner
        # Merge text body CSS (flex anchor, columns) into the shape style.
        body_css = _text_body_css(
            node.text, warnings, node.line.width_emu if node.line is not None else 0
        )
        shape_style = _shape_style(node, assets, warnings)
        combined_style = (shape_style + ";" + body_css) if body_css else shape_style
        # Autofit metadata attribute when autofit != "normal" (the default).
        autofit_attr = ""
        if node.text is not None and node.text.autofit != "normal":
            autofit_attr = f' data-domoxml-autofit="{escape(node.text.autofit, quote=True)}"'
        text_body_attr = ' data-domoxml-text-body="true"' if _plain_text_body(node.text) else ""
        # Decorative-raster marker round-trips via data-domoxml-raster so a re-compile is stable.
        raster_attr = ""
        if isinstance(node.fill, PictureFill) and node.fill.raster_role is not None:
            raster_attr = f' data-domoxml-raster="{escape(node.fill.raster_role, quote=True)}"'
        fill_layer = ""
        if (
            isinstance(node.fill, PictureFill | PatternFill)
            and node.opacity < 1.0
            and _fill_layer_needed(node)
        ):
            combined_style, fill_layer = _faded_fill_layer(combined_style, node.opacity)
        style = escape(combined_style, quote=True)
        metadata_attrs = _identity_attrs(node) + _effect_attrs(node) + _text_payload_attrs(node)
        reflection_attrs, reflection_layer = _blurred_reflection_layer(node, assets)
        text_html = fill_layer + _text_html(node.text, warnings)
        flipped = node.transform is not None and node.transform.flip_h
        if text_html and flipped != (node.text is not None and node.text.mirror_x):
            # CSS mirrors the element's text with the element; PowerPoint does not, unless the
            # text body says so. Turn it back so the text reads as it does in the deck.
            text_html = f'<div style="transform:scaleX(-1)">{text_html}</div>'
        inner = (
            f'<div class="domoxml-shape"{metadata_attrs} style="{style}"'
            f"{autofit_attr}{text_body_attr}{raster_attr}{reflection_attrs}>"
            f"{text_html}{reflection_layer}</div>"
        )
        return inner
    if isinstance(node, GroupNode):
        return _group_html(node, assets, warnings)
    if isinstance(node, MediaNode):
        return _media_html(node, assets, warnings)
    if isinstance(node, Connector):
        return _connector_html(node, warnings)
    if isinstance(node, TableNode):
        return _table_html(node, assets, warnings)
    payload = escape(encode_payload(node.payload), quote=True)
    base = (
        f"position:absolute;left:{_px(node.box.x)};top:{_px(node.box.y)};"
        f"width:{_px(node.box.width)};height:{_px(node.box.height)};"
    )
    hidden = "" if node.alt_text else ' aria-hidden="true"'
    metadata = (
        f'class="domoxml-preserved"{_identity_attrs(node)}{hidden} '
        f'data-domoxml-preserved-payload="{payload}"'
    )
    if node.fallback is not None:
        asset = _asset(node.fallback)
        assets.setdefault(asset.path, asset)
        representation = node.fallback_representation.replace("_", "-")
        return (
            f'<img {metadata} data-domoxml-representation="{representation}" '
            f'src="../{asset.path}" alt="{escape(node.alt_text or "", quote=True)}" '
            f'style="{base}object-fit:fill"/>'
        )
    return f'<div {metadata} style="{base}opacity:0;pointer-events:none;overflow:hidden"></div>'


_ARROW_LENGTH = {"sm": 3, "med": 4, "lg": 6}
_ARROW_WIDTH = {"sm": 2, "med": 3, "lg": 5}


def _connector_html(node: Connector, warnings: list[ConversionWarning]) -> str:
    """Serialize a ``p:cxnSp`` connector to an absolutely-positioned ``<svg>`` element.

    The SVG's bounding box covers start→end (or the convex hull for bent/curved).  Straight
    connectors emit ``<line>``; bent connectors approximate with an L-shaped ``<path>``; curved
    connectors use a quadratic Bézier approximation.  Arrowheads on ``line.head``/``line.tail``
    are rendered as SVG ``<marker>`` elements.
    """
    line = node.line
    color_css = f"rgba({line.color.r},{line.color.g},{line.color.b},{_number(line.color.a)})"
    stroke_w_px = emu_to_px(line.width_emu)

    # Convert endpoints to px.
    sx = emu_to_px(node.start.x)
    sy = emu_to_px(node.start.y)
    ex = emu_to_px(node.end.x)
    ey = emu_to_px(node.end.y)

    # Bounding box in px (with a small padding so strokes at the edge are not clipped).
    pad = max(stroke_w_px * 2, 4.0)
    min_x = min(sx, ex) - pad
    min_y = min(sy, ey) - pad
    max_x = max(sx, ex) + pad
    max_y = max(sy, ey) + pad
    svg_w = max_x - min_x
    svg_h = max_y - min_y

    # Translate start/end into SVG-local coordinates.
    lsx = sx - min_x
    lsy = sy - min_y
    lex = ex - min_x
    ley = ey - min_y

    pos_style = (
        f"position:absolute;left:{_number(min_x)}px;top:{_number(min_y)}px;"
        f"width:{_number(svg_w)}px;height:{_number(svg_h)}px;overflow:visible"
    )
    connector_payload = escape(node.model_dump_json(exclude={"node_id", "provenance"}), quote=True)

    # Build arrowhead markers.
    defs = ""
    marker_ids: dict[str, str] = {}  # "head" / "tail" → id string
    for end_name, arrow in (("head", line.head), ("tail", line.tail)):
        if arrow is None or arrow.type == "none":
            continue
        mid = (
            f"arr-{end_name}-{line.color.r:02x}{line.color.g:02x}{line.color.b:02x}"
            f"-{arrow.length}-{arrow.width}"
        )
        marker_ids[end_name] = mid
        # Simple filled triangle — points chosen for a clean arrow shape.
        orient = "auto-start-reverse" if end_name == "head" else "auto"
        # PowerPoint sizes a head in line widths; the id carries what makes two heads differ,
        # because every SVG on a slide shares one id space.
        length = _ARROW_LENGTH[arrow.length]
        breadth = _ARROW_WIDTH[arrow.width]
        defs += (
            f'<defs><marker id="{mid}" markerUnits="strokeWidth" viewBox="0 0 10 7" '
            f'preserveAspectRatio="none" markerWidth="{length}" markerHeight="{breadth}" '
            f'refX="10" refY="3.5" orient="{orient}">'
            f'<polygon points="0 0, 10 3.5, 0 7" fill="{color_css}"/>'
            f"</marker></defs>"
        )

    marker_start_attr = (
        f' marker-start="url(#{marker_ids["head"]})"' if "head" in marker_ids else ""
    )
    marker_end_attr = f' marker-end="url(#{marker_ids["tail"]})"' if "tail" in marker_ids else ""
    stroke_attrs = (
        f'stroke="{color_css}" stroke-width="{_number(stroke_w_px)}"'
        f"{marker_start_attr}{marker_end_attr}"
    )

    if node.kind == "straight":
        shape_el = (
            f'<line x1="{_number(lsx)}" y1="{_number(lsy)}"'
            f' x2="{_number(lex)}" y2="{_number(ley)}"'
            f' {stroke_attrs} fill="none"/>'
        )
    elif node.kind == "bent":
        # Three segments with the middle one halfway between the ends, like bentConnector3.
        if node.vertical_first:
            mid = lsy + (ley - lsy) * node.elbow
            points = [(lsx, lsy), (lsx, mid), (lex, mid), (lex, ley)]
        else:
            mid = lsx + (lex - lsx) * node.elbow
            points = [(lsx, lsy), (mid, lsy), (mid, ley), (lex, ley)]
        d = "M " + " L ".join(f"{_number(px)} {_number(py)}" for px, py in points)
        shape_el = f'<path d="{escape(d, quote=True)}" {stroke_attrs} fill="none"/>'
    else:
        # curvedConnector3: two curves meeting at the middle, tangent to the leaving direction.
        dx, dy = lex - lsx, ley - lsy
        turn = node.elbow
        if node.vertical_first:
            across = lsy + dy * turn
            way = [
                (lsx, lsy + dy * turn / 2),
                (lsx + dx / 4, across),
                (lsx + dx / 2, across),
                (lsx + 3 * dx / 4, across),
                (lex, lsy + dy * (1 + turn) / 2),
            ]
        else:
            across = lsx + dx * turn
            way = [
                (lsx + dx * turn / 2, lsy),
                (across, lsy + dy / 4),
                (across, lsy + dy / 2),
                (across, lsy + 3 * dy / 4),
                (lsx + dx * (1 + turn) / 2, ley),
            ]
        pt = [f"{_number(px)} {_number(py)}" for px, py in way]
        d = (
            f"M {_number(lsx)} {_number(lsy)} C {pt[0]}, {pt[1]}, {pt[2]}"
            f" C {pt[3]}, {pt[4]}, {_number(lex)} {_number(ley)}"
        )
        shape_el = f'<path d="{escape(d, quote=True)}" {stroke_attrs} fill="none"/>'

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"{_identity_attrs(node)}'
        f' data-domoxml-connector="{connector_payload}"'
        f' style="{escape(pos_style, quote=True)}">'
        f"{defs}{shape_el}</svg>"
    )


def _media_html(
    node: MediaNode, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]
) -> str:
    """Serialize a recovered video/audio ``p:pic`` as a positioned ``<video>``/``<audio>``.

    Embedded media becomes a shared asset; external media uses its URL. The poster blip (if
    any) is the ``poster`` for video. Play settings (``p:videoPr``) are preserved out-of-band,
    so a warning records that they don't survive to CSS/HTML."""
    pos = (
        f"position:absolute;left:{_px(node.box.x)};top:{_px(node.box.y)};"
        f"width:{_px(node.box.width)};height:{_px(node.box.height)}"
    )
    # Resolve the media source: embedded → shared asset; external → URL.
    src = ""
    if node.media_data is not None and node.kind != "model":
        digest = hashlib.sha256(node.media_data).hexdigest()[:16]
        asset = HtmlAsset(path=f"assets/{digest}.{node.media_ext}", data=node.media_data)
        assets.setdefault(asset.path, asset)
        src = asset.path
    elif node.media_url is not None:
        src = node.media_url
    src_attr = f' src="{escape(src, quote=True)}"' if src else ""
    if node.play_settings_xml is not None:
        warnings.append(
            ConversionWarning(
                message=f"{node.kind} play settings (p:{node.kind}Pr) preserved out-of-band; "
                "not represented in HTML/CSS"
            )
        )
    if node.kind == "model" and node.media_data is not None:
        # A 3-D model comes back as the viewer element it was authored as.
        encoded = base64.b64encode(node.media_data).decode()
        poster_attr = ""
        if node.poster_fill is not None:
            poster = _asset(node.poster_fill)
            assets.setdefault(poster.path, poster)
            poster_attr = f' poster="{escape(poster.path, quote=True)}"'
            # An undefined element ignores ``poster``: paint it so the page shows the model's look.
            pos += f";background:url({poster.path}) center/cover no-repeat"
        return (
            f"<model-viewer camera-controls{_identity_attrs(node)} "
            f'style="{escape(pos, quote=True)}" '
            f'src="data:model/gltf-binary;base64,{encoded}"{poster_attr}></model-viewer>'
        )
    if node.kind == "web" and node.media_url is not None:
        # A Web Viewer frame is a live page; it comes back as the iframe it started as.
        return (
            f'<iframe{_identity_attrs(node)} style="{escape(pos, quote=True)};border:0"'
            f"{src_attr}></iframe>"
        )
    if node.media_url is not None and online_video_url(node.media_url) is not None:
        # An online player is a page, not a file: it comes back as the embed it started as.
        return (
            f'<iframe{_identity_attrs(node)} style="{escape(pos, quote=True)};border:0"'
            f"{src_attr} allowfullscreen></iframe>"
        )
    if node.kind == "audio":
        return (
            f'<audio controls{_identity_attrs(node)} style="{escape(pos, quote=True)}"'
            f"{src_attr}></audio>"
        )
    poster_attr = ""
    if node.poster_fill is not None:
        poster = _asset(node.poster_fill)
        assets.setdefault(poster.path, poster)
        poster_attr = f' poster="{escape(poster.path, quote=True)}"'
    return (
        f'<video controls{_identity_attrs(node)} style="{escape(pos, quote=True)}"'
        f"{src_attr}{poster_attr}></video>"
    )


def _slide_notes_attr(notes: str | None) -> str:
    """The ``data-notes`` attribute carrying a slide's speaker notes, or an empty string."""
    return f' data-notes="{escape(notes, quote=True)}"' if notes else ""


def _slide_transition_attrs(transition: SlideTransition | None) -> str:
    """Return HTML data attribute string for the slide root element's transition."""
    if transition is None or transition.type == "none":
        return ""
    attrs = f' data-transition="{transition.type}"'
    if transition.duration_ms is not None:
        attrs += f' data-transition-duration="{transition.duration_ms}"'
    if transition.direction is not None:
        attrs += f' data-transition-direction="{transition.direction}"'
    return attrs


def _slide_background_css(background: SlideBackground | None, assets: dict[str, HtmlAsset]) -> str:
    """Return a CSS background declaration for the slide root element, or empty string."""
    if background is None:
        return ""
    fill = background.fill
    if isinstance(fill, SolidFill):
        return f"background-color:{_rgba(fill.color)}"
    if isinstance(fill, GradientFill):
        return f"background-image:{_gradient(fill, opacity=1.0)}"
    if isinstance(fill, PictureFill):
        asset = _asset(fill)
        assets.setdefault(asset.path, asset)
        return f"background-image:url(../{asset.path});background-size:cover"
    else:  # PatternFill
        fg_hex = _color_spec_hex(fill.fg)
        bg_hex = _color_spec_hex(fill.bg)
        prop, value, _approx = pattern_to_css(fg_hex, bg_hex, fill.preset)
        return f"{prop}:{value}"


def _slide_renderer_fallback_html(
    slide: SlideIR,
    assets: dict[str, HtmlAsset],
) -> str:
    """Serialize one authoritative full-slide renderer fallback above retained native contents."""
    fallback = slide.renderer_fallback
    if fallback is None:
        return ""
    asset = _asset(fallback)
    assets.setdefault(asset.path, asset)
    style = (
        "position:absolute;left:0;top:0;width:100%;height:100%;object-fit:fill;"
        "z-index:2147483647;pointer-events:none"
    )
    owner_attr = ""
    if slide.renderer_fallback_owner_node_id is not None:
        owner_id = escape(slide.renderer_fallback_owner_node_id, quote=True)
        owner_attr = f' data-domoxml-owner-node-id="{owner_id}"'
    return (
        '<img class="domoxml-slide-fallback" data-domoxml-slide-fallback="rasterized" '
        f'src="../{asset.path}" alt="" aria-hidden="true"{owner_attr} style="{style}"/>'
    )


def serialize_canvas(
    slides: list[SlideIR],
    *,
    warnings: tuple[ConversionWarning, ...] = (),
    preserved: tuple[PreservedFragment, ...] = (),
    embedded_fonts: tuple[ReverseFontFace, ...] = (),
    coverage: CoverageReport | None = None,
) -> HtmlPresentation:
    """Serialize canvas IR to one stable HTML fragment per slide plus shared assets."""
    assets: dict[str, HtmlAsset] = {}
    html_slides: list[HtmlSlide] = []
    emitted_warnings: list[ConversionWarning] = list(warnings)
    for slide in slides:
        # The animations on a node serialise with that node.
        grouped: dict[str, list[tuple[int, Animation]]] = {}
        for position, animation in enumerate(slide.animations):
            grouped.setdefault(animation.target, []).append((position, animation))
        by_node = {target: tuple(found) for target, found in grouped.items()}
        token = _ANIMATIONS.set(by_node)
        try:
            shapes = "".join(_node_html(node, assets, emitted_warnings) for node in slide.contents)
        finally:
            _ANIMATIONS.reset(token)
        shapes += _slide_renderer_fallback_html(slide, assets)
        width_px = round(emu_to_px(slide.width))
        height_px = round(emu_to_px(slide.height))
        transition_attrs = _slide_transition_attrs(slide.transition) + _slide_notes_attr(
            slide.notes
        )
        bg_css = _slide_background_css(slide.background, assets)
        base_style = f"{_SLIDE_BASE_STYLE};width:{width_px}px;height:{height_px}px"
        slide_style = f"{base_style};{bg_css}" if bg_css else base_style
        html = f'<div class="domoxml-slide"{transition_attrs} style="{slide_style}">{shapes}</div>'
        html_slides.append(HtmlSlide(html=html, width_px=width_px, height_px=height_px))

    # Emit embedded font faces as assets and @font-face CSS rules.
    for face in embedded_fonts:
        asset_path = f"assets/fonts/{font_asset_name(face)}"
        assets.setdefault(asset_path, HtmlAsset(path=asset_path, data=face.data))
    css = font_face_css(list(embedded_fonts))

    return HtmlPresentation(
        slides=tuple(html_slides),
        css=css,
        assets=tuple(assets.values()),
        warnings=tuple(emitted_warnings),
        preserved=preserved,
        coverage=coverage or CoverageReport(items=()),
    )
