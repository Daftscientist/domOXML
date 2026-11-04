"""Where a shape's outline sits: CSS draws a border inside the box, DrawingML centres it.

A CSS border fills the band from the border box inward. A DrawingML ``a:ln`` is centred on the
shape's path, so the same box would put half of the stroke outside it (measured in real
PowerPoint: a 24 px border's outer edge lands 12 px outside the browser's). The IR keeps the CSS
meaning, a box that includes its border; :func:`stroke_centred` gives the box and corner radius
the file needs, and :func:`stroke_outer` undoes it for a shape read from one.
"""

from __future__ import annotations

from domoxml.core.ir.model import Box, ShapeNode

# A shape thinner than its stroke has no band to inset: lines and rules keep their box. The two
# directions test the box on their own side of the inset, so they agree on which shapes move.
_IR_SPANS = 3
_FILE_SPANS = 2


def _half(node: ShapeNode, spans: int) -> int:
    line = node.line
    if (
        line is None
        or line.width_emu <= 0
        or node.custom_geom is not None
        or node.side_lines is not None
    ):
        return 0
    if min(node.box.width, node.box.height) < spans * line.width_emu:
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


def outer_box(box: Box, line_width_emu: int) -> Box:
    """The CSS box of a plain preset shape read from a file with this stroke width."""
    if line_width_emu <= 0 or min(box.width, box.height) < _FILE_SPANS * line_width_emu:
        return box
    half = line_width_emu // 2
    return Box(
        x=box.x - half, y=box.y - half, width=box.width + 2 * half, height=box.height + 2 * half
    )


def stroke_centred(node: ShapeNode) -> ShapeNode:
    """``node`` as the file needs it: the box inset so the stroke covers the CSS border band."""
    half = _half(node, _IR_SPANS)
    return _grown(node, -half) if half else node


def stroke_outer(node: ShapeNode) -> ShapeNode:
    """A shape read from a file, boxed the CSS way: out to the outer edge of its stroke."""
    half = _half(node, _FILE_SPANS)
    return _grown(node, half) if half else node
