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

from domoxml.core.images import ImageExt, crop_png, decode_data_uri, normalise_image
from domoxml.core.ir.model import (
    Box,
    Fill,
    GradientFill,
    Line,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.ir.parse import (
    is_bold,
    parse_border_side,
    parse_color,
    parse_gradient,
    parse_length_px,
    parse_shadow,
)
from domoxml.core.render.browser import RenderedNode, RenderedSlide, RenderedTextRun
from domoxml.core.units import px_to_emu, px_to_pt
from domoxml.types import ConversionWarning, CoverageItem, Disposition

_DEFAULT_TEXT_COLOR = Rgba(r=0, g=0, b=0)
_RASTER_TAGS = {"svg", "canvas", "video", "iframe"}
_URL_RE = re.compile(r"""url\(\s*['"]?(.*?)['"]?\s*\)""", re.IGNORECASE | re.DOTALL)
_MATRIX_RE = re.compile(r"matrix\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,")

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


def _text_run(text: str, styles: dict[str, str]) -> TextRun | None:
    if not text:
        return None
    return TextRun(
        text=text,
        font_family=(styles.get("fontFamily") or "sans-serif").split(",")[0].strip().strip("'\""),
        size_pt=px_to_pt(parse_length_px(styles.get("fontSize")) or 16.0),
        bold=is_bold(styles.get("fontWeight")),
        italic=styles.get("fontStyle", "normal") == "italic",
        color=parse_color(styles.get("color")) or _DEFAULT_TEXT_COLOR,
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
    return TextBody(
        paragraphs=tuple(TextParagraph(runs=tuple(runs), align=align) for runs in paragraphs)
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
    """True for rotation/skew/3-D transforms (a non-axis-aligned box we can't place natively).
    Pure translation is already baked into the captured bounding box, so it is fine."""
    if not value or value == "none":
        return False
    if value.startswith("matrix3d") or "rotate" in value or "skew" in value:
        return True
    match = _MATRIX_RE.search(value)
    if match is None:
        return False
    b, c = float(match.group(2)), float(match.group(3))
    return abs(b) > 1e-3 or abs(c) > 1e-3


def _structural_raster_reason(node: RenderedNode) -> str | None:
    """A reason this element can only be rasterised, independent of its fill, or ``None``."""
    styles = node.styles
    if node.tag in _RASTER_TAGS:
        return f"<{node.tag}> has no native OOXML mapping"
    if styles.get("clipPath", "none") not in ("none", ""):
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


def _resolve_line(styles: dict[str, str]) -> tuple[Line | None, ConversionWarning | None]:
    sides = [
        parse_border_side(
            styles.get(f"border{side}Width"),
            styles.get(f"border{side}Style"),
            styles.get(f"border{side}Color"),
        )
        for side in ("Top", "Right", "Bottom", "Left")
    ]
    present = [side for side in sides if side is not None]
    if not present:
        return None, None
    if len(present) == 4 and all(side == present[0] for side in present):
        return present[0], None
    # A single a:ln can't carry four different borders; approximate with the heaviest + warn.
    heaviest = max(present, key=lambda line: line.width_emu)
    return heaviest, ConversionWarning(message="non-uniform border approximated by one outline")


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
        line, line_warning = _resolve_line(node.styles)
        if _is_plain_inline(node, fill, line):
            coverage.append(CoverageItem(element=_label(node), disposition=Disposition.NATIVE))
            continue
        corner = px_to_emu(parse_length_px(node.styles.get("borderRadius")))
        shapes.append(
            ShapeNode(
                box=box,
                geom=_geometry(box, corner),
                fill=fill,
                line=line,
                shadow=parse_shadow(node.styles.get("boxShadow")),
                corner_radius_emu=corner,
                opacity=_opacity(node.styles),
                text=_text_body(node),
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
