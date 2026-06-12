"""Serialize PowerPoint canvas IR to deterministic browser-renderable HTML/CSS."""

from __future__ import annotations

import hashlib
import math
from html import escape

from domoxml.core.fontsread import ReverseFontFace, font_asset_name, font_face_css
from domoxml.core.ir.model import (
    GradientFill,
    Node,
    PatternFill,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
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
    if node.shadow is not None:
        radians = math.radians(node.shadow.direction_deg)
        offset_x = emu_to_px(round(math.cos(radians) * node.shadow.distance_emu))
        offset_y = emu_to_px(round(math.sin(radians) * node.shadow.distance_emu))
        styles.append(
            "box-shadow:"
            f"{_number(offset_x)}px {_number(offset_y)}px {_px(node.shadow.blur_emu)} "
            f"{_rgba(node.shadow.color)}"
            f"{' inset' if node.shadow.inset else ''}"
        )
    return ";".join(styles)


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
        return f'<div class="domoxml-shape" style="{style}">{_text_html(node.text)}</div>'
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
    embedded_fonts: tuple[ReverseFontFace, ...] = (),
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

    # Emit embedded font faces as assets and @font-face CSS rules.
    for face in embedded_fonts:
        asset_path = f"assets/fonts/{font_asset_name(face)}"
        assets.setdefault(asset_path, HtmlAsset(path=asset_path, data=face.data))
    css = _SHARED_CSS + font_face_css(list(embedded_fonts))

    return HtmlPresentation(
        slides=tuple(html_slides),
        css=css,
        assets=tuple(assets.values()),
        warnings=tuple(emitted_warnings),
        preserved=preserved,
    )
