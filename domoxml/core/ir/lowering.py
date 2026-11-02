"""Lower CSS paint features that are colour or alpha maths into plain fills, lines and shadows.

``filter`` colour functions, ``drop-shadow`` and a ``mask-image`` fade look like effects that need
pixels, but each reduces to a different colour, a shadow or an alpha ramp on content whose colours
are already known. That is only true for a *leaf*: an element with children paints them inside the
filter or mask too, and a per-element colour change differs from a per-pixel one where translucent
layers overlap. So nothing here applies to an element that has children.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

from domoxml.core.ir.filters import (
    COLOR_FUNCTIONS,
    FilterFunction,
    apply_to_color,
    is_lowerable,
    parse_filters,
)
from domoxml.core.ir.model import (
    Effect,
    Fill,
    Glow,
    GradientFill,
    GradientStop,
    Line,
    Rgba,
    Shadow,
    ShapeNode,
    SolidFill,
    TextBody,
    TextOutline,
    TextRun,
)
from domoxml.core.ir.parse import parse_gradient
from domoxml.core.render.browser import RenderedNode, RenderedSlide

LEAF = "domoxmlLeaf"
_MASK_DEFAULTS = {
    "maskSize": {"auto", "auto auto", ""},
    "maskPosition": {"0% 0%", "0% 0% 0% 0%", ""},
    "maskRepeat": {"repeat", ""},
    "maskMode": {"match-source", ""},
    "maskComposite": {"add", ""},
    "maskClip": {"border-box", ""},
    "maskOrigin": {"border-box", ""},
}


def mark_leaves(rendered: RenderedSlide) -> RenderedSlide:
    """``rendered`` with every node that has no child nodes flagged as a leaf."""
    parents = {node.parent for node in rendered.nodes}
    nodes = tuple(
        node.model_copy(update={"styles": {**node.styles, LEAF: "1"}})
        if node.index not in parents
        else node
        for node in rendered.nodes
    )
    return rendered.model_copy(update={"nodes": nodes})


def is_leaf(node: RenderedNode) -> bool:
    return node.styles.get(LEAF) == "1"


def filter_functions(node: RenderedNode) -> tuple[FilterFunction, ...]:
    """The node's lowerable filter functions, or ``()`` if it has none or cannot lower them."""
    functions = parse_filters(node.styles.get("filter"))
    if functions is None or not is_leaf(node) or not is_lowerable(functions):
        return ()
    if "url(" in node.styles.get("backgroundImage", ""):
        return ()  # a picture background would need its pixels filtered too
    return functions


def colour_functions(node: RenderedNode) -> tuple[FilterFunction, ...]:
    return tuple(f for f in filter_functions(node) if f.name in COLOR_FUNCTIONS)


def lower_drop_shadow(node: RenderedNode) -> RenderedNode:
    """Turn ``drop-shadow()`` into the equivalent ``box-shadow`` (or ``text-shadow`` for bare text).

    A drop shadow follows the painted alpha. For a filled shape that is its box, for text without a
    box it is the glyphs; both use the same blur convention as the CSS shadow they become.
    """
    functions = filter_functions(node)
    shadows = [f.argument for f in functions if f.name == "drop-shadow"]
    if not shadows:
        return node
    styles = dict(node.styles)
    remaining = " ".join(
        f"{f.name}({f.amount:g}{'deg' if f.name == 'hue-rotate' else ''})"
        for f in functions
        if f.name != "drop-shadow"
    )
    styles["filter"] = remaining or "none"
    key = "boxShadow" if _paints_a_box(node) else "textShadow"
    existing = styles.get(key, "none")
    joined = ", ".join(shadows)
    styles[key] = joined if existing in ("", "none") else f"{existing}, {joined}"
    update: dict[str, object] = {"styles": styles}
    if key == "textShadow":
        # Runs carry their own computed styles, so the shadow has to reach each of them too.
        update["text_runs"] = tuple(
            run.model_copy(update={"styles": {**run.styles, "textShadow": styles[key]}})
            for run in node.text_runs
        )
    return node.model_copy(update=update)


def _paints_a_box(node: RenderedNode) -> bool:
    styles = node.styles
    if styles.get("backgroundImage", "none") != "none":
        return True
    background = styles.get("backgroundColor", "")
    transparent = background in ("", "transparent") or background.replace(" ", "").endswith(",0)")
    borders = any(
        styles.get(f"border{side}Style", "none") not in ("none", "hidden")
        and not styles.get(f"border{side}Width", "0px").startswith("0")
        for side in ("Top", "Right", "Bottom", "Left")
    )
    return not transparent or borders or not node.text


# --------------------------------------------------------------------------- opacity


def fade_shape(shape: ShapeNode, factor: float) -> ShapeNode:
    """``shape`` with its outline, effects and text faded by ``factor``.

    The fill is left to ``ShapeNode.opacity``, which the writers apply to solid and gradient fills
    and to pictures alike. CSS ``opacity`` fades everything the element paints, so the rest
    has to follow.
    """
    if factor >= 1.0:
        return shape
    functions = (FilterFunction("opacity", max(0.0, factor)),)

    def tone(color: Rgba) -> Rgba:
        return apply_to_color(color, functions)

    return shape.model_copy(
        update={
            "line": _recolor_line(shape.line, tone),
            "effects": tuple(_recolor_effect(effect, tone) for effect in shape.effects),
            "text": _recolor_text(shape.text, tone),
        }
    )


# --------------------------------------------------------------------------- recolouring


