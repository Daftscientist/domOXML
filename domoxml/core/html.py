"""Serialize PowerPoint canvas IR to deterministic browser-renderable HTML/CSS."""

from __future__ import annotations

import hashlib
import math
from html import escape

from domoxml.core.ir.model import (
    Blur,
    Glow,
    GradientFill,
    Node,
    PatternFill,
    PictureFill,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SoftEdge,
    SolidFill,
    TextBody,
    TextRun,
)
from domoxml.core.units import emu_to_px
from domoxml.types import (
    ConversionWarning,
    HtmlAsset,
    HtmlPresentation,
    HtmlSlide,
    PreservedFragment,
)

_SHARED_CSS = (
    ".domoxml-slide{position:relative;overflow:hidden;box-sizing:border-box}"
    ".domoxml-shape{position:absolute;box-sizing:border-box}"
    ".domoxml-text{white-space:pre-wrap}"
)
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


def _number(value: float) -> str:
    """Stable compact decimal representation for emitted CSS."""
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _px(value: int) -> str:
    return f"{_number(emu_to_px(value))}px"


def _rgba(color: Rgba, *, opacity: float = 1.0) -> str:
    alpha = color.a * opacity
    return f"rgba({color.r},{color.g},{color.b},{_number(alpha)})"


def _asset(fill: PictureFill) -> HtmlAsset:
    digest = hashlib.sha256(fill.data).hexdigest()[:16]
    return HtmlAsset(path=f"assets/{digest}.{fill.ext}", data=fill.data)


def _gradient(fill: GradientFill, *, opacity: float) -> str:
    stops = ",".join(
        f"{_rgba(stop.color, opacity=opacity)} {_number(stop.pos * 100)}%" for stop in fill.stops
    )
    if fill.radial:
        return f"radial-gradient(circle,{stops})"
    return f"linear-gradient({_number(fill.angle_deg)}deg,{stops})"


