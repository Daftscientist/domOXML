"""Where a shape's outline sits: CSS draws a border inside the box, DrawingML centres it.

A CSS border fills the band from the border box inward. A DrawingML ``a:ln`` is centred on the
shape's path, so the same box would put half of the stroke outside it (measured in real
PowerPoint: a 24 px border's outer edge lands 12 px outside the browser's). The IR keeps the CSS
meaning, a box that includes its border; :func:`stroke_centred` gives the box and corner radius
the file needs, and :func:`stroke_outer` undoes it for a shape read from one.
"""

from __future__ import annotations

from domoxml.core.ir.model import Box, ShapeNode


def _half(node: ShapeNode, *, writing: bool) -> int:
    """Half the stroke width when ``node`` is a plain preset shape whose box moves, else 0.

    A shape no thicker than its own stroke has no band to inset, so the writer leaves it alone. A
    box cannot tell a reader whether it was inset, so the reader moves every box that has room:
    the two agree for every shape thicker than its stroke, and differ only for the degenerate
    ones that are all border.
    """
    line = node.line
    if (
        line is None
        or line.width_emu <= 0
        or node.custom_geom is not None
        or node.side_lines is not None
    ):
        return 0
    if writing and min(node.box.width, node.box.height) <= line.width_emu:
        return 0
    return line.width_emu // 2


def _grown(node: ShapeNode, delta: int) -> ShapeNode:
    """``node`` with its box grown by ``delta`` on every side (negative shrinks).

    The corner radius follows the edge it belongs to, and the text insets shrink as the box
    grows, so the text stays where it was.
    """
    update: dict[str, object] = {
        "box": Box(
            x=node.box.x - delta,
            y=node.box.y - delta,
            width=node.box.width + 2 * delta,
            height=node.box.height + 2 * delta,
        )
    }
    if node.corner_radius_emu > 0:
        update["corner_radius_emu"] = max(0, node.corner_radius_emu + delta)
    text = node.text
    if text is not None and any(text.margins):
        left, top, right, bottom = (max(0, margin + delta) for margin in text.margins)
        update["text"] = text.model_copy(update={"margins": (left, top, right, bottom)})
    return node.model_copy(update=update)


def stroke_centred(node: ShapeNode) -> ShapeNode:
    """``node`` as the file needs it: the box inset so the stroke covers the CSS border band."""
    half = _half(node, writing=True)
    return _grown(node, -half) if half else node


def stroke_outer(node: ShapeNode) -> ShapeNode:
    """A shape read from a file, boxed the CSS way: out to the outer edge of its stroke."""
    half = _half(node, writing=False)
    return _grown(node, half) if half else node