def recolor_shape(shape: ShapeNode, functions: tuple[FilterFunction, ...]) -> ShapeNode:
    """``shape`` with every colour it paints mapped through the colour ``functions``."""
    if not functions:
        return shape

    def tone(color: Rgba) -> Rgba:
        return apply_to_color(color, functions)

    return shape.model_copy(
        update={
            "fill": _recolor_fill(shape.fill, tone),
            "line": _recolor_line(shape.line, tone),
            "effects": tuple(_recolor_effect(effect, tone) for effect in shape.effects),
            "text": _recolor_text(shape.text, tone),
        }
    )


def _recolor_gradient(gradient: GradientFill, tone: Callable[[Rgba], Rgba]) -> GradientFill:
    # Channel clamping bends the ramp between stops, so sample it finely before recolouring.
    positions = sorted({stop.pos for stop in gradient.stops} | {i / 16 for i in range(17)})
    stops = tuple(
        GradientStop(pos=pos, color=tone(_sample(gradient.stops, pos))) for pos in positions
    )
    return gradient.model_copy(update={"stops": stops})


def _recolor_fill(fill: Fill | None, tone: Callable[[Rgba], Rgba]) -> Fill | None:
    if isinstance(fill, SolidFill):
        return fill.model_copy(update={"color": tone(fill.color)})
    if isinstance(fill, GradientFill):
        return _recolor_gradient(fill, tone)
    return fill


def _recolor_line(line: Line | None, tone: Callable[[Rgba], Rgba]) -> Line | None:
    if line is None:
        return None
    gradient = _recolor_gradient(line.gradient, tone) if line.gradient is not None else None
    return line.model_copy(update={"color": tone(line.color), "gradient": gradient})


def _recolor_effect(effect: Effect, tone: Callable[[Rgba], Rgba]) -> Effect:
    if isinstance(effect, Shadow | Glow):
        return effect.model_copy(update={"color": tone(effect.color)})
    return effect


def _recolor_text(text: TextBody | None, tone: Callable[[Rgba], Rgba]) -> TextBody | None:
    if text is None:
        return None
    paragraphs = tuple(
        paragraph.model_copy(
            update={"runs": tuple(_recolor_run(run, tone) for run in paragraph.runs)}
        )
        for paragraph in text.paragraphs
    )
    return text.model_copy(update={"paragraphs": paragraphs})


def _recolor_run(run: TextRun, tone: Callable[[Rgba], Rgba]) -> TextRun:
    outline = (
        TextOutline(width_pt=run.outline.width_pt, color=tone(run.outline.color))
        if run.outline is not None
        else None
    )
    return run.model_copy(
        update={
            "color": tone(run.color),
            "gradient": _recolor_gradient(run.gradient, tone) if run.gradient else None,
            "outline": outline,
            "shadow": run.shadow.model_copy(update={"color": tone(run.shadow.color)})
            if run.shadow
            else None,
        }
    )


# --------------------------------------------------------------------------- masks


def lower_mask(fill: Fill | None, node: RenderedNode) -> tuple[Fill | None, str | None]:
    """Fold a ``mask-image`` fade into ``fill``'s alpha, or say why it cannot be.

    Returns ``(fill, None)`` when there is no mask or it folded, and ``(fill, reason)`` when the
    node has a mask that must stay a raster.
    """
    styles = node.styles
    value = styles.get("maskImage", "none")
    if value in ("", "none"):
        return fill, None
    mask = parse_gradient(value) if is_leaf(node) and fill_only(node) else None
    if mask is None or any(
        styles.get(key, "") not in allowed for key, allowed in _MASK_DEFAULTS.items()
    ):
        return fill, "CSS mask has no native mapping"
    if isinstance(fill, SolidFill):
        stops = tuple(
            GradientStop(
                pos=s.pos, color=fill.color.model_copy(update={"a": fill.color.a * s.color.a})
            )
            for s in mask.stops
        )
        return GradientFill(stops=stops, angle_deg=mask.angle_deg, radial=mask.radial), None
    if (
        isinstance(fill, GradientFill)
        and not fill.radial
        and not mask.radial
        and abs(fill.angle_deg - mask.angle_deg) < 0.01
    ):
        positions = sorted({s.pos for s in fill.stops} | {s.pos for s in mask.stops})
        folded = tuple(
            GradientStop(
                pos=pos,
                color=_sample(fill.stops, pos).model_copy(
                    update={"a": _sample(fill.stops, pos).a * _sample(mask.stops, pos).a}
                ),
            )
            for pos in positions
        )
        return fill.model_copy(update={"stops": folded}), None
    return fill, "CSS mask has no native mapping for this fill"


def fill_only(node: RenderedNode) -> bool:
    """Whether the fill is all the node paints; a mask also fades its text, border and shadow."""
    styles = node.styles
    borders = any(
        styles.get(f"border{side}Style", "none") not in ("none", "hidden")
        and not styles.get(f"border{side}Width", "0px").startswith("0")
        for side in ("Top", "Right", "Bottom", "Left")
    )
    return not node.text and not borders and styles.get("boxShadow", "none") in ("none", "")


def _sample(stops: tuple[GradientStop, ...], position: float) -> Rgba:
    """The gradient's colour at ``position``, interpolating in premultiplied alpha like CSS."""
    if position <= stops[0].pos:
        return stops[0].color
    for before, after in pairwise(stops):
        if before.pos <= position <= after.pos:
            span = after.pos - before.pos
            return mix_colors(
                before.color, after.color, 0.0 if span <= 0 else (position - before.pos) / span
            )
    return stops[-1].color


def mix_colors(a: Rgba, b: Rgba, t: float) -> Rgba:
    alpha = a.a + (b.a - a.a) * t

    def channel(x: int, y: int) -> int:
        if alpha <= 0:
            return round(x + (y - x) * t)
        return round((x * a.a * (1 - t) + y * b.a * t) / alpha)

    return Rgba(r=channel(a.r, b.r), g=channel(a.g, b.g), b=channel(a.b, b.b), a=alpha)
