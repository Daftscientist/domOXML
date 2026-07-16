"""Turn a captured :class:`RenderedSlide` into the normalized :class:`SlideIR`.

The mapping is **native-first**: every element that OOXML can express (solid/gradient/
picture fills, borders, shadows, basic geometry, text) is mapped to native, editable
DrawingML. An element is rasterised **only** when it has no faithful native mapping
(conic gradients, CSS filters, blend modes, clip paths, rotation, ``<svg>``/``<canvas>``).
Nothing is ever dropped silently: every element yields a :class:`CoverageItem`, and every
raster/approximation yields a :class:`ConversionWarning`.
"""

from __future__ import annotations

import contextlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from domoxml.core.crop import cover_crop
from domoxml.core.drawingml.presets import match_polygon
from domoxml.core.fillcrop import cover_crop_fractions
from domoxml.core.images import (
    ImageExt,
    crop_png,
    decode_data_uri,
    image_dimensions,
    normalise_image,
)
from domoxml.core.ir.connector_extract import extract_connector
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Box,
    CharBullet,
    Connector,
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
    SrcRect,
    TableNode,
    TextBody,
    TextParagraph,
    TextRun,
    Transform,
)
from domoxml.core.ir.parse import (
    css_list_style_to_autonum,
    css_list_style_to_bu_char,
    is_bold,
    parse_background_position,
    parse_background_size,
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
from domoxml.core.ir.pattern import match_pattern_fill
from domoxml.core.ir.slide_properties_extract import extract_slide_properties
from domoxml.core.ir.svg_extract import extract_custom_geometry
from domoxml.core.ir.table_extract import extract_table
from domoxml.core.render.browser import (
    RenderedNode,
    RenderedSlide,
    RenderedTextRun,
    is_complex_transform,
    parse_native_transform,
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


def _detect_anchor(styles: dict[str, str]) -> Literal["top", "middle", "bottom"]:
    """Infer vertical anchor from flex container styles.

    Detection rules (conservative — only fires when clear flex alignment signals exist):
    - ``display:flex`` with ``flex-direction:column`` (or default ``row``):
      - ``justify-content:center`` + column → anchor "middle"
      - ``justify-content:flex-end`` + column → anchor "bottom"
      - ``align-items:center`` + row-ish (single-axis centering) → anchor "middle"
      - ``align-items:flex-end`` + row-ish → anchor "bottom"
    Default is "top" which emits no special attribute.
    """
    display = (styles.get("display") or "").lower()
    if "flex" not in display:
        return "top"
    flex_dir = (styles.get("flexDirection") or "row").lower()
    column_flow = flex_dir.startswith("column")
    justify = (styles.get("justifyContent") or "").lower()
    align = (styles.get("alignItems") or "").lower()
    if column_flow:
        # Main-axis aligns content vertically.
        if justify in ("center",):
            return "middle"
        if justify in ("flex-end", "end"):
            return "bottom"
    else:
        # Cross-axis aligns content vertically (row layout, single-line text).
        if align in ("center",):
            return "middle"
        if align in ("flex-end", "end"):
            return "bottom"
    return "top"


def _detect_text_align(
    styles: dict[str, str],
) -> Literal["left", "center", "right", "justify"]:
    """Infer horizontal text alignment, including flex main/cross-axis positioning."""
    raw = (styles.get("textAlign") or "").strip().lower()
    if raw not in ("", "start"):
        return _ALIGN.get(raw, "left")
    if "flex" not in (styles.get("display") or "").lower():
        return _ALIGN.get(raw, "left")
    column_flow = (styles.get("flexDirection") or "row").lower().startswith("column")
    horizontal = styles.get("alignItems") if column_flow else styles.get("justifyContent")
    horizontal = (horizontal or "").lower()
    if horizontal == "center":
        return "center"
    if horizontal in ("flex-end", "end"):
        return "right"
    return "left"


def _detect_autofit(styles: dict[str, str]) -> Literal["none", "normal", "shape"]:
    """Infer autofit mode from CSS overflow and white-space.

    Rules:
    - ``overflow:hidden`` + fixed element → keep ``normal`` (normAutofit); text is clipped.
    - ``white-space:nowrap`` single-line → ``shape`` (spAutoFit) is acceptable.
    - Default → ``normal`` (normAutofit).
    """
    overflow = (styles.get("overflow") or "").lower()
    white_space = (styles.get("whiteSpace") or "").lower()
    if overflow == "hidden":
        return "normal"
    if white_space == "nowrap":
        return "shape"
    return "normal"


def _detect_columns(styles: dict[str, str]) -> tuple[int, int]:
    """Parse ``column-count`` and ``column-gap`` from styles.

    Returns ``(columns, column_gap_emu)``; ``columns`` is at least 1.
    ``column-gap`` is a px value converted to EMU.
    """
    raw_count = (styles.get("columnCount") or "").strip()
    columns = 1
    if raw_count and raw_count not in ("auto", "normal"):
        with contextlib.suppress(ValueError):
            columns = max(1, int(raw_count))
    column_gap_emu = 0
    raw_gap = (styles.get("columnGap") or "").strip()
    if raw_gap and raw_gap not in ("normal", ""):
        gap_px = parse_length_px(raw_gap)
        if gap_px > 0:
            column_gap_emu = px_to_emu(gap_px)
    return columns, column_gap_emu


def _text_body_margins(node: RenderedNode) -> tuple[int, int, int, int]:
    """Recover CSS container padding as DrawingML text-body insets."""
    styles = node.styles
    is_container = (
        styles.get("domoxmlConsolidatedText") == "true"
        or "flex" in (styles.get("display") or "").lower()
        or _detect_columns(styles)[0] > 1
    )
    if not is_container:
        return (0, 0, 0, 0)
    return (
        px_to_emu(parse_length_px(styles.get("paddingLeft"))),
        px_to_emu(parse_length_px(styles.get("paddingTop"))),
        px_to_emu(parse_length_px(styles.get("paddingRight"))),
        px_to_emu(parse_length_px(styles.get("paddingBottom"))),
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
    align = _detect_text_align(node.styles)
    styles = node.styles

    # Paragraph spacing from CSS margins (px → pt).
    space_before = parse_margin_pt(styles.get("marginTop")) or None
    space_after = parse_margin_pt(styles.get("marginBottom")) or None

    # Line height — skip when "normal" to avoid embedding browser-resolved metrics.
    raw_lh = styles.get("lineHeight", "")
    line_spacing: LineSpacing | None = parse_line_height(raw_lh) if raw_lh != "normal" else None

    # text-indent and margin-left → indent_pt / left_margin_pt.
    indent_pt = parse_margin_pt(styles.get("textIndent"))
    margins = _text_body_margins(node)
    left_margin_pt = parse_margin_pt(styles.get("marginLeft"))
    if margins == (0, 0, 0, 0):
        left_margin_pt = parse_margin_pt(styles.get("paddingLeft")) or left_margin_pt

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
            raw_ordinal = styles.get("domoxmlListOrdinal", "1")
            try:
                ordinal = max(1, int(raw_ordinal))
            except ValueError:
                ordinal = 1
            bullet = AutoNumberBullet(scheme=autonum_scheme, start_at=ordinal)
        else:
            char = css_list_style_to_bu_char(list_type)
            bullet = CharBullet(char=char)
        if styles.get("listStylePosition", "outside") != "inside":
            # LibreOffice supplies a large default list margin when DrawingML omits these
            # values. Keep CSS's outside marker gutter explicit so marker and text retain
            # their browser positions. Any authored padding remains part of the text margin.
            left_margin_pt += 13.5
            indent_pt = -(left_margin_pt - 0.75)

    anchor = _detect_anchor(styles)
    autofit = _detect_autofit(styles)
    columns, column_gap_emu = _detect_columns(styles)

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
        ),
        anchor=anchor,
        autofit=autofit,
        columns=columns,
        column_gap_emu=column_gap_emu,
        margins=margins,
    )


def _box(node: RenderedNode) -> Box:
    transform = node.styles.get("transform")
    if transform and transform != "none" and not _has_complex_transform(transform):
        with contextlib.suppress(KeyError, ValueError):
            layout_width = float(node.styles["domoxmlLayoutWidth"])
            layout_height = float(node.styles["domoxmlLayoutHeight"])
            center_x = node.x + node.width / 2
            center_y = node.y + node.height / 2
            return Box(
                x=px_to_emu(center_x - layout_width / 2),
                y=px_to_emu(center_y - layout_height / 2),
                width=px_to_emu(layout_width),
                height=px_to_emu(layout_height),
            )
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
    """True when transform can't be expressed as pure translation, rotation, or flip."""
    return is_complex_transform(value)


_CENTER_ORIGINS = frozenset({"50% 50%", "center center", "center", "50%"})


def _is_center_transform_origin(value: str | None) -> bool:
    """Return True when transform-origin is the element center (the OOXML default).

    Chromium resolves transform-origin to a pixel value like ``"640px 360px"``, so we
    cannot simply compare to the string "center".  We accept any value unless it is a
    keyword/percentage that is clearly off-center.  In practice, if transformOrigin is
    not captured or is empty we assume center (safe default).
    """
    if not value or value.strip() in ("", "none"):
        return True  # absent ⇒ assume center
    # Chromium exposes this as resolved px like "320px 180px" — we cannot compare
    # to the element's own half-size here without geometry.  The JS snapshot captures
    # it as a string; we only reject non-center *keyword/percent* values.
    lower = value.strip().lower()
    if lower in ("50% 50%", "center center", "center"):
        return True
    # If it looks like a resolved px pair we accept it (can't check without shape size).
    # All other keyword forms (top, left, right, bottom, top left, …) are non-center.
    return "px" in lower


def _structural_raster_reason(node: RenderedNode) -> str | None:
    """A reason this element can only be rasterised, independent of its fill, or ``None``."""
    styles = node.styles
    if node.tag in _RASTER_TAGS and node.tag != "svg":
        return f"<{node.tag}> has no native OOXML mapping"
    if node.tag == "svg":
        # SVG is handled by the custom-geometry path in extract_slide; returning None
        # here lets the SVG node fall through to that check. If the custom-geometry
        # attempt fails, extract_slide will rasterise it explicitly.
        return None
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
    shadow = parse_shadow(styles.get("boxShadow"))
    if shadow is not None and shadow.inset:
        return "inset box-shadow is rasterised because LibreOffice ignores a:innerShdw"
    transform_val = styles.get("transform")
    if _has_complex_transform(transform_val):
        return "skew/perspective/shear transform has no native mapping"
    if transform_val and transform_val != "none":
        _rotation, flip_h, flip_v = parse_native_transform(transform_val)
        if (flip_h or flip_v) and (node.text or node.text_runs):
            return "CSS flip mirrors text but PowerPoint keeps shape text readable"
    # A non-center transform-origin cannot be faithfully round-tripped via a:xfrm
    # (which always rotates about the shape center).
    if transform_val and transform_val != "none":
        origin = styles.get("transformOrigin")
        if not _is_center_transform_origin(origin):
            return "transform-origin is not center — rotation falls back to raster"
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


def _is_svg_url(url: str) -> bool:
    """True when ``url`` looks like an SVG resource: a ``.svg`` file or a
    ``data:image/svg+xml`` URI."""
    lowered = url.lower()
    if lowered.startswith("data:image/svg"):
        return True
    path = lowered.split("?", 1)[0].split("#", 1)[0]
    return path.endswith(".svg")


def _resolve_svg_bytes(url: str, rendered: RenderedSlide) -> bytes | None:
    """Return raw SVG bytes for ``url`` from the resource cache, or ``None``."""
    raw = decode_data_uri(url) if url.startswith("data:") else rendered.resources.get(url)
    if raw is None:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):  # trim UTF-8 BOM
        raw = raw[3:]
    return raw


