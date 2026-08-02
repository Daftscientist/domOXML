"""Turn a captured :class:`RenderedSlide` into the normalized :class:`SlideIR`.

The mapping is **native-first**: every element that OOXML can express (solid/gradient/
picture fills, borders, shadows, basic geometry, text) is mapped to native, editable
DrawingML. An element is rasterised **only** when it has no faithful native mapping
(conic gradients, unsupported CSS filters, blend modes, clip paths, rotation,
``<svg>``/``<canvas>``).
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
from domoxml.core.fillcrop import cover_crop_fractions, explicit_crop_fractions
from domoxml.core.images import (
    ImageExt,
    crop_png,
    decode_data_uri,
    image_dimensions,
    normalise_image,
)
from domoxml.core.ir.connector_extract import extract_connector
from domoxml.core.ir.effect_calibration import (
    BOX_SHADOW_BLUR_TO_DML,
    CUSTOM_GLOW_ALPHA_TO_DML,
    CUSTOM_GLOW_RADIUS_TO_DML,
    CUSTOM_SHADOW_ALPHA_TO_DML,
    CUSTOM_SHADOW_BLUR_TO_DML,
)
from domoxml.core.ir.effect_payload import decode_effect_payload, decode_effects
from domoxml.core.ir.geometry_payload import decode_custom_geometry
from domoxml.core.ir.group_payload import GroupMemberPayload, GroupPayload, decode_group_payload
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Blur,
    Box,
    CanvasNode,
    CharBullet,
    Connector,
    Fill,
    FillOverlay,
    Geometry,
    Glow,
    GradientFill,
    GroupNode,
    Hyperlink,
    Line,
    LineSpacing,
    Node,
    PatternFill,
    PictureFill,
    PortableFallback,
    PreservedNode,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SoftEdge,
    SolidFill,
    SourceProvenance,
    SrcRect,
    TextBody,
    TextParagraph,
    TextRun,
    Transform,
)
from domoxml.core.ir.parse import (
    css_list_style_to_autonum,
    css_list_style_to_bu_char,
    fill_overlay_base_styles,
    is_bold,
    parse_background_position,
    parse_background_size,
    parse_blur_filter,
    parse_border_side,
    parse_box_reflection,
    parse_caps,
    parse_color,
    parse_decoration,
    parse_drop_shadow_filter,
    parse_fill_overlay_effect,
    parse_gradient,
    parse_length_px,
    parse_letter_spacing_pt,
    parse_line_height,
    parse_margin_pt,
    parse_polygon,
    parse_radius_px,
    parse_shadow,
    parse_shadows,
    parse_soft_edge_mask,
    parse_svg_fill_overlay_filter,
    parse_svg_soft_edge_filter,
)
from domoxml.core.ir.pattern import match_pattern_fill
from domoxml.core.ir.slide_properties_extract import extract_slide_properties
from domoxml.core.ir.svg_extract import extract_custom_geometry
from domoxml.core.ir.table_extract import extract_table
from domoxml.core.ir.table_payload import apply_table_geometry, decode_table_geometry
from domoxml.core.ir.text_payload import decode_text_body
from domoxml.core.opc import decode_payload
from domoxml.core.render.browser import (
    RenderedNode,
    RenderedSlide,
    RenderedTextRun,
    is_complex_transform,
    parse_native_transform,
)
from domoxml.core.svg_stroke import parse_svg_dasharray
from domoxml.core.units import px_to_emu, px_to_pt
from domoxml.types import (
    ConversionWarning,
    CoverageItem,
    Editability,
    Representation,
    SourceRetention,
)

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


def _text_body_from_decoded(node: RenderedNode, encoded: TextBody | None) -> TextBody | None:
    if encoded is not None:
        return encoded
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


def _text_body(node: RenderedNode) -> TextBody | None:
    return _text_body_from_decoded(node, decode_text_body(node.styles.get("domoxmlTextPayload")))


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
    node_id = node.styles.get("domoxmlNodeId", "").strip()
    identity = f"#{node_id}" if node_id else ""
    return f"<{node.tag}>{identity}" + (f" “{snippet}”" if snippet else "")


class _IdentityAllocator:
    """Assign collision-free IDs while reserving metadata IDs before extraction starts."""

    def __init__(self, sources: tuple[RenderedNode, ...]) -> None:
        self._reserved = {
            value for source in sources if (value := source.styles.get("domoxmlNodeId", "").strip())
        }
        self._allocated: set[str] = set()
        self._automatic_bases: dict[int, str] = {}

    def _base_id(self, source: RenderedNode) -> str:
        inherited = source.styles.get("domoxmlNodeId", "").strip()
        if inherited:
            return inherited
        existing = self._automatic_bases.get(source.index)
        if existing is not None:
            return existing
        stem = f"html-auto-{source.index}"
        candidate = stem
        suffix = 2
        while candidate in self._reserved or candidate in self._allocated:
            candidate = f"{stem}-{suffix}"
            suffix += 1
        self._automatic_bases[source.index] = candidate
        return candidate

    def apply[T: CanvasNode](
        self, output: T, source: RenderedNode, *, role: str | None = None
    ) -> T:
        """Attach stable HTML identity/provenance to one emitted canvas node."""
        owner_id = self._base_id(source)
        node_id = owner_id if role is None else f"{owner_id}:{role}"
        if node_id in self._allocated:
            raise ValueError(f"duplicate HTML canvas node_id: {node_id!r}")
        self._allocated.add(node_id)
        source_format_raw = source.styles.get("domoxmlSourceFormat", "html")
        source_format: Literal["html", "pptx"] = "pptx" if source_format_raw == "pptx" else "html"
        source_id = (
            source.styles.get("domoxmlSourceId", "").strip()
            or source.styles.get("domoxmlElementId", "").strip()
            or f"dom:{source.index}"
        )
        provenance = SourceProvenance(
            source_format=source_format,
            source_id=source_id,
            source_part=source.styles.get("domoxmlSourcePart") or None,
            owner_node_id=(
                source.styles.get("domoxmlOwnerNodeId") or (owner_id if role is not None else None)
            ),
            role=role or source.styles.get("domoxmlLayerRole") or None,
        )
        return output.model_copy(update={"node_id": node_id, "provenance": provenance})


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
    blend_mode = styles.get("backgroundBlendMode", "normal")
    encoded_effect_payload = decode_effect_payload(styles.get("domoxmlEffects"))
    encoded_effects = encoded_effect_payload.effects if encoded_effect_payload is not None else None
    encoded_overlay = next(
        (effect for effect in (encoded_effects or ()) if isinstance(effect, FillOverlay)),
        None,
    )
    normalized_overlay = (
        fill_overlay_base_styles(
            styles.get("backgroundImage"),
            blend_mode,
            encoded_overlay,
            background_color=styles.get("backgroundColor"),
            background_size=styles.get("backgroundSize"),
            background_position=styles.get("backgroundPosition"),
            background_repeat=styles.get("backgroundRepeat"),
            background_origin=styles.get("backgroundOrigin"),
            background_clip=styles.get("backgroundClip"),
        )
        if encoded_overlay is not None
        else None
    )
    if encoded_overlay is not None and normalized_overlay is None:
        return "encoded fill-overlay metadata does not match rendered CSS"
    has_normalized_overlay = normalized_overlay is not None
    authored_overlay = (
        parse_fill_overlay_effect(
            styles.get("backgroundImage"),
            blend_mode,
            background_color=styles.get("backgroundColor"),
            background_size=styles.get("backgroundSize"),
            background_position=styles.get("backgroundPosition"),
            background_repeat=styles.get("backgroundRepeat"),
            background_origin=styles.get("backgroundOrigin"),
            background_clip=styles.get("backgroundClip"),
        )
        if encoded_overlay is None
        else None
    )
    over_overlay = (
        encoded_overlay
        if encoded_overlay is not None and encoded_overlay.blend == "over"
        else authored_overlay
        if authored_overlay is not None and authored_overlay.blend == "over"
        else None
    )
    if over_overlay is not None and (
        clip not in ("none", "")
        or _opacity(styles) != 1.0
        or bool(node.text or node.text_runs)
        or any(side is not None for side in _resolve_border_sides(styles)[0])
        or (encoded_effects is not None and len(encoded_effects) != 1)
        or (
            encoded_effects is None
            and (
                bool(parse_shadows(styles.get("boxShadow")))
                or parse_blur_filter(styles.get("filter")) is not None
                or parse_soft_edge_mask(
                    styles.get("maskImage"),
                    styles.get("maskComposite"),
                    repeat=styles.get("maskRepeat"),
                    position=styles.get("maskPosition"),
                    size=styles.get("maskSize"),
                    origin=styles.get("maskOrigin"),
                    clip=styles.get("maskClip"),
                    mode=styles.get("maskMode"),
                    ellipse=False,
                )
                is not None
                or parse_box_reflection(styles.get("webkitBoxReflect")) is not None
            )
        )
        or (
            styles.get("transform", "none") not in ("none", "")
            and _parse_transform(styles) is not None
        )
        or parse_radius_px(
            styles.get("borderRadius"),
            shorter_side_px=min(node.width, node.height),
        )
        > 0
    ):
        return "CSS normal fill overlay is only typed for square-cornered rectangles"
    if blend_mode not in ("normal", "") and authored_overlay is None and not has_normalized_overlay:
        return "background-blend-mode has no native fill-overlay mapping"
    if styles.get("backdropFilter", "none") not in ("none", ""):
        return "backdrop-filter has no native mapping"
    filter_value = styles.get("filter", "none")
    if filter_value not in ("none", "") and parse_blur_filter(filter_value) is None:
        return "CSS filter has no native mapping"
    mask_value = styles.get("maskImage", "none")
    mask_corner = px_to_emu(
        parse_radius_px(styles.get("borderRadius"), shorter_side_px=min(node.width, node.height))
    )
    if (
        mask_value not in ("none", "")
        and parse_soft_edge_mask(
            mask_value,
            styles.get("maskComposite"),
            repeat=styles.get("maskRepeat"),
            position=styles.get("maskPosition"),
            size=styles.get("maskSize"),
            origin=styles.get("maskOrigin"),
            clip=styles.get("maskClip"),
            mode=styles.get("maskMode"),
            ellipse=_geometry(_box(node), mask_corner) == "ellipse",
        )
        is None
    ):
        return "CSS mask has no native mapping"
    reflection_value = styles.get("webkitBoxReflect", "none")
    if reflection_value not in ("none", "") and parse_box_reflection(reflection_value) is None:
        return "CSS box reflection has no native mapping"
    shadows = parse_shadows(styles.get("boxShadow"))
    all_outer_sibling_graph = all(
        not shadow.inset and shadow.distance_emu != 0 for shadow in shadows
    )
    mixed_effect_list = (
        len(shadows) == 2
        and sum(shadow.inset for shadow in shadows) == 1
        and all(shadow.inset or shadow.distance_emu != 0 for shadow in shadows)
    )
    mixed_schema_subset = (
        len(shadows) > 2
        and any(shadow.inset for shadow in shadows)
        and any(not shadow.inset for shadow in shadows)
    )
    retained_schema_subset = (
        encoded_effect_payload is not None
        and encoded_effect_payload.native_projection == "schema_subset"
    )
    if len(shadows) > 1 and not (
        all_outer_sibling_graph
        or mixed_effect_list
        or mixed_schema_subset
        or retained_schema_subset
    ):
        return "mixed multiple box-shadow layers have no proven DrawingML effect graph"
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

    ``background-size: cover`` and oversized explicit sizes produce a source-rect crop (a window
    of the source shown stretched to fill the shape). ``contain`` and undersized explicit sizes
    letter-box the whole image, which a blip ``a:srcRect`` cannot express, so those fall through
    with no crop. Returns ``None`` when no crop applies or the image cannot be measured.
    """
    if node.width <= 0 or node.height <= 0:
        return None
    mode, explicit = parse_background_size(
        node.styles.get("backgroundSize"),
        box_width_px=node.width,
        box_height_px=node.height,
    )
    pos_x, pos_y = parse_background_position(node.styles.get("backgroundPosition"))
    if mode == "cover":
        dims = image_dimensions(data)
        if dims is None:
            return None
        img_w, img_h = dims
        crop = cover_crop_fractions(img_w, img_h, node.width, node.height, pos_x=pos_x, pos_y=pos_y)
    elif mode == "explicit" and explicit is not None:
        crop = explicit_crop_fractions(
            explicit[0], explicit[1], node.width, node.height, pos_x=pos_x, pos_y=pos_y
        )
    else:
        return None
    left, top, right, bottom = crop
    if left <= 0 and top <= 0 and right <= 0 and bottom <= 0:
        return None
    return SrcRect(left=left, top=top, right=right, bottom=bottom)


