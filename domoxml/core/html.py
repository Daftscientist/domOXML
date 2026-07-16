"""Serialize PowerPoint canvas IR to deterministic browser-renderable HTML/CSS."""

from __future__ import annotations

import hashlib
import math
from html import escape
from urllib.parse import urlsplit

from domoxml.core.drawingml.presets import preset_defaults, preset_vertices
from domoxml.core.fillcrop import srcrect_to_background
from domoxml.core.fontsread import ReverseFontFace, font_asset_name, font_face_css
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Blur,
    CanvasNode,
    CharBullet,
    ColorSpec,
    Connector,
    Fill,
    Glow,
    GradientFill,
    GroupNode,
    Line,
    MediaNode,
    Node,
    PatternFill,
    PictureFill,
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
from domoxml.core.opc import encode_payload
from domoxml.core.svg_path import commands_to_svg_d
from domoxml.core.svg_stroke import svg_dash_lengths
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
_SAFE_HYPERLINK_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


def _number(value: float) -> str:
    """Stable compact decimal representation for emitted CSS."""
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _px(value: int) -> str:
    return f"{_number(emu_to_px(value))}px"


def _identity_attrs(node: CanvasNode) -> str:
    """HTML data attributes that carry stable IR identity without affecting rendering."""
    attrs: list[tuple[str, str]] = []
    if node.node_id is not None:
        attrs.append(("data-domoxml-node-id", node.node_id))
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
    return "".join(f' {name}="{escape(value, quote=True)}"' for name, value in attrs)


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
    # Emit rotation/flip transform if present.
    transform_css = _transform_css(node.transform)
    if transform_css is not None:
        styles.append(f"transform:{transform_css}")
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
            styles.append(f"line-height:{_number(ls.percent)}")
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
        styles.append("column-fill:auto")
        styles.append(f"column-gap:{_px(body.column_gap_emu)}")
    if any(body.margins):
        left, top, right, bottom = body.margins
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