def _svg_to_png(svg_bytes: bytes, *, width_px: int, height_px: int) -> bytes | None:
    """Rasterise SVG to PNG via cairosvg if installed, else ``None`` (caller falls back to the
    slide-PNG crop, which Chromium has already rendered)."""
    try:
        import cairosvg  # type: ignore[import-untyped]
    except ImportError:
        return None
    return cairosvg.svg2png(  # type: ignore[reportUnknownMemberType,no-any-return]
        bytestring=svg_bytes, output_width=max(1, width_px), output_height=max(1, height_px)
    )


def _img_crop(node: RenderedNode, rendered: RenderedSlide) -> SrcRect | None:
    """A DrawingML ``srcRect`` for ``object-fit:cover`` on an ``<img>``, or ``None``.

    Decodes the source to get the intrinsic size, then computes cover crop fractions against
    the rendered box. ``contain``/explicit fits letterbox (no native srcRect) and return None.
    """
    if node.styles.get("objectFit", "").strip().lower() != "cover" or not node.src:
        return None
    raw = (
        decode_data_uri(node.src)
        if node.src.startswith("data:")
        else rendered.resources.get(node.src)
    )
    if raw is None:
        return None
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(raw)) as img:
            src_w, src_h = img.size
    except Exception:
        return None
    if src_w <= 0 or src_h <= 0 or node.width <= 0 or node.height <= 0:
        return None
    crop = cover_crop(src_w=src_w, src_h=src_h, dst_w=node.width, dst_h=node.height)
    if not any((crop.left, crop.top, crop.right, crop.bottom)):
        return None
    return crop