def _shape_style(
    node: ShapeNode, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]
) -> str:
    styles = [
        f"left:{_px(node.box.x)}",
        f"top:{_px(node.box.y)}",
        f"width:{_px(node.box.width)}",
        f"height:{_px(node.box.height)}",
    ]
    if isinstance(node.fill, SolidFill):
        styles.append(f"background-color:{_rgba(node.fill.color, opacity=node.opacity)}")
    elif isinstance(node.fill, GradientFill):
        styles.append(f"background-image:{_gradient(node.fill, opacity=node.opacity)}")
    elif isinstance(node.fill, PictureFill):
        asset = _asset(node.fill)
        assets.setdefault(asset.path, asset)
        styles.extend((f"background-image:url(../{asset.path})", "background-size:100% 100%"))
    elif isinstance(node.fill, PatternFill):
        # TODO(coverage): map a:pattFill to a repeating CSS background. No native CSS source
        # yet, so warn rather than silently drop the fill (no-silent-drop policy).
        warnings.append(
            ConversionWarning(message="pattern fill not yet serialized to HTML; fill dropped")
        )
    fill_uses_opacity = isinstance(node.fill, PictureFill | PatternFill) or node.fill is None
    if fill_uses_opacity and node.opacity < 1.0:
        styles.append(f"opacity:{_number(node.opacity)}")
    if node.line is not None:
        styles.append(
            f"border:{_px(node.line.width_emu)} {_CSS_DASH[node.line.dash]} "
            f"{_rgba(node.line.color)}"
        )
    if node.geom == "ellipse":
        styles.append("border-radius:50%")
    elif node.geom == "roundRect" and node.corner_radius_emu > 0:
        styles.append(f"border-radius:{_px(node.corner_radius_emu)}")
    # Emit effects
    _append_effect_styles(node, styles, warnings)
    return ";".join(styles)


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
            spread_px = emu_to_px(effect.spread_emu) if effect.spread_emu else 0.0
            inset_kw = " inset" if effect.inset else ""
            box_shadows.append(
                f"{_number(offset_x)}px {_number(offset_y)}px "
                f"{_px(effect.blur_emu)} {_number(spread_px)}px "
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
        elif isinstance(effect, Blur):
            blur_filters.append(f"blur({_number(emu_to_px(effect.radius_emu))}px)")
            warnings.append(
                ConversionWarning(
                    message="a:blur mapped to CSS filter:blur() — forward round-trip will rasterise"
                )
            )
        elif isinstance(effect, SoftEdge):
            # Approximate softEdge as a CSS mask with an inset radial gradient.
            # The gradient fades from opaque at (radius) inset to transparent at the edge.
            rad_px = _number(emu_to_px(effect.radius_emu))
            soft_edge_masks.append(
                f"radial-gradient(ellipse calc(100% - {rad_px}px) calc(100% - {rad_px}px) "
                f"at 50% 50%, black calc(100% - {rad_px}px), transparent 100%)"
            )
        else:
            # Reflection is handled in _node_html; skip in style accumulation.
            pass

    if box_shadows:
        styles.append(f"box-shadow:{','.join(box_shadows)}")
    if blur_filters:
        styles.append(f"filter:{' '.join(blur_filters)}")
    if soft_edge_masks:
        styles.append(f"mask-image:{','.join(soft_edge_masks)}")
        styles.append("-webkit-mask-image:" + ",".join(soft_edge_masks))


def _run_html(run: TextRun) -> str:
    styles = [
        f"font-family:{run.font_family}",
        f"font-size:{_number(run.size_pt)}pt",
        f"font-weight:{'700' if run.bold else '400'}",
        f"font-style:{'italic' if run.italic else 'normal'}",
        f"color:{_rgba(run.color)}",
    ]
    return f'<span style="{escape(";".join(styles), quote=True)}">{escape(run.text)}</span>'


def _text_html(body: TextBody | None) -> str:
    if body is None:
        return ""
    paragraphs = "".join(
        f'<div class="domoxml-text" style="text-align:{paragraph.align}">'
        f"{''.join(_run_html(run) for run in paragraph.runs)}</div>"
        for paragraph in body.paragraphs
    )
    return paragraphs


def _node_html(node: Node, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]) -> str:
    """Serialize one slide node. Only :class:`ShapeNode` has an HTML mapping today; groups,
    connectors, and tables warn and emit nothing rather than drop silently."""
    if isinstance(node, ShapeNode):
        style = escape(_shape_style(node, assets, warnings), quote=True)
        inner = f'<div class="domoxml-shape" style="{style}">{_text_html(node.text)}</div>'
        # Wrap with reflection if present
        reflections = [e for e in node.effects if isinstance(e, Reflection)]
        if reflections:
            ref = reflections[0]
            dist_px = _number(emu_to_px(ref.distance_emu))
            # Build a gradient mask for the reflection fade
            grad = (
                f"linear-gradient(to bottom, "
                f"rgba(0,0,0,{_number(ref.start_alpha)}) 0%, "
                f"rgba(0,0,0,{_number(ref.end_alpha)}) 100%)"
            )
            reflect_style = (
                f"-webkit-box-reflect:below {dist_px}px {grad};box-reflect:below {dist_px}px {grad}"
            )
            warnings.append(
                ConversionWarning(
                    message="a:reflection approximated as -webkit-box-reflect; "
                    "support is WebKit/Blink only — forward round-trip will rasterise"
                )
            )
            # Wrap so the reflect doesn't escape the slide bounds
            w = _px(node.box.width)
            h = _px(node.box.height)
            left = _px(node.box.x)
            top = _px(node.box.y)
            return (
                f'<div class="domoxml-shape" '
                f'style="left:{left};top:{top};width:{w};height:{h};'
                f'{reflect_style}">'
                f"{_text_html(node.text)}</div>"
            )
        return inner
    # TODO(coverage): GroupNode/Connector/TableNode have no HTML serializer yet. The extractor
    # never produces them today; warn (no-silent-drop) when one reaches here.
    kind = type(node).__name__
    warnings.append(ConversionWarning(message=f"{kind} not yet serialized to HTML; node dropped"))
    return ""


def serialize_canvas(
    slides: list[SlideIR],
    *,
    warnings: tuple[ConversionWarning, ...] = (),
    preserved: tuple[PreservedFragment, ...] = (),
) -> HtmlPresentation:
    """Serialize canvas IR to one stable HTML fragment per slide plus shared assets."""
    assets: dict[str, HtmlAsset] = {}
    html_slides: list[HtmlSlide] = []
    emitted_warnings: list[ConversionWarning] = list(warnings)
    for slide in slides:
        shapes = "".join(
            _node_html(node, assets, emitted_warnings) for node in (*slide.shapes, *slide.nodes)
        )
        width_px = round(emu_to_px(slide.width))
        height_px = round(emu_to_px(slide.height))
        html = (
            f'<div class="domoxml-slide" style="width:{width_px}px;height:{height_px}px">'
            f"{shapes}</div>"
        )
        html_slides.append(HtmlSlide(html=html, width_px=width_px, height_px=height_px))
    return HtmlPresentation(
        slides=tuple(html_slides),
        css=_SHARED_CSS,
        assets=tuple(assets.values()),
        warnings=tuple(emitted_warnings),
        preserved=preserved,
    )
