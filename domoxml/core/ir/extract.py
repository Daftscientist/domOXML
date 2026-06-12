"""Turn a captured :class:`RenderedSlide` into the normalized :class:`SlideIR`.

The mapping is **native-first**: every element that OOXML can express (solid/gradient/
picture fills, borders, shadows, basic geometry, text) is mapped to native, editable
DrawingML. An element is rasterised **only** when it has no faithful native mapping
(conic gradients, CSS filters, blend modes, clip paths, rotation, ``<svg>``/``<canvas>``).
Nothing is ever dropped silently: every element yields a :class:`CoverageItem`, and every
raster/approximation yields a :class:`ConversionWarning`.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from domoxml.core.drawingml.presets import match_polygon
from domoxml.core.images import ImageExt, crop_png, decode_data_uri, normalise_image
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Box,
    CharBullet,
    Fill,
    Geometry,
    Glow,
    GradientFill,
    Hyperlink,
    Line,
    LineSpacing,
    PictureFill,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.ir.parse import (
    css_list_style_to_autonum,
    css_list_style_to_bu_char,
    is_bold,
    parse_border_side,
    parse_caps,
    parse_color,
    parse_decoration,
    parse_gradient,
    parse_length_px,
    parse_letter_spacing_pt,
    parse_line_height,
    parse_margin_pt,
    parse_polygon,
    parse_radius_px,
    parse_shadow,
)
from domoxml.core.render.browser import (
    RenderedNode,
    RenderedSlide,
    RenderedTextRun,
    is_complex_transform,
)
from domoxml.core.units import px_to_emu, px_to_pt
from domoxml.types import ConversionWarning, CoverageItem, Disposition

_DEFAULT_TEXT_COLOR = Rgba(r=0, g=0, b=0)
_RASTER_TAGS = {"svg", "canvas", "video", "iframe"}
_URL_RE = re.compile(r"""url\(\s*['"]?(.*?)['"]?\s*\)""", re.IGNORECASE | re.DOTALL)

# Chromium reports logical alignments (start/end); map them to the IR's physical set.
_ALIGN: dict[str, Literal["left", "center", "right", "justify"]] = {
    "left": "left",
    "center": "center",
    "right": "right",
    "justify": "justify",
    "start": "left",
    "end": "right",
}


class ExtractResult(BaseModel):
    """A slide's IR plus the per-element coverage and any conversion warnings."""

    model_config = ConfigDict(frozen=True)

    slide: SlideIR
    coverage: tuple[CoverageItem, ...]
    warnings: tuple[ConversionWarning, ...]


def _hyperlink(href: str) -> Hyperlink | None:
    """Map an ``<a href>`` value to a :class:`Hyperlink`. ``#slide-N`` (1-based, the authoring
    convention) becomes an internal jump to the zero-based ``slide_index``; anything else is an
    external URL. Empty/missing hrefs yield ``None``."""
    href = href.strip()
    if not href:
        return None
    if href.startswith("#slide-"):
        try:
            return Hyperlink(slide_index=int(href.removeprefix("#slide-")) - 1)
        except ValueError:
            return None
    return Hyperlink(url=href)


def _text_run(text: str, styles: dict[str, str]) -> TextRun | None:
    if not text:
        return None
    underline, strike = parse_decoration(styles.get("textDecorationLine"))
    return TextRun(
        text=text,
        font_family=(styles.get("fontFamily") or "sans-serif").split(",")[0].strip().strip("'\""),
        size_pt=px_to_pt(parse_length_px(styles.get("fontSize")) or 16.0),
        bold=is_bold(styles.get("fontWeight")),
        italic=styles.get("fontStyle", "normal") == "italic",
        underline=underline,
        strike=strike,
        caps=parse_caps(styles.get("textTransform"), styles.get("fontVariantCaps")),
        letter_spacing_pt=parse_letter_spacing_pt(styles.get("letterSpacing")),
        color=parse_color(styles.get("color")) or _DEFAULT_TEXT_COLOR,
        hyperlink=_hyperlink(styles.get("domoxmlHref", "")),
    )


def _text_body(node: RenderedNode) -> TextBody | None:
    source = node.text_runs or (
        (RenderedTextRun(text=node.text, styles=node.styles),) if node.text else ()
    )
    if not source:
        return None
    paragraphs: list[list[TextRun]] = [[]]
    for fragment in source:
        pieces = fragment.text.split("\n")
        for index, piece in enumerate(pieces):
            run = _text_run(piece, fragment.styles)
            if run is not None:
                paragraphs[-1].append(run)
            if index < len(pieces) - 1:
                paragraphs.append([])
    if not any(paragraphs):
        return None
    align = _ALIGN.get((node.styles.get("textAlign") or "").strip().lower(), "left")
    styles = node.styles

    # Paragraph spacing from CSS margins (px → pt).
    space_before = parse_margin_pt(styles.get("marginTop")) or None
    space_after = parse_margin_pt(styles.get("marginBottom")) or None

    # Line height — skip when "normal" to avoid embedding browser-resolved metrics.
    raw_lh = styles.get("lineHeight", "")
    line_spacing: LineSpacing | None = parse_line_height(raw_lh) if raw_lh != "normal" else None

    # text-indent and margin-left → indent_pt / left_margin_pt.
    indent_pt = parse_margin_pt(styles.get("textIndent"))
    left_margin_pt = parse_margin_pt(styles.get("paddingLeft")) or parse_margin_pt(
        styles.get("marginLeft")
    )

    # Bullet detection via list context captured by the snapshot JS.
    bullet = None
    level = 0
    if node.tag == "li":
        raw_depth = styles.get("domoxmlListDepth", "1")
        try:
            level = max(0, int(raw_depth) - 1)
        except ValueError:
            level = 0
        list_type = styles.get("domoxmlListType") or styles.get("listStyleType") or "disc"
        autonum_scheme = css_list_style_to_autonum(list_type)
        if autonum_scheme is not None:
            bullet = AutoNumberBullet(scheme=autonum_scheme)
        else:
            char = css_list_style_to_bu_char(list_type)
            bullet = CharBullet(char=char)

    return TextBody(
        paragraphs=tuple(
            TextParagraph(
                runs=tuple(runs),
                align=align,
                line_spacing=line_spacing,
                space_before_pt=space_before,
                space_after_pt=space_after,
                indent_pt=indent_pt,
                left_margin_pt=left_margin_pt,
                level=level,
                bullet=bullet,
            )
            for runs in paragraphs
        )
    )


def _box(node: RenderedNode) -> Box:
    return Box(
        x=px_to_emu(node.x),
        y=px_to_emu(node.y),
        width=px_to_emu(node.width),
        height=px_to_emu(node.height),
    )


def _label(node: RenderedNode) -> str:
    snippet = node.text[:24].strip()
    return f"<{node.tag}>" + (f" “{snippet}”" if snippet else "")


def _has_complex_transform(value: str | None) -> bool:
    """True when transform can't be expressed as pure translation."""
    return is_complex_transform(value)


def _structural_raster_reason(node: RenderedNode) -> str | None:
    """A reason this element can only be rasterised, independent of its fill, or ``None``."""
    styles = node.styles
    if node.tag in _RASTER_TAGS:
        return f"<{node.tag}> has no native OOXML mapping"
    clip = styles.get("clipPath", "none")
    if clip not in ("none", "") and not (
        clip.strip().lower().startswith("polygon(") or "polygon(" in clip
    ):
        # Only polygon() is potentially mappable — non-polygon clip-paths still rasterise.
        # The actual polygon→preset matching happens later in the main loop; here we just
        # allow polygon() through.
        return "clip-path has no native mapping"
    if styles.get("mixBlendMode", "normal") not in ("normal", ""):
        return "mix-blend-mode has no native mapping"
    if styles.get("backdropFilter", "none") not in ("none", ""):
        return "backdrop-filter has no native mapping"
    if styles.get("filter", "none") not in ("none", ""):
        return "CSS filter has no native mapping"
    if _has_complex_transform(styles.get("transform")):
        return "rotated/skewed transform has no native mapping"
    return None


def _resolve_preset_geom(node: RenderedNode) -> tuple[Geometry, bool]:
    """Try to match a ``clip-path: polygon(...)`` to a preset geometry.

    Returns ``(geom_name, matched)`` where ``matched`` is ``True`` when the clip-path was
    successfully matched to a preset (the caller should use ``geom_name`` and treat the
    element as native), or ``False`` when the clip-path is not a polygon or does not match
    (the caller should rasterise).

    When there is no clip-path at all, returns ``("rect", False)`` — the caller ignores
    ``matched`` and uses ``_geometry()`` for the normal border-radius path.
    """
    clip = node.styles.get("clipPath", "none")
    if clip in ("none", ""):
        return "rect", False  # no clip-path; caller uses border-radius path
    polygon = parse_polygon(clip, width_px=node.width, height_px=node.height)
    if polygon is None:
        return "rect", False  # non-polygon or parse error
    preset = match_polygon(polygon, node.width, node.height)
    if preset is None:
        return "rect", False  # polygon doesn't match any known preset
    return preset, True  # type: ignore[return-value]


def _resolve_image_bytes(url: str, rendered: RenderedSlide) -> tuple[bytes, ImageExt] | None:
    raw = decode_data_uri(url) if url.startswith("data:") else rendered.resources.get(url)
    return normalise_image(raw) if raw is not None else None


def _resolve_fill(node: RenderedNode, rendered: RenderedSlide) -> tuple[Fill | None, str | None]:
    """Resolve a node's fill. Returns ``(fill, raster_reason)``; a non-``None`` reason means
    the fill can't be expressed natively and the element must rasterise."""
    styles = node.styles

    if node.tag == "img" and node.src:
        resolved = _resolve_image_bytes(node.src, rendered)
        if resolved is None:
            return None, "image source was not captured"
        data, ext = resolved
        return PictureFill(data=data, ext=ext), None

    background_image = styles.get("backgroundImage", "none")
    # Check for url(...) first, before checking for gradient keywords
    if "url(" in background_image:
        match = _URL_RE.search(background_image)
        resolved = _resolve_image_bytes(match.group(1), rendered) if match else None
        if resolved is None:
            return None, "background image was not captured"
        data, ext = resolved
        return PictureFill(data=data, ext=ext), None
    if "gradient" in background_image:
        gradient: GradientFill | None = parse_gradient(background_image)
        if gradient is not None:
            return gradient, None
        return None, "gradient has no native mapping (conic or layered)"

    background = parse_color(styles.get("backgroundColor"))
    if background is not None and background.a > 0:
        return SolidFill(color=background), None
    return None, None


def _resolve_border_sides(
    styles: dict[str, str],
) -> tuple[
    tuple[Line | None, Line | None, Line | None, Line | None],
    list[str],
]:
    """Parse all four CSS border sides; return ``(top, right, bottom, left)`` plus any
    approximation warning messages (e.g. ``double`` → ``solid``)."""
    warnings: list[str] = []
    sides: list[Line | None] = []
    for side in ("Top", "Right", "Bottom", "Left"):
        line, warn = parse_border_side(
            styles.get(f"border{side}Width"),
            styles.get(f"border{side}Style"),
            styles.get(f"border{side}Color"),
        )
        sides.append(line)
        if warn:
            warnings.append(warn)
    return (sides[0], sides[1], sides[2], sides[3]), warnings


def _make_side_rect(box: Box, fill: Fill) -> ShapeNode:
    """A zero-border, zero-corner rect ShapeNode used for per-side border decomposition."""
    return ShapeNode(box=box, geom="rect", fill=fill)


def _decompose_per_side(
    base_box: Box,
    top: Line | None,
    right: Line | None,
    bottom: Line | None,
    left: Line | None,
) -> list[ShapeNode]:
    """Emit up to 4 thin solid rects that reproduce CSS per-side borders.

    Layout convention (matches CSS border-box painting model):
    - top/bottom span the full width of the element.
    - left/right are clipped vertically to the space between top and bottom borders, to
      avoid double-painting corners.
    """
    rects: list[ShapeNode] = []
    top_w = top.width_emu if top is not None else 0
    bot_w = bottom.width_emu if bottom is not None else 0
    if top is not None:
        rects.append(
            _make_side_rect(
                Box(x=base_box.x, y=base_box.y, width=base_box.width, height=top_w),
                SolidFill(color=top.color),
            )
        )
    if bottom is not None:
        rects.append(
            _make_side_rect(
                Box(
                    x=base_box.x,
                    y=base_box.y + base_box.height - bot_w,
                    width=base_box.width,
                    height=bot_w,
                ),
                SolidFill(color=bottom.color),
            )
        )
    interior_y = base_box.y + top_w
    interior_h = base_box.height - top_w - bot_w
    if left is not None and interior_h > 0:
        rects.append(
            _make_side_rect(
                Box(x=base_box.x, y=interior_y, width=left.width_emu, height=interior_h),
                SolidFill(color=left.color),
            )
        )
    if right is not None and interior_h > 0:
        rects.append(
            _make_side_rect(
                Box(
                    x=base_box.x + base_box.width - right.width_emu,
                    y=interior_y,
                    width=right.width_emu,
                    height=interior_h,
                ),
                SolidFill(color=right.color),
            )
        )
    return rects


def _shadow_to_effect(shadow: Shadow, box: Box, warnings: list[ConversionWarning]) -> Shadow | Glow:
    """Decide whether to emit a :class:`Glow` or keep the :class:`Shadow` as-is.

    A CSS ``box-shadow`` with zero offset and a non-negative spread maps cleanly onto
    ``a:glow`` — it is more faithful in PowerPoint than an ``outerShdw`` with zero distance.
    Any other shadow stays as a :class:`Shadow` (outer or inner depending on ``inset``).
    """
    if not shadow.inset and shadow.distance_emu == 0 and shadow.spread_emu >= 0:
        # Convert to glow: radius = blur + spread (both contribute to halo size)
        radius = shadow.blur_emu + shadow.spread_emu
        return Glow(color=shadow.color, radius_emu=radius)
    return shadow


def _geometry(box: Box, corner_emu: int) -> Literal["rect", "roundRect", "ellipse"]:
    if corner_emu <= 0:
        return "rect"
    if corner_emu * 2 >= min(box.width, box.height):
        return "ellipse"
    return "roundRect"


def _opacity(styles: dict[str, str]) -> float:
    try:
        return max(0.0, min(1.0, float(styles.get("opacity", "1"))))
    except ValueError:
        return 1.0


def _is_plain_inline(node: RenderedNode, fill: Fill | None, line: Line | None) -> bool:
    """Whether a node is represented by its nearest block ancestor's rich text body."""
    return (
        node.parent >= 0
        and node.styles.get("display", "").startswith("inline")
        and node.tag != "img"
        and fill is None
        and line is None
        and parse_shadow(node.styles.get("boxShadow")) is None
    )


def _raster_shape(node: RenderedNode, rendered: RenderedSlide) -> ShapeNode | None:
    isolated = rendered.rasters.get(node.index)
    if isolated is not None:
        return ShapeNode(
            box=Box(
                x=px_to_emu(isolated.x),
                y=px_to_emu(isolated.y),
                width=px_to_emu(isolated.width),
                height=px_to_emu(isolated.height),
            ),
            fill=PictureFill(data=isolated.png, ext="png"),
        )
    crop = crop_png(
        rendered.png,
        left=node.x * rendered.scale,
        top=node.y * rendered.scale,
        width=node.width * rendered.scale,
        height=node.height * rendered.scale,
    )
    if crop is None:
        return None
    return ShapeNode(box=_box(node), fill=PictureFill(data=crop, ext="png"))


def _children(nodes: tuple[RenderedNode, ...]) -> dict[int, list[int]]:
    adjacency: dict[int, list[int]] = {}
    for node in nodes:
        adjacency.setdefault(node.parent, []).append(node.index)
    return adjacency


def _subtree(root: int, children: dict[int, list[int]]) -> set[int]:
    seen: set[int] = set()
    stack = [root]
    while stack:
        index = stack.pop()
        if index in seen:
            continue
        seen.add(index)
        stack.extend(children.get(index, ()))
    return seen


def extract_slide(rendered: RenderedSlide) -> ExtractResult:
    """Map every captured node to native OOXML where possible, rasterising only the residue.

    Stacking follows DOM order; a rasterised element consumes its whole subtree so its
    children aren't drawn twice over the baked-in pixels.
    """
    children = _children(rendered.nodes)
    consumed: set[int] = set()
    shapes: list[ShapeNode] = []
    coverage: list[CoverageItem] = []
    warnings: list[ConversionWarning] = []

    for node in rendered.nodes:
        if node.index in consumed or node.width <= 0 or node.height <= 0:
            continue

        reason = _structural_raster_reason(node)
        fill: Fill | None = None
        if reason is None:
            fill, reason = _resolve_fill(node, rendered)

        # If the structural check let a polygon clip-path through, try to match it to a preset.
        # If matching fails, fall back to raster (overwrite reason).
        clip = node.styles.get("clipPath", "none")
        has_polygon_clip = clip not in ("none", "") and (
            clip.strip().lower().startswith("polygon(") or "polygon(" in clip
        )
        preset_geom: Geometry = "rect"
        polygon_matched = False
        if has_polygon_clip and reason is None:
            preset_geom, polygon_matched = _resolve_preset_geom(node)
            if not polygon_matched:
                reason = "clip-path polygon does not match any known preset geometry"

        if reason is not None:
            label = _label(node)
            shape = _raster_shape(node, rendered)
            consumed |= _subtree(node.index, children)
            if shape is None:
                warnings.append(
                    ConversionWarning(
                        message=f"dropped — empty raster region ({reason})", element=label
                    )
                )
                # Record coverage even when rasterization fails
                coverage.append(
                    CoverageItem(element=label, disposition=Disposition.RASTER, reason=reason)
                )
                continue
            shapes.append(shape)
            coverage.append(
                CoverageItem(element=label, disposition=Disposition.RASTER, reason=reason)
            )
            warnings.append(ConversionWarning(message=f"rasterised — {reason}", element=label))
            continue

        box = _box(node)
        # Resolve borders: uniform borders use a single a:ln; per-side borders without
        # border-radius are decomposed into four thin ShapeNode rects; per-side + radius
        # falls back to the heaviest-side approximation.
        (side_top, side_right, side_bottom, side_left), warn_msgs = _resolve_border_sides(
            node.styles
        )
        present_sides = [s for s in (side_top, side_right, side_bottom, side_left) if s is not None]

        line: Line | None = None
        side_rect_shapes: list[ShapeNode] = []
        line_warning: ConversionWarning | None = (
            ConversionWarning(message=warn_msgs[0]) if warn_msgs else None
        )

        # When a polygon preset was matched, use that geometry; otherwise the border-radius path.
        if polygon_matched:
            geom: Geometry = preset_geom
            corner = 0
        else:
            corner = px_to_emu(
                parse_radius_px(
                    node.styles.get("borderRadius"), shorter_side_px=min(node.width, node.height)
                )
            )
            geom = _geometry(box, corner)

        if present_sides:
            uniform = len(present_sides) == 4 and all(s == present_sides[0] for s in present_sides)
            if uniform:
                line = present_sides[0]
            elif corner == 0:
                # Per-side decomposition: the shape gets no a:ln; four thin solid rects carry
                # each visible border, positioned flush to their respective edges.
                side_rect_shapes = _decompose_per_side(
                    box, side_top, side_right, side_bottom, side_left
                )
                line_warning = line_warning or ConversionWarning(
                    message="non-uniform border decomposed into per-side rects"
                )
            else:
                # border-radius + non-uniform: native decomposition is not possible —
                # rounded borders can't be reproduced with flat rects.
                line = max(present_sides, key=lambda s: s.width_emu)
                line_warning = line_warning or ConversionWarning(
                    message="non-uniform border with border-radius approximated by one outline"
                )

        if _is_plain_inline(node, fill, line):
            coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
            continue
        text = _text_body(node)
        if text is not None and fill is None and line is None:
            padding = px_to_emu(4)
            box = box.model_copy(update={"x": box.x - padding, "width": box.width + padding * 2})
        shadow = parse_shadow(node.styles.get("boxShadow"))
        effect = _shadow_to_effect(shadow, box, warnings) if shadow is not None else None
        # Emit per-side border rects before the main shape so they appear behind its fill.
        shapes.extend(side_rect_shapes)
        shapes.append(
            ShapeNode(
                box=box,
                geom=geom,
                fill=fill,
                line=line,
                effects=(effect,) if effect is not None else (),
                corner_radius_emu=corner,
                opacity=_opacity(node.styles),
                text=text,
            )
        )
        coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
        if line_warning is not None:
            warnings.append(line_warning.model_copy(update={"element": _label(node)}))

    slide = SlideIR(
        width=px_to_emu(rendered.width),
        height=px_to_emu(rendered.height),
        shapes=tuple(shapes),
    )
    return ExtractResult(slide=slide, coverage=tuple(coverage), warnings=tuple(warnings))