def _background_crop(data: bytes, node: RenderedNode) -> SrcRect | None:
    """Compute an ``a:srcRect`` crop for a div ``background-image`` from background-size/position.

    Only ``background-size: cover`` produces a source-rect crop (a window of the source shown
    stretched to fill the shape). ``contain`` / explicit sizes letter-box the whole image, which
    a blip ``a:srcRect`` cannot express (it crops, it does not pad) so those fall through with no
    crop (the image stretches to fill, matching the existing behaviour). Returns ``None`` when no
    crop applies or the image cannot be measured.
    """
    mode, _explicit = parse_background_size(node.styles.get("backgroundSize"))
    if mode != "cover":
        return None
    dims = image_dimensions(data)
    if dims is None:
        return None
    img_w, img_h = dims
    if node.width <= 0 or node.height <= 0:
        return None
    pos_x, pos_y = parse_background_position(node.styles.get("backgroundPosition"))
    left, top, right, bottom = cover_crop_fractions(
        img_w, img_h, node.width, node.height, pos_x=pos_x, pos_y=pos_y
    )
    if left <= 0 and top <= 0 and right <= 0 and bottom <= 0:
        return None
    return SrcRect(left=left, top=top, right=right, bottom=bottom)


def _resolve_fill(node: RenderedNode, rendered: RenderedSlide) -> tuple[Fill | None, str | None]:
    """Resolve a node's fill. Returns ``(fill, raster_reason)``; a non-``None`` reason means
    the fill can't be expressed natively and the element must rasterise."""
    styles = node.styles

    if node.tag == "img" and node.src:
        # SVG source: preserve the vector via the svgBlip extension with a PNG fallback blip.
        if _is_svg_url(node.src):
            svg_bytes = _resolve_svg_bytes(node.src, rendered)
            if svg_bytes is not None:
                w_px, h_px = max(1, round(node.width)), max(1, round(node.height))
                png = _svg_to_png(svg_bytes, width_px=w_px, height_px=h_px)
                if png is None:
                    # No SVG rasteriser — crop the region Chromium already rendered.
                    png = crop_png(
                        rendered.png,
                        left=node.x * rendered.scale,
                        top=node.y * rendered.scale,
                        width=node.width * rendered.scale,
                        height=node.height * rendered.scale,
                    )
                if png is not None:
                    return PictureFill(data=png, ext="png", svg_data=svg_bytes), None
            return None, "SVG image source was not captured"

        resolved = _resolve_image_bytes(node.src, rendered)
        if resolved is None:
            return None, "image source was not captured"
        data, ext = resolved
        crop = _img_crop(node, rendered)
        return PictureFill(data=data, ext=ext, crop=crop), None

    background_image = styles.get("backgroundImage", "none")
    # Check for url(...) first, before checking for gradient keywords
    if "url(" in background_image:
        match = _URL_RE.search(background_image)
        resolved = _resolve_image_bytes(match.group(1), rendered) if match else None
        if resolved is None:
            return None, "background image was not captured"
        data, ext = resolved
        crop = _background_crop(data, node)
        return PictureFill(data=data, ext=ext, crop=crop), None
    if "repeating-linear-gradient" in background_image.lower():
        # Try the native two-colour stripe -> a:pattFill mapping before the gradient path.
        pattern = match_pattern_fill(background_image)
        if pattern is not None:
            return pattern, None
        # Not a clean two-colour stripe; fall through to the raster/warning path unchanged.
        return None, "repeating gradient is not a clean two-colour pattern (rasterised)"
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
        # CSS and DrawingML use different blur kernels. These factors are calibrated against
        # Chromium's CSS raster and LibreOffice's DrawingML renderer so the visible falloff,
        # rather than the nominal radius, is preserved.
        radius = round((shadow.blur_emu + shadow.spread_emu) * 0.85)
        color = shadow.color.model_copy(update={"a": shadow.color.a * 0.6})
        return Glow(color=color, radius_emu=radius)
    if not shadow.inset:
        return shadow.model_copy(update={"blur_emu": round(shadow.blur_emu * 0.75)})
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


