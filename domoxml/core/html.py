"""Serialize PowerPoint canvas IR to deterministic browser-renderable HTML/CSS."""

from __future__ import annotations

import hashlib
import math
from html import escape

from domoxml.core.drawingml.presets import preset_defaults, preset_vertices
from domoxml.core.fillcrop import srcrect_to_background
from domoxml.core.fontsread import ReverseFontFace, font_asset_name, font_face_css
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Blur,
    CharBullet,
    ColorSpec,
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
    TextParagraph,
    TextRun,
    ThemeColorRef,
)
from domoxml.core.ir.parse import autonum_to_css_list_style, bu_char_to_css_list_style
from domoxml.core.ir.pattern import pattern_to_css
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
    fill_uses_opacity = isinstance(node.fill, PictureFill | PatternFill) or node.fill is None
    if fill_uses_opacity and node.opacity < 1.0:
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


def _text_body_css(body: TextBody | None, warnings: list[ConversionWarning]) -> str:
    """Return inline CSS for text body container (vertical anchor, columns).

    Emits flex properties for non-top anchors; column CSS for multi-column bodies.
    Returns an empty string when no special properties are needed.
    """
    if body is None:
        return ""
    styles: list[str] = []
    if body.anchor == "middle":
        styles.extend(["display:flex", "flex-direction:column", "justify-content:center"])
    elif body.anchor == "bottom":
        styles.extend(["display:flex", "flex-direction:column", "justify-content:flex-end"])
    if body.columns > 1:
        styles.append(f"column-count:{body.columns}")
        if body.column_gap_emu > 0:
            styles.append(f"column-gap:{_px(body.column_gap_emu)}")
    return ";".join(styles)


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
        # Merge text body CSS (flex anchor, columns) into the shape style.
        body_css = _text_body_css(node.text, warnings)
        shape_style = _shape_style(node, assets, warnings)
        combined_style = (shape_style + ";" + body_css) if body_css else shape_style
        # Autofit metadata attribute when autofit != "normal" (the default).
        autofit_attr = ""
        if node.text is not None and node.text.autofit != "normal":
            autofit_attr = f' data-domoxml-autofit="{escape(node.text.autofit, quote=True)}"'
        style = escape(combined_style, quote=True)
        inner = (
            f'<div class="domoxml-shape" style="{style}"{autofit_attr}>'
            f"{_text_html(node.text, warnings)}</div>"
        )
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
                f"{_text_html(node.text, warnings)}</div>"
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