def _resolve_fill(node: RenderedNode, rendered: RenderedSlide) -> tuple[Fill | None, str | None]:
    """Resolve a node's fill. Returns ``(fill, raster_reason)``; a non-``None`` reason means
    the fill can't be expressed natively and the element must rasterise."""
    styles = node.styles

    if node.tag == "path":
        svg_fill = styles.get("fill", "none").strip().lower()
        if svg_fill not in {"", "none"}:
            color = parse_color(svg_fill)
            if color is None:
                return None, "SVG fill paint has no native mapping"
            if color.a > 0:
                return SolidFill(color=color), None

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
    encoded_effects = decode_effects(styles.get("domoxmlEffects"))
    encoded_overlay = next(
        (effect for effect in (encoded_effects or ()) if isinstance(effect, FillOverlay)),
        None,
    )
    if encoded_overlay is not None:
        base_styles = fill_overlay_base_styles(
            background_image,
            styles.get("backgroundBlendMode"),
            encoded_overlay,
            background_color=styles.get("backgroundColor"),
            background_size=styles.get("backgroundSize"),
            background_position=styles.get("backgroundPosition"),
            background_repeat=styles.get("backgroundRepeat"),
            background_origin=styles.get("backgroundOrigin"),
            background_clip=styles.get("backgroundClip"),
        )
        if base_styles is None:
            return None, "encoded fill-overlay metadata does not match rendered CSS"
        styles = {**styles, **base_styles}
        background_image = styles["backgroundImage"]
    else:
        fill_overlay = parse_fill_overlay_effect(
            background_image,
            styles.get("backgroundBlendMode"),
            background_color=styles.get("backgroundColor"),
            background_size=styles.get("backgroundSize"),
            background_position=styles.get("backgroundPosition"),
            background_repeat=styles.get("backgroundRepeat"),
            background_origin=styles.get("backgroundOrigin"),
            background_clip=styles.get("backgroundClip"),
        )
        if fill_overlay is not None:
            base_styles = fill_overlay_base_styles(
                background_image,
                styles.get("backgroundBlendMode"),
                fill_overlay,
                background_color=styles.get("backgroundColor"),
                background_size=styles.get("backgroundSize"),
                background_position=styles.get("backgroundPosition"),
                background_repeat=styles.get("backgroundRepeat"),
                background_origin=styles.get("backgroundOrigin"),
                background_clip=styles.get("backgroundClip"),
            )
            if base_styles is None:
                return None, "authored fill-overlay metadata does not match rendered CSS"
            styles = {**styles, **base_styles}
            background_image = styles["backgroundImage"]

    # Check for url(...) first, before checking for gradient keywords
    if "url(" in background_image:
        match = _URL_RE.search(background_image)
        resolved = _resolve_image_bytes(match.group(1), rendered) if match else None
        if resolved is None:
            return None, "background image was not captured"
        data, ext = resolved
        crop = _background_crop(data, node.model_copy(update={"styles": styles}))
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