def _group_html(
    group: GroupNode, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]
) -> str:
    """Flatten a :class:`GroupNode` to HTML.

    OOXML groups define a child coordinate space (``a:chOff``/``a:chExt``) which may differ
    from the group's slide-space extent (``a:off``/``a:ext``).  Each child's position within
    that coordinate space is mapped to absolute slide EMUs using::

        child_slide_x = grp_off_x + (child_x - grp_chOff_x) * scale_x
        child_slide_y = grp_off_y + (child_y - grp_chOff_y) * scale_y
        scale_x       = grp_ext_cx / grp_chExt_cx
        scale_y       = grp_ext_cy / grp_chExt_cy

    The resulting children are emitted as flat positioned ``<div>`` elements (no wrapper div),
    which keeps the HTML simple and consistent with the extractor's flat output.

    Groups with degenerate child extent (zero size) are silently dropped.
    """
    g_off_x = group.box.x
    g_off_y = group.box.y
    g_ext_cx = group.box.width
    g_ext_cy = group.box.height
    ch_off_x = group.child_box.x
    ch_off_y = group.child_box.y
    ch_ext_cx = group.child_box.width
    ch_ext_cy = group.child_box.height

    if ch_ext_cx == 0 or ch_ext_cy == 0:
        warnings.append(ConversionWarning(message="group has zero child extent; children dropped"))
        return ""

    scale_x = g_ext_cx / ch_ext_cx
    scale_y = g_ext_cy / ch_ext_cy

    parts: list[str] = []
    for child in group.children:
        if isinstance(child, (ShapeNode, GroupNode)):
            # Remap child's box from group-child-space to slide space.
            c_box = child.box
            mapped_x = round(g_off_x + (c_box.x - ch_off_x) * scale_x)
            mapped_y = round(g_off_y + (c_box.y - ch_off_y) * scale_y)
            mapped_w = round(c_box.width * scale_x)
            mapped_h = round(c_box.height * scale_y)
            from domoxml.core.ir.model import Box as _Box

            remapped_child = child.model_copy(
                update={"box": _Box(x=mapped_x, y=mapped_y, width=mapped_w, height=mapped_h)}
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
            parts.append(_node_html(remapped_child, assets, warnings))
    return "".join(parts)


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

            # Build cell style.
            cell_styles: list[str] = []
            fill_css = _fill_css(cell.fill)
            if fill_css is not None:
                cell_styles.append(fill_css)
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

            td_style = escape(";".join(cell_styles), quote=True)

            # Span attributes.
            span_attrs = ""
            if cell.col_span > 1:
                span_attrs += f' colspan="{cell.col_span}"'
            if cell.row_span > 1:
                span_attrs += f' rowspan="{cell.row_span}"'

            # Cell content.
            inner = _text_html(cell.text, warnings)
            cells_html += f'<td style="{td_style}"{span_attrs}>{inner}</td>'

            col_cursor += max(1, cell.col_span)

        rows_html += f'<tr style="height:{_px(row.height_emu)}">{cells_html}</tr>'

    return (
        f'<table{_identity_attrs(node)} style="{escape(table_style, quote=True)}">'
        f"{colgroup}"
        f"<tbody>{rows_html}</tbody>"
        f"</table>"
    )


def _node_html(node: Node, assets: dict[str, HtmlAsset], warnings: list[ConversionWarning]) -> str:
    """Serialize one slide node. :class:`ShapeNode`, :class:`MediaNode`, and
    :class:`TableNode` have HTML mappings; others warn and emit nothing."""
    if isinstance(node, ShapeNode):
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
        if node.custom_geom is not None:
            cg = node.custom_geom
            left = _px(node.box.x)
            top = _px(node.box.y)
            w_px = _number(emu_to_px(node.box.width))
            h_px = _number(emu_to_px(node.box.height))
            pos_style = (
                f"position:absolute;left:{left};top:{top};"
                f"width:{w_px}px;height:{h_px}px;overflow:visible"
            )
            vb_w = cg.width_emu
            vb_h = cg.height_emu
            d = commands_to_svg_d(cg.path)
            # Fill attribute
            if isinstance(node.fill, SolidFill):
                fill_attr = (
                    f'fill="rgba({node.fill.color.r},{node.fill.color.g},'
                    f'{node.fill.color.b},{_number(node.fill.color.a * node.opacity)})"'
                )
            else:
                fill_attr = 'fill="none"'
            # Stroke attributes
            stroke_attrs = ""
            if node.line is not None:
                line = node.line
                stroke_w_px = _number(emu_to_px(line.width_emu))
                dash_lengths = svg_dash_lengths(line.dash, emu_to_px(line.width_emu))
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
            inner = (
                f'<svg xmlns="http://www.w3.org/2000/svg"{_identity_attrs(node)}'
                f' viewBox="0 0 {vb_w} {vb_h}"'
                f' style="{escape(pos_style, quote=True)}">'
                f'<path d="{escape(d, quote=True)}" {fill_attr}{stroke_attrs}/>'
                f"</svg>"
            )
            return inner
        # Merge text body CSS (flex anchor, columns) into the shape style.
        body_css = _text_body_css(node.text, warnings)
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
        style = escape(combined_style, quote=True)
        inner = (
            f'<div class="domoxml-shape"{_identity_attrs(node)} style="{style}"'
            f"{autofit_attr}{text_body_attr}{raster_attr}>"
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
                f'<div class="domoxml-shape"{_identity_attrs(node)} '
                f'style="left:{left};top:{top};width:{w};height:{h};'
                f'{reflect_style}">'
                f"{_text_html(node.text, warnings)}</div>"
            )
        return inner
    if isinstance(node, GroupNode):
        return _group_html(node, assets, warnings)
    if isinstance(node, MediaNode):
        return _media_html(node, assets, warnings)
    if isinstance(node, Connector):
        return _connector_html(node, warnings)
    if isinstance(node, TableNode):
        return _table_html(node, warnings)
    payload = escape(encode_payload(node.payload), quote=True)
    style = (
        f"position:absolute;left:{_px(node.box.x)};top:{_px(node.box.y)};"
        f"width:{_px(node.box.width)};height:{_px(node.box.height)};"
        "opacity:0;pointer-events:none;overflow:hidden"
    )
    return (
        f'<div class="domoxml-preserved"{_identity_attrs(node)} aria-hidden="true" '
        f'data-domoxml-preserved-payload="{payload}" style="{style}"></div>'
    )


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
        mid = f"arr-{end_name}"
        marker_ids[end_name] = mid
        # Simple filled triangle — points chosen for a clean arrow shape.
        orient = "auto-start-reverse" if end_name == "head" else "auto"
        defs += (
            f'<defs><marker id="{mid}" markerUnits="strokeWidth" '
            f'markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="{orient}">'
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
        # Approximate with an L-shaped path: horizontal first, then vertical.
        mid_x = lex
        mid_y = lsy
        d = (
            f"M {_number(lsx)} {_number(lsy)}"
            f" L {_number(mid_x)} {_number(mid_y)}"
            f" L {_number(lex)} {_number(ley)}"
        )
        shape_el = f'<path d="{escape(d, quote=True)}" {stroke_attrs} fill="none"/>'
    else:
        # curved: quadratic Bézier with control point at the midpoint offset.
        cpx = (lsx + lex) / 2
        cpy = (lsy + ley) / 2 - abs(lex - lsx) * 0.25
        d = (
            f"M {_number(lsx)} {_number(lsy)}"
            f" Q {_number(cpx)} {_number(cpy)}"
            f" {_number(lex)} {_number(ley)}"
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
    if node.media_data is not None:
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
        shapes = "".join(_node_html(node, assets, emitted_warnings) for node in slide.contents)
        width_px = round(emu_to_px(slide.width))
        height_px = round(emu_to_px(slide.height))
        transition_attrs = _slide_transition_attrs(slide.transition)
        bg_css = _slide_background_css(slide.background, assets)
        base_style = f"width:{width_px}px;height:{height_px}px"
        slide_style = f"{base_style};{bg_css}" if bg_css else base_style
        html = f'<div class="domoxml-slide"{transition_attrs} style="{slide_style}">{shapes}</div>'
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
