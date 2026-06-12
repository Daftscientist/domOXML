"""Serialize PowerPoint canvas IR to deterministic browser-renderable HTML/CSS."""

from __future__ import annotations

import hashlib
import math
from html import escape

from domoxml.core.fontsread import ReverseFontFace, font_asset_name, font_face_css
from domoxml.core.ir.model import (
    AutoNumberBullet,
    CharBullet,
    GradientFill,
    Node,
    PatternFill,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.ir.parse import autonum_to_css_list_style, bu_char_to_css_list_style
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


def _decoration_css(run: TextRun) -> str | None:
    """``text-decoration-line`` for the run (underline and/or line-through), or ``None``."""
    lines: list[str] = []
    if run.underline is not False:
        lines.append("underline")
    if run.strike:
        lines.append("line-through")
    return " ".join(lines) if lines else None


def _run_html(run: TextRun) -> str:
    styles = [
        f"font-family:{run.font_family}",
        f"font-size:{_number(run.size_pt)}pt",
        f"font-weight:{'700' if run.bold else '400'}",
        f"font-style:{'italic' if run.italic else 'normal'}",
        f"color:{_rgba(run.color)}",
    ]
    decoration = _decoration_css(run)
    if decoration is not None:
        styles.append(f"text-decoration-line:{decoration}")
    if run.caps == "all":
        styles.append("text-transform:uppercase")
    elif run.caps == "small":
        styles.append("font-variant-caps:small-caps")
    if run.letter_spacing_pt:
        styles.append(f"letter-spacing:{_number(run.letter_spacing_pt)}pt")
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
    else:
        return inner
    return f'<a href="{escape(href, quote=True)}">{inner}</a>'


def _para_spacing_style(paragraph: TextParagraph) -> str:
    """Return inline CSS for paragraph-level spacing/indent (no trailing semicolon)."""
    styles: list[str] = []
    if paragraph.line_spacing is not None:
        ls = paragraph.line_spacing
        if ls.percent is not None:
            styles.append(f"line-height:{_number(ls.percent)}")
        elif ls.points is not None:
            styles.append(f"line-height:{_number(ls.points)}pt")
    if paragraph.space_before_pt:
        styles.append(f"margin-top:{_number(paragraph.space_before_pt)}pt")
    if paragraph.space_after_pt:
        styles.append(f"margin-bottom:{_number(paragraph.space_after_pt)}pt")
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


def _text_html(body: TextBody | None) -> str:
    """Serialize text body to HTML. Consecutive bulleted paragraphs at the same level
    become nested ``<ul>``/``<ol>`` elements; plain paragraphs become ``<div>``."""
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
                result.append(
                    f'<{list_tag} style="list-style-type:{escape(list_style, quote=True)}"'
                    f"{start_attr}>"
                )
                open_lists.append((list_tag, target_level))

            # Emit the <li>
            spacing_style = _para_spacing_style(paragraph)
            li_style = f"text-align:{paragraph.align}"
            if spacing_style:
                li_style += ";" + spacing_style
            runs_html = "".join(_run_html(run) for run in paragraph.runs)
            result.append(f'<li style="{escape(li_style, quote=True)}">{runs_html}</li>')
        else:
            # Plain paragraph — close all open lists first.
            _close_all_lists()
            spacing_style = _para_spacing_style(paragraph)
            div_style = f"text-align:{paragraph.align}"
            if spacing_style:
                div_style += ";" + spacing_style
            runs_html = "".join(_run_html(run) for run in paragraph.runs)
            result.append(
                f'<div class="domoxml-text" style="{escape(div_style, quote=True)}">'
                f"{runs_html}</div>"
            )

    _close_all_lists()
    return "".join(result)


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