def _resolve_svg_line(styles: dict[str, str]) -> tuple[Line | None, str | None]:
    """Resolve a solid SVG stroke into a native DrawingML line."""
    stroke = styles.get("stroke", "none").strip().lower()
    if stroke in {"", "none"}:
        return None, None
    color = parse_color(stroke)
    if color is None:
        return None, "SVG stroke paint has no native mapping"
    width_px = parse_length_px(styles.get("strokeWidth"))
    if color.a <= 0 or width_px <= 0:
        return None, None
    dasharray = styles.get("strokeDasharray", "none").strip().lower()
    dash = "solid"
    if dasharray not in {"", "none"}:
        parsed_dash = parse_svg_dasharray(dasharray, width_px)
        if parsed_dash is None:
            return None, "SVG custom dash array has no native mapping"
        dash = parsed_dash
    cap_token = styles.get("strokeLinecap", "butt")
    cap: Literal["flat", "round", "square"] = (
        "round" if cap_token == "round" else "square" if cap_token == "square" else "flat"
    )
    join_token = styles.get("strokeLinejoin", "round")
    join: Literal["round", "bevel", "miter"] = (
        "bevel" if join_token == "bevel" else "miter" if join_token == "miter" else "round"
    )
    return Line(
        color=color,
        width_emu=px_to_emu(width_px),
        dash=dash,
        cap=cap,
        join=join,
    ), None


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
) -> list[tuple[str, ShapeNode]]:
    """Emit up to 4 thin solid rects that reproduce CSS per-side borders.

    Layout convention (matches CSS border-box painting model):
    - top/bottom span the full width of the element.
    - left/right are clipped vertically to the space between top and bottom borders, to
      avoid double-painting corners.
    """
    rects: list[tuple[str, ShapeNode]] = []
    top_w = top.width_emu if top is not None else 0
    bot_w = bottom.width_emu if bottom is not None else 0
    if top is not None:
        rects.append(
            (
                "border-top",
                _make_side_rect(
                    Box(x=base_box.x, y=base_box.y, width=base_box.width, height=top_w),
                    SolidFill(color=top.color),
                ),
            )
        )
    if bottom is not None:
        rects.append(
            (
                "border-bottom",
                _make_side_rect(
                    Box(
                        x=base_box.x,
                        y=base_box.y + base_box.height - bot_w,
                        width=base_box.width,
                        height=bot_w,
                    ),
                    SolidFill(color=bottom.color),
                ),
            )
        )
    interior_y = base_box.y + top_w
    interior_h = base_box.height - top_w - bot_w
    if left is not None and interior_h > 0:
        rects.append(
            (
                "border-left",
                _make_side_rect(
                    Box(x=base_box.x, y=interior_y, width=left.width_emu, height=interior_h),
                    SolidFill(color=left.color),
                ),
            )
        )
    if right is not None and interior_h > 0:
        rects.append(
            (
                "border-right",
                _make_side_rect(
                    Box(
                        x=base_box.x + base_box.width - right.width_emu,
                        y=interior_y,
                        width=right.width_emu,
                        height=interior_h,
                    ),
                    SolidFill(color=right.color),
                ),
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
        return shadow.model_copy(
            update={"blur_emu": round(shadow.blur_emu * BOX_SHADOW_BLUR_TO_DML)}
        )
    return shadow


def _custom_drop_shadow_to_effect(shadow: Shadow) -> Shadow | Glow:
    """Calibrate one path-aware CSS drop shadow for PowerPoint and LibreOffice."""
    if shadow.distance_emu == 0:
        return Glow(
            color=shadow.color.model_copy(update={"a": shadow.color.a * CUSTOM_GLOW_ALPHA_TO_DML}),
            radius_emu=round(shadow.blur_emu * CUSTOM_GLOW_RADIUS_TO_DML),
        )
    return shadow.model_copy(
        update={
            "blur_emu": round(shadow.blur_emu * CUSTOM_SHADOW_BLUR_TO_DML),
            "color": shadow.color.model_copy(
                update={"a": shadow.color.a * CUSTOM_SHADOW_ALPHA_TO_DML}
            ),
        }
    )


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
        and node.styles.get("filter", "none") in ("none", "")
        and node.styles.get("maskImage", "none") in ("none", "")
        and node.styles.get("webkitBoxReflect", "none") in ("none", "")
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


def _native_coverage(element: str) -> CoverageItem:
    return CoverageItem(
        element=element,
        representation=Representation.NATIVE,
        editability=Editability.SEMANTIC,
    )


def _element_layer_coverage(element: str, shape: ShapeNode, reason: str) -> CoverageItem:
    return CoverageItem(
        element=element,
        representation=Representation.ELEMENT_LAYER,
        editability=Editability.LAYERS,
        raster_area_emu2=shape.box.width * shape.box.height,
        reason=reason,
    )


def _failed_coverage(element: str, reason: str) -> CoverageItem:
    return CoverageItem(
        element=element,
        representation=Representation.FAILED,
        editability=Editability.NONE,
        source_retention=SourceRetention.LOST,
        output_count=0,
        reason=f"{reason}; rasterization returned an empty region",
    )


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


def _restore_group_child(
    child: ShapeNode | GroupNode | Connector,
    group: GroupNode,
    original: GroupMemberPayload | None,
) -> ShapeNode | GroupNode | Connector:
    """Invert the HTML flattening map from slide space into the group's child space."""
    provenance = child.provenance
    if provenance is not None and provenance.owner_node_id is None:
        provenance = provenance.model_copy(update={"owner_node_id": group.node_id})
    if isinstance(child, Connector):
        if original is None or original.start is None or original.end is None:
            return child.model_copy(update={"provenance": provenance})
        return child.model_copy(
            update={
                "start": original.start,
                "end": original.end,
                "provenance": provenance,
            }
        )
    if original is not None and original.box is not None:
        restored = original.box
    else:
        scale_x = group.box.width / group.child_box.width
        scale_y = group.box.height / group.child_box.height
        box = child.box
        restored = Box(
            x=round(group.child_box.x + (box.x - group.box.x) / scale_x),
            y=round(group.child_box.y + (box.y - group.box.y) / scale_y),
            width=round(box.width / scale_x),
            height=round(box.height / scale_y),
        )
    return child.model_copy(update={"box": restored, "provenance": provenance})


def _group_projection_is_fresh(source: RenderedNode, member: GroupMemberPayload) -> bool:
    """Whether the captured member still matches the geometry that the payload describes."""
    expected = member.projected_box
    if expected is None:
        return False
    keys = (
        "domoxmlGroupLayoutLeft",
        "domoxmlGroupLayoutTop",
        "domoxmlGroupLayoutWidth",
        "domoxmlGroupLayoutHeight",
    )
    raw = tuple(source.styles.get(key) for key in keys)
    if any(not value for value in raw):
        return False
    captured = tuple(parse_length_px(value) for value in raw)
    expected_values = (expected.x, expected.y, expected.width, expected.height)
    tolerance = px_to_emu(1 / 32)
    return all(
        abs(px_to_emu(value) - wanted) <= tolerance
        for value, wanted in zip(captured, expected_values, strict=True)
    )


def _group_wrapper_projection_is_fresh(source: RenderedNode, payload: GroupPayload) -> bool:
    """Whether the normalized wrapper still represents the encoded group projection."""
    transform_value = source.styles.get("transform")
    if is_complex_transform(transform_value) or _transform_has_translation(transform_value):
        return False
    actual_transform = _parse_transform(source.styles)
    if source.styles.get("display") == "contents":
        return payload.transform is None and actual_transform is None

    keys = (
        "domoxmlGroupWrapperLeft",
        "domoxmlGroupWrapperTop",
        "domoxmlGroupWrapperWidth",
        "domoxmlGroupWrapperHeight",
    )
    raw = tuple(source.styles.get(key) for key in keys)
    if any(not value for value in raw):
        return False
    captured = tuple(parse_length_px(value) for value in raw)
    expected_values = (
        payload.box.x,
        payload.box.y,
        payload.box.width,
        payload.box.height,
    )
    tolerance = px_to_emu(1 / 32)
    if not all(
        abs(px_to_emu(value) - wanted) <= tolerance
        for value, wanted in zip(captured, expected_values, strict=True)
    ):
        return False

    expected_transform = payload.transform
    if expected_transform is None or actual_transform is None:
        return expected_transform is actual_transform
    if (
        abs(expected_transform.rotation_deg - actual_transform.rotation_deg) > 0.001
        or expected_transform.flip_h != actual_transform.flip_h
        or expected_transform.flip_v != actual_transform.flip_v
    ):
        return False
    origin = source.styles.get("transformOrigin", "").split()
    if len(origin) < 2:
        return False
    return (
        abs(px_to_emu(parse_length_px(origin[0])) - payload.box.width / 2) <= tolerance
        and abs(px_to_emu(parse_length_px(origin[1])) - payload.box.height / 2) <= tolerance
    )


def _transform_has_translation(value: str | None) -> bool:
    """Return whether a CSS transform includes translation that group metadata cannot restore."""
    if not value or value == "none":
        return False
    lowered = value.strip().lower()
    if lowered.startswith("matrix(") and lowered.endswith(")"):
        try:
            components = tuple(
                float(component.strip())
                for component in lowered.removeprefix("matrix(").removesuffix(")").split(",")
            )
        except ValueError:
            return True
        return len(components) != 6 or abs(components[4]) > 1e-6 or abs(components[5]) > 1e-6
    return "translate" in lowered


def _reconstruct_groups(
    nodes: tuple[RenderedNode, ...],
    contents: list[Node],
    coverage: list[CoverageItem],
    identities: _IdentityAllocator,
) -> tuple[list[Node], list[CoverageItem], tuple[ConversionWarning, ...]]:
    """Replace normalized-HTML group children with their canonical ``GroupNode`` owner."""
    group_sources = [node for node in nodes if node.styles.get("domoxmlGroup")]
    extra_warnings: list[ConversionWarning] = []
    for source in reversed(group_sources):
        payload = decode_group_payload(source.styles.get("domoxmlGroup"))
        if (
            payload is None
            or payload.box.width <= 0
            or payload.box.height <= 0
            or payload.child_box.width <= 0
            or payload.child_box.height <= 0
        ):
            extra_warnings.append(
                ConversionWarning(
                    message="invalid normalized group payload; children left flattened",
                    element=_label(source),
                )
            )
            continue
        direct_sources = [node for node in nodes if node.parent == source.index]
        member_ids = [
            member_id
            for child in direct_sources
            if (member_id := child.styles.get("domoxmlNodeId", "").strip())
        ]
        if len(member_ids) != len(direct_sources):
            extra_warnings.append(
                ConversionWarning(
                    message=(
                        "normalized group member is missing stable identity; "
                        "children left flattened"
                    ),
                    element=_label(source),
                )
            )
            continue
        positions = [
            index for index, candidate in enumerate(contents) if candidate.node_id in member_ids
        ]
        if len(positions) != len(member_ids) or not positions:
            extra_warnings.append(
                ConversionWarning(
                    message=(
                        "normalized group members could not be recovered exactly; "
                        "children left flattened"
                    ),
                    element=_label(source),
                )
            )
            continue
        member_labels = [_label(child) for child in direct_sources]
        coverage_positions = [
            index for index, item in enumerate(coverage) if item.element in member_labels
        ]
        member_coverage = [coverage[index] for index in coverage_positions]
        if len(coverage_positions) != len(direct_sources) or any(
            item.representation is not Representation.NATIVE or item.output_count != 1
            for item in member_coverage
        ):
            extra_warnings.append(
                ConversionWarning(
                    message=(
                        "normalized group members did not retain exact native mappings; "
                        "children left flattened"
                    ),
                    element=_label(source),
                )
            )
            continue
        members = [contents[position] for position in positions]
        group_members = [
            member for member in members if isinstance(member, ShapeNode | GroupNode | Connector)
        ]
        if len(group_members) != len(members):
            extra_warnings.append(
                ConversionWarning(
                    message=(
                        "normalized group contains an unsupported child; children left flattened"
                    ),
                    element=_label(source),
                )
            )
            continue
        original_members = {member.node_id: member for member in payload.members}
        stale_members = [
            child
            for child in direct_sources
            if (member_id := child.styles.get("domoxmlNodeId", "").strip())
            and (
                (original := original_members.get(member_id)) is None
                or not _group_projection_is_fresh(child, original)
            )
        ]
        if stale_members or not _group_wrapper_projection_is_fresh(source, payload):
            reason = (
                "normalized group or member projection changed after metadata was written; "
                "visible members left flattened"
            )
            extra_warnings.append(ConversionWarning(message=reason, element=_label(source)))
            for position in coverage_positions:
                coverage[position] = coverage[position].model_copy(
                    update={
                        "representation": Representation.APPROXIMATED,
                        "editability": Editability.COMPONENTS,
                        "reason": reason,
                    }
                )
            continue
        shell = identities.apply(
            GroupNode(
                box=payload.box,
                child_box=payload.child_box,
                transform=payload.transform,
            ),
            source,
        )
        restored_children = tuple(
            _restore_group_child(member, shell, original_members.get(member.node_id or ""))
            for member in group_members
        )
        group = shell.model_copy(update={"children": restored_children})
        first = min(positions)
        for position in sorted(positions, reverse=True):
            contents.pop(position)
        contents.insert(first, group)
        first_coverage = min(coverage_positions)
        for position in sorted(coverage_positions, reverse=True):
            coverage.pop(position)
        coverage.insert(first_coverage, _native_coverage(_label(source)))
    return contents, coverage, tuple(extra_warnings)


def extract_slide(rendered: RenderedSlide) -> ExtractResult:
    """Map every captured node to native OOXML where possible, rasterising only the residue.

    Stacking follows DOM order; a rasterised element consumes its whole subtree so its
    children aren't drawn twice over the baked-in pixels.
    """
    children = _children(rendered.nodes)
    consumed: set[int] = set()
    contents: list[Node] = []
    coverage: list[CoverageItem] = []
    warnings: list[ConversionWarning] = []
    identities = _IdentityAllocator(rendered.nodes)

    slide_root, transition, background = extract_slide_properties(
        rendered.nodes, lambda node: _resolve_fill(node, rendered)
    )
    fallback_node = next(
        (
            node
            for node in rendered.nodes
            if node.styles.get("domoxmlSlideFallback") == "rasterized"
        ),
        None,
    )
    renderer_fallback: PictureFill | None = None
    renderer_fallback_owner_node_id: str | None = None
    renderer_fallback_owner_found = False
    if fallback_node is not None:
        fallback_fill, fallback_reason = _resolve_fill(fallback_node, rendered)
        if isinstance(fallback_fill, PictureFill):
            renderer_fallback = fallback_fill.model_copy(
                update={"raster_role": "pptx-slide-rasterized"}
            )
            renderer_fallback_owner_node_id = fallback_node.styles.get("domoxmlOwnerNodeId")
            consumed |= _subtree(fallback_node.index, children)
        else:
            reason = fallback_reason or "slide renderer fallback image could not be recovered"
            warnings.append(ConversionWarning(message=reason, element=_label(fallback_node)))

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

        # Normalized group wrappers carry structural metadata but no independent paint.
        # Their direct children remain eligible for extraction and are consolidated below.
        if node.styles.get("domoxmlGroup"):
            continue

        preserved_payload = node.styles.get("domoxmlPreservedPayload")
        if preserved_payload:
            label = _label(node)
            try:
                payload = decode_payload(preserved_payload)
            except (ValueError, TypeError):
                consumed |= _subtree(node.index, children)
                reason = "invalid attached preservation payload"
                coverage.append(_failed_coverage(label, reason))
                warnings.append(ConversionWarning(message=reason, element=label))
            else:
                fallback_fill, fallback_reason = _resolve_fill(node, rendered)
                fallback = fallback_fill if isinstance(fallback_fill, PictureFill) else None
                fallback_representation: Literal["element_layer", "rasterized"] = (
                    "rasterized"
                    if node.styles.get("domoxmlRepresentation") == "rasterized"
                    else "element_layer"
                )
                preserved_node = identities.apply(
                    PreservedNode(
                        box=_box(node),
                        payload=payload,
                        fallback=fallback,
                        fallback_representation=fallback_representation,
                    ),
                    node,
                )
                contents.append(preserved_node)
                owned_by_renderer_fallback = (
                    renderer_fallback is not None
                    and renderer_fallback_owner_node_id is not None
                    and preserved_node.node_id == renderer_fallback_owner_node_id
                )
                renderer_fallback_owner_found |= owned_by_renderer_fallback
                consumed |= _subtree(node.index, children)
                if fallback is not None:
                    box = _box(node)
                    coverage.append(
                        CoverageItem(
                            element=label,
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
                            source_retention=SourceRetention.ATTACHED,
                            raster_area_emu2=box.width * box.height,
                            reason=(
                                "renderer-derived fallback is not independently editable"
                                if fallback_representation == "rasterized"
                                else "renderer-derived fallback for attached source object"
                            ),
                        )
                    )
                elif not owned_by_renderer_fallback:
                    reason = fallback_reason or "attached source object has no visual fallback"
                    coverage.append(
                        CoverageItem(
                            element=label,
                            representation=Representation.FAILED,
                            editability=Editability.NONE,
                            source_retention=SourceRetention.ATTACHED,
                            output_count=0,
                            reason=reason,
                        )
                    )
                    warnings.append(ConversionWarning(message=reason, element=label))
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
                geometry = decode_table_geometry(node.styles.get("domoxmlTableGeometry"))
                if (
                    geometry is not None
                    and len(geometry.col_widths_emu) == len(table.col_widths_emu)
                    and len(geometry.row_heights_emu) == len(table.rows)
                ):
                    table = apply_table_geometry(table, geometry)
                contents.append(identities.apply(table, node))
                consumed |= _subtree(node.index, children)
                coverage.append(_native_coverage(_label(node)))
                continue

        # --- SVG custom-geometry interception ---
        # An inline <svg> with exactly one <path> child whose d attribute was captured
        # can be converted to a native a:custGeom instead of being rasterised.
        if node.tag == "svg":
            connector = extract_connector(node, None, None)
            if connector is not None:
                contents.append(identities.apply(connector, node))
                consumed |= _subtree(node.index, children)
                coverage.append(_native_coverage(_label(node)))
                continue
            svg = extract_custom_geometry(
                node,
                rendered.nodes,
                children,
                encoded_geometry=decode_custom_geometry(node.styles.get("domoxmlCustomGeometry")),
            )
            if svg.warning is not None:
                warnings.append(svg.warning)
            if svg.geometry is not None:
                fill_node = svg.style_node
                fill, fill_reason = _resolve_fill(fill_node, rendered)
                line, line_reason = _resolve_svg_line(fill_node.styles)
                box = _box(node)
                encoded_effect_payload = decode_effect_payload(node.styles.get("domoxmlEffects"))
                encoded_effects = (
                    encoded_effect_payload.effects if encoded_effect_payload is not None else None
                )
                filter_styles = node.styles
                filter_value = filter_styles.get("filter", "none")
                if filter_value in ("none", ""):
                    filter_styles = fill_node.styles
                    filter_value = filter_styles.get("filter", "none")
                reflection_value = node.styles.get("webkitBoxReflect", "none")
                if reflection_value in ("none", ""):
                    reflection_value = fill_node.styles.get("webkitBoxReflect", "none")
                drop_shadow = (
                    parse_drop_shadow_filter(filter_value) if encoded_effects is None else None
                )
                blur = parse_blur_filter(filter_value) if encoded_effects is None else None
                svg_soft_edge = (
                    parse_svg_soft_edge_filter(filter_styles.get("domoxmlSvgFilter"))
                    if encoded_effects is None
                    else None
                )
                svg_fill_overlay = (
                    parse_svg_fill_overlay_filter(filter_styles.get("domoxmlSvgFilter"))
                    if encoded_effects is None
                    else None
                )
                reflection = (
                    parse_box_reflection(reflection_value) if encoded_effects is None else None
                )
                effect_reason: str | None = None
                if (
                    encoded_effects is None
                    and filter_value not in ("none", "")
                    and drop_shadow is None
                    and blur is None
                    and svg_soft_edge is None
                    and svg_fill_overlay is None
                ):
                    effect_reason = "SVG CSS filter has no native custom-geometry mapping"
                if (
                    encoded_effects is None
                    and reflection_value not in ("none", "")
                    and reflection is None
                ):
                    effect_reason = "SVG CSS reflection has no native custom-geometry mapping"
                authored_filter_effects = tuple(
                    effect
                    for effect in (drop_shadow, blur, svg_soft_edge, svg_fill_overlay)
                    if effect is not None
                )
                if reflection is not None and authored_filter_effects:
                    effect_reason = (
                        "compound SVG filter and reflection ordering has no native "
                        "custom-geometry mapping"
                    )
                effects = (
                    encoded_effects
                    if encoded_effects is not None
                    else (
                        (_custom_drop_shadow_to_effect(drop_shadow),)
                        if drop_shadow is not None
                        else (blur,)
                        if blur is not None
                        else (svg_soft_edge,)
                        if svg_soft_edge is not None
                        else (svg_fill_overlay,)
                        if svg_fill_overlay is not None
                        else (reflection,)
                        if reflection is not None
                        else ()
                    )
                )
                fallback_shape = (
                    _raster_shape(node, rendered)
                    if (
                        node.styles.get("domoxmlRasterBounds")
                        or blur is not None
                        or svg_soft_edge is not None
                        or svg_fill_overlay is not None
                        or reflection is not None
                    )
                    else None
                )
                portable_fallback = (
                    PortableFallback(
                        box=fallback_shape.box,
                        picture=fallback_shape.fill.model_copy(
                            update={"raster_role": "portable-effect-fallback"}
                        ),
                    )
                    if fallback_shape is not None and isinstance(fallback_shape.fill, PictureFill)
                    else None
                )
                if (
                    blur is not None
                    or svg_soft_edge is not None
                    or svg_fill_overlay is not None
                    or reflection is not None
                ) and portable_fallback is None:
                    effect_reason = (
                        "SVG effect requires an exact owned renderer fallback, "
                        "but rasterization returned no region"
                    )
                paint_reason = fill_reason or line_reason or effect_reason
                if paint_reason is not None:
                    label = _label(node)
                    shape = _raster_shape(node, rendered)
                    consumed |= _subtree(node.index, children)
                    raster_reason = f"SVG custom geometry paint cannot map natively: {paint_reason}"
                    if shape is None:
                        coverage.append(_failed_coverage(label, raster_reason))
                        warnings.append(
                            ConversionWarning(
                                message=f"dropped — empty raster region ({raster_reason})",
                                element=label,
                            )
                        )
                    else:
                        contents.append(identities.apply(shape, node))
                        coverage.append(_element_layer_coverage(label, shape, raster_reason))
                        warnings.append(
                            ConversionWarning(
                                message=f"rasterised — {raster_reason}", element=label
                            )
                        )
                    continue
                if (
                    blur is not None
                    or svg_soft_edge is not None
                    or svg_fill_overlay is not None
                    or reflection is not None
                ) and portable_fallback is not None:
                    effect_name = (
                        "blur"
                        if blur is not None
                        else "soft edge"
                        if svg_soft_edge is not None
                        else "fill overlay"
                        if svg_fill_overlay is not None
                        else "reflection"
                    )
                    native_name = (
                        "a:blur"
                        if blur is not None
                        else "a:softEdge"
                        if svg_soft_edge is not None
                        else "a:fillOverlay"
                        if svg_fill_overlay is not None
                        else "a:reflection"
                    )
                    warnings.append(
                        ConversionWarning(
                            message=(
                                f"SVG {effect_name} emitted as editable native {native_name} "
                                "with an exact "
                                "custom-geometry-owned renderer fallback"
                            ),
                            element=_label(node),
                        )
                    )
                # Build the ShapeNode with custom_geom
                contents.append(
                    identities.apply(
                        ShapeNode(
                            box=box,
                            custom_geom=svg.geometry,
                            fill=fill,
                            line=line,
                            effects=effects,
                            effect_container=(
                                encoded_effect_payload.container
                                if encoded_effect_payload is not None
                                else "list"
                            ),
                            effect_source_ref=(
                                encoded_effect_payload.source_ref
                                if encoded_effect_payload is not None
                                else "fillLine"
                                if line is not None
                                else "fill"
                            ),
                            native_effect_projection=(
                                encoded_effect_payload.native_projection
                                if encoded_effect_payload is not None
                                else "complete"
                            ),
                            portable_fallback=portable_fallback,
                        ),
                        node,
                    )
                )
                consumed |= _subtree(node.index, children)
                if portable_fallback is None:
                    coverage.append(_native_coverage(_label(node)))
                else:
                    coverage.append(
                        CoverageItem(
                            element=_label(node),
                            representation=Representation.HYBRID,
                            editability=Editability.COMPONENTS,
                            output_count=2,
                            raster_area_emu2=(
                                portable_fallback.box.width * portable_fallback.box.height
                            ),
                            reason=(
                                "editable native custom geometry with an exact owned effect layer"
                            ),
                        )
                    )
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
                    coverage.append(_failed_coverage(label, raster_reason))
                else:
                    contents.append(identities.apply(shape, node))
                    coverage.append(_element_layer_coverage(label, shape, raster_reason))
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
                coverage.append(_failed_coverage(label, reason))
                continue
            contents.append(identities.apply(shape, node))
            coverage.append(_element_layer_coverage(label, shape, reason))
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
                side_rect_shapes = [
                    identities.apply(shape, node, role=role)
                    for role, shape in _decompose_per_side(
                        box, side_top, side_right, side_bottom, side_left
                    )
                ]
                line_warning = line_warning or ConversionWarning(
                    message="non-uniform border decomposed into per-side rects"
                )
            else:
                # border-radius + non-uniform: native decomposition is not possible —
                # rounded borders can't be reproduced with flat rects.
                line = max(present_sides, key=lambda s: s.width_emu)
                warn_msgs.append(
                    "non-uniform border with border-radius approximated by one outline"
                )
                line_warning = line_warning or ConversionWarning(
                    message="non-uniform border with border-radius approximated by one outline"
                )

        # --- HR / thin-element connector detection ---
        # Check before emitting a ShapeNode; <hr> and thin unfilled elements become Connectors.
        connector_line = line
        if node.tag == "hr" and connector_line is None and present_sides:
            connector_line = max(present_sides, key=lambda side: side.width_emu)
        connector = extract_connector(node, fill, connector_line)
        if connector is not None:
            contents.append(identities.apply(connector, node))
            consumed.add(node.index)
            if warn_msgs:
                coverage.append(
                    CoverageItem(
                        element=_label(node),
                        representation=Representation.APPROXIMATED,
                        editability=Editability.SEMANTIC,
                        reason="; ".join(dict.fromkeys(warn_msgs)),
                    )
                )
                if line_warning is not None:
                    warnings.append(line_warning.model_copy(update={"element": _label(node)}))
            else:
                coverage.append(_native_coverage(_label(node)))
            continue

        if _is_plain_inline(node, fill, line):
            coverage.append(_native_coverage(_label(node)))
            continue
        encoded_text = decode_text_body(node.styles.get("domoxmlTextPayload"))
        text = _text_body_from_decoded(node, encoded_text)
        approximation_reasons = list(warn_msgs)
        if (
            text is not None
            and text.columns > 1
            and (node.styles.get("columnFill") or "balance") != "auto"
        ):
            approximation_reasons.append(
                "balanced CSS columns approximated as sequential PowerPoint columns"
            )
            warnings.append(
                ConversionWarning(
                    message=("balanced CSS columns approximated as sequential PowerPoint columns"),
                    element=_label(node),
                )
            )
        if text is not None and fill is None and line is None and encoded_text is None:
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
        encoded_effect_payload = decode_effect_payload(node.styles.get("domoxmlEffects"))
        encoded_effects = (
            encoded_effect_payload.effects if encoded_effect_payload is not None else None
        )
        shadows = parse_shadows(node.styles.get("boxShadow")) if encoded_effects is None else ()
        blur = parse_blur_filter(node.styles.get("filter")) if encoded_effects is None else None
        soft_edge = (
            parse_soft_edge_mask(
                node.styles.get("maskImage"),
                node.styles.get("maskComposite"),
                repeat=node.styles.get("maskRepeat"),
                position=node.styles.get("maskPosition"),
                size=node.styles.get("maskSize"),
                origin=node.styles.get("maskOrigin"),
                clip=node.styles.get("maskClip"),
                mode=node.styles.get("maskMode"),
                ellipse=geom == "ellipse",
            )
            if encoded_effects is None
            else None
        )
        reflection = (
            parse_box_reflection(node.styles.get("webkitBoxReflect"))
            if encoded_effects is None
            else None
        )
        fill_overlay_effect = (
            parse_fill_overlay_effect(
                node.styles.get("backgroundImage"),
                node.styles.get("backgroundBlendMode"),
                background_color=node.styles.get("backgroundColor"),
                background_size=node.styles.get("backgroundSize"),
                background_position=node.styles.get("backgroundPosition"),
                background_repeat=node.styles.get("backgroundRepeat"),
                background_origin=node.styles.get("backgroundOrigin"),
                background_clip=node.styles.get("backgroundClip"),
            )
            if encoded_effects is None
            else None
        )
        effects = (
            encoded_effects
            if encoded_effects is not None
            else (
                ((blur,) if blur is not None else ())
                + ((soft_edge,) if soft_edge is not None else ())
                + ((reflection,) if reflection is not None else ())
                + ((fill_overlay_effect,) if fill_overlay_effect is not None else ())
                + tuple(_shadow_to_effect(shadow, box, warnings) for shadow in shadows)
            )
        )
        effect_container = (
            encoded_effect_payload.container
            if encoded_effect_payload is not None
            else "sibling"
            if len(shadows) > 1 and all(not shadow.inset for shadow in shadows)
            else "list"
        )
        effect_source_ref = (
            encoded_effect_payload.source_ref
            if encoded_effect_payload is not None
            else "fillLine"
            if line is not None
            else "fill"
        )
        native_effect_projection = (
            encoded_effect_payload.native_projection
            if encoded_effect_payload is not None
            else "schema_subset"
            if (
                len(shadows) > 2
                and any(shadow.inset for shadow in shadows)
                and any(not shadow.inset for shadow in shadows)
            )
            else "complete"
        )
        portable_fallback: PortableFallback | None = None
        portable_effects = tuple(
            effect
            for effect in effects
            if isinstance(effect, Blur | Reflection)
            or (isinstance(effect, Shadow) and effect.inset)
            or (isinstance(effect, SoftEdge) and effect.radius_emu > 0)
            or (
                isinstance(effect, FillOverlay)
                and (
                    isinstance(effect.fill, PatternFill)
                    or (isinstance(effect.fill, SolidFill) and effect.fill.color.a > 0.0)
                    or (
                        isinstance(effect.fill, GradientFill)
                        and any(stop.color.a > 0.0 for stop in effect.fill.stops)
                    )
                )
            )
        )
        if portable_effects or effect_container == "sibling":
            fallback_shape = _raster_shape(node, rendered)
            if fallback_shape is not None and isinstance(fallback_shape.fill, PictureFill):
                only_blur = len(effects) == 1 and isinstance(effects[0], Blur)
                effect_names = ", ".join(effect.kind for effect in effects)
                portable_fallback = PortableFallback(
                    box=fallback_shape.box,
                    picture=fallback_shape.fill.model_copy(
                        update={
                            "raster_role": (
                                "portable-blur-fallback"
                                if only_blur
                                else "portable-effect-fallback"
                            )
                        }
                    ),
                )
                warnings.append(
                    ConversionWarning(
                        message=(
                            "exact multi-layer CSS shadow intent retained with a schema-valid "
                            "native effect subset and an isolated renderer fallback"
                            if native_effect_projection == "schema_subset"
                            else (
                                "multiple CSS shadows emitted as editable native a:effectDag "
                                "with an isolated renderer fallback"
                            )
                            if effect_container == "sibling"
                            else (
                                "mixed CSS outer and inset shadows emitted as editable native "
                                "a:effectLst with an isolated renderer fallback"
                            )
                            if (
                                len(effects) == 2
                                and all(isinstance(effect, Shadow) for effect in effects)
                                and sum(
                                    effect.inset for effect in effects if isinstance(effect, Shadow)
                                )
                                == 1
                            )
                            else (
                                "CSS inset shadow emitted as editable native a:innerShdw "
                                "with an isolated renderer fallback"
                            )
                            if len(effects) == 1
                            and isinstance(effects[0], Shadow)
                            and effects[0].inset
                            else (
                                "CSS blur emitted as editable native a:blur with an isolated "
                                "renderer fallback"
                            )
                            if only_blur
                            else (
                                f"CSS {effect_names} emitted as editable native effect metadata "
                                "with an isolated renderer fallback"
                            )
                        ),
                        element=_label(node),
                    )
                )
        # Emit per-side border rects before the main shape so they appear behind its fill.
        contents.extend(side_rect_shapes)
        contents.append(
            identities.apply(
                ShapeNode(
                    box=box,
                    geom=geom,
                    fill=fill,
                    line=line,
                    effects=effects,
                    effect_container=effect_container,
                    effect_source_ref=effect_source_ref,
                    native_effect_projection=native_effect_projection,
                    portable_fallback=portable_fallback,
                    corner_radius_emu=corner,
                    opacity=_opacity(node.styles),
                    text=text,
                    transform=_parse_transform(node.styles),
                ),
                node,
            )
        )
        if node.styles.get("domoxmlConsolidatedText") == "true" or encoded_text is not None:
            consumed |= _subtree(node.index, children) - {node.index}
        if side_rect_shapes and not approximation_reasons:
            coverage.append(
                CoverageItem(
                    element=_label(node),
                    representation=Representation.DECOMPOSED,
                    editability=Editability.COMPONENTS,
                    output_count=1 + len(side_rect_shapes),
                    reason="non-uniform border decomposed into editable per-side rectangles",
                )
            )
        elif approximation_reasons:
            coverage.append(
                CoverageItem(
                    element=_label(node),
                    representation=Representation.APPROXIMATED,
                    editability=(
                        Editability.COMPONENTS if side_rect_shapes else Editability.SEMANTIC
                    ),
                    output_count=1 + len(side_rect_shapes),
                    reason="; ".join(dict.fromkeys(approximation_reasons)),
                )
            )
        elif portable_fallback is not None:
            effect_names = ", ".join(
                ("innerShdw" if effect.inset else "outerShdw")
                if isinstance(effect, Shadow)
                else effect.kind
                for effect in effects
            )
            coverage.append(
                CoverageItem(
                    element=_label(node),
                    representation=Representation.HYBRID,
                    editability=Editability.COMPONENTS,
                    output_count=2,
                    raster_area_emu2=(portable_fallback.box.width * portable_fallback.box.height),
                    reason=(
                        "editable schema-valid native subset with exact retained effect intent "
                        "and an isolated renderer fallback"
                        if native_effect_projection == "schema_subset"
                        else f"editable native {effect_names} with an isolated renderer fallback"
                    ),
                )
            )
        else:
            coverage.append(_native_coverage(_label(node)))
        if line_warning is not None:
            warnings.append(line_warning.model_copy(update={"element": _label(node)}))

    contents, coverage, group_warnings = _reconstruct_groups(
        rendered.nodes, contents, coverage, identities
    )
    warnings.extend(group_warnings)
    width = px_to_emu(rendered.width)
    height = px_to_emu(rendered.height)
    attached_owner_node_id: str | None = None
    if renderer_fallback is not None:
        attached_owner_node_id = (
            renderer_fallback_owner_node_id if renderer_fallback_owner_found else None
        )
        coverage.append(
            CoverageItem(
                element="slide:renderer-fallback",
                representation=Representation.RASTERIZED,
                editability=Editability.NONE,
                source_retention=(
                    SourceRetention.ATTACHED
                    if attached_owner_node_id is not None
                    else SourceRetention.DETACHED
                ),
                raster_area_emu2=width * height,
                reason=(
                    "authoritative full-slide renderer fallback above retained native contents"
                ),
            )
        )
    slide = SlideIR(
        width=width,
        height=height,
        contents=tuple(contents),
        transition=transition,
        background=background,
        renderer_fallback=renderer_fallback,
        renderer_fallback_owner_node_id=attached_owner_node_id,
    )
    return ExtractResult(slide=slide, coverage=tuple(coverage), warnings=tuple(warnings))