def _parse_transform(styles: dict[str, str]) -> Transform | None:
    """Parse CSS ``transform`` into a :class:`Transform` IR node, or ``None`` when identity.

    Only called when ``is_complex_transform`` has already returned False, so the transform
    is guaranteed to be a pure rotation/flip combination.  Translation components are ignored
    (the bounding-box position already accounts for them).
    """
    value = styles.get("transform")
    if not value or value == "none":
        return None
    rotation_deg, flip_h, flip_v = parse_native_transform(value)
    if rotation_deg == 0.0 and not flip_h and not flip_v:
        return None
    return Transform(rotation_deg=rotation_deg, flip_h=flip_h, flip_v=flip_v)


def extract_slide(rendered: RenderedSlide) -> ExtractResult:
    """Map every captured node to native OOXML where possible, rasterising only the residue.

    Stacking follows DOM order; a rasterised element consumes its whole subtree so its
    children aren't drawn twice over the baked-in pixels.
    """
    children = _children(rendered.nodes)
    consumed: set[int] = set()
    shapes: list[ShapeNode] = []
    nodes: list[Connector | TableNode] = []
    coverage: list[CoverageItem] = []
    warnings: list[ConversionWarning] = []

    slide_root, transition, background = extract_slide_properties(
        rendered.nodes, lambda node: _resolve_fill(node, rendered)
    )

    for node in rendered.nodes:
        if node.index in consumed or node.width <= 0 or node.height <= 0:
            continue

        # An opted-in slide root owns the canvas background. The browser's synthetic body is
        # only a rendering wrapper and must not become an opaque full-slide shape above it.
        if slide_root is not None and node.tag == "body":
            continue

        # Skip the slide root node itself — it is the canvas container, not a shape (its fill
        # becomes the slide background, captured above).
        if slide_root is not None and node.index == slide_root.index:
            consumed.add(node.index)
            continue

        # --- Native table interception ---
        # A <table> subtree maps to a native a:tbl (graphicFrame). Consume the whole subtree so
        # its rows/cells aren't also emitted as shapes.
        if node.tag == "table":
            table = extract_table(
                node,
                rendered.nodes,
                children,
                fill_for=lambda cell: _resolve_fill(cell, rendered)[0],
                borders_for=_resolve_border_sides,
                text_for=_text_body,
            )
            if table is not None:
                nodes.append(table)
                consumed |= _subtree(node.index, children)
                coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
                continue

        # --- SVG custom-geometry interception ---
        # An inline <svg> with exactly one <path> child whose d attribute was captured
        # can be converted to a native a:custGeom instead of being rasterised.
        if node.tag == "svg":
            svg = extract_custom_geometry(node, rendered.nodes, children)
            if svg.warning is not None:
                warnings.append(svg.warning)
            if svg.geometry is not None:
                fill_node = svg.style_node
                fill, fill_reason = _resolve_fill(fill_node, rendered)
                (side_top, side_right, side_bottom, side_left), _warns = _resolve_border_sides(
                    fill_node.styles
                )
                present_sides = [
                    s for s in (side_top, side_right, side_bottom, side_left) if s is not None
                ]
                line: Line | None = None
                if present_sides:
                    uniform = len(present_sides) == 4 and all(
                        s == present_sides[0] for s in present_sides
                    )
                    if uniform:
                        line = present_sides[0]
                    else:
                        line = max(present_sides, key=lambda s: s.width_emu)

                # Build the ShapeNode with custom_geom
                box = _box(node)
                shapes.append(
                    ShapeNode(
                        box=box,
                        custom_geom=svg.geometry,
                        fill=fill if fill_reason is None else None,
                        line=line,
                    )
                )
                consumed |= _subtree(node.index, children)
                coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
                continue
            else:
                # SVG custom-geometry failed: fall through to raster
                label = _label(node)
                shape = _raster_shape(node, rendered)
                consumed |= _subtree(node.index, children)
                raster_reason = "SVG could not be converted to custom geometry; rasterised"
                if shape is None:
                    warnings.append(
                        ConversionWarning(
                            message=f"dropped — empty raster region ({raster_reason})",
                            element=label,
                        )
                    )
                    coverage.append(
                        CoverageItem(
                            element=label, disposition=Disposition.RASTER, reason=raster_reason
                        )
                    )
                else:
                    shapes.append(shape)
                    coverage.append(
                        CoverageItem(
                            element=label, disposition=Disposition.RASTER, reason=raster_reason
                        )
                    )
                    warnings.append(
                        ConversionWarning(message=f"rasterised — {raster_reason}", element=label)
                    )
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

        # --- HR / thin-element connector detection ---
        # Check before emitting a ShapeNode; <hr> and thin unfilled elements become Connectors.
        connector = extract_connector(node, fill, line)
        if connector is not None:
            nodes.append(connector)
            consumed.add(node.index)
            coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
            continue

        if _is_plain_inline(node, fill, line):
            coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
            continue
        text = _text_body(node)
        if (
            text is not None
            and text.columns > 1
            and (node.styles.get("columnFill") or "balance") != "auto"
        ):
            warnings.append(
                ConversionWarning(
                    message=("balanced CSS columns approximated as sequential PowerPoint columns"),
                    element=_label(node),
                )
            )
        if text is not None and fill is None and line is None:
            outside_bullet = (
                any(paragraph.bullet is not None for paragraph in text.paragraphs)
                and node.styles.get("listStylePosition", "outside") != "inside"
            )
            left_padding = px_to_emu(18 if outside_bullet else 4)
            right_padding = px_to_emu(4)
            box = box.model_copy(
                update={
                    "x": box.x - left_padding,
                    "width": box.width + left_padding + right_padding,
                }
            )
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
                transform=_parse_transform(node.styles),
            )
        )
        if node.styles.get("domoxmlConsolidatedText") == "true":
            consumed |= _subtree(node.index, children) - {node.index}
        coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
        if line_warning is not None:
            warnings.append(line_warning.model_copy(update={"element": _label(node)}))

    slide = SlideIR(
        width=px_to_emu(rendered.width),
        height=px_to_emu(rendered.height),
        shapes=tuple(shapes),
        nodes=tuple(nodes),
        transition=transition,
        background=background,
    )
    return ExtractResult(slide=slide, coverage=tuple(coverage), warnings=tuple(warnings))
