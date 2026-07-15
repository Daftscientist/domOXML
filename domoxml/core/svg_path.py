"""SVG path ``d`` attribute parser → IR path commands.

Supported subset (ECMA-376 § SVG path data):
  M/m  moveto
  L/l  lineto
  H/h  horizontal lineto
  V/v  vertical lineto
  C/c  cubic Bézier
  Q/q  quadratic Bézier
  Z/z  close path

Unsupported commands (bail to raster with warning):
  S/s  smooth cubic Bézier
  T/t  smooth quadratic Bézier
  A/a  arc

All coordinates are normalised to **absolute** values in the SVG user-space (pixels / viewBox
units), then scaled by the caller to EMU.  Relative commands are accumulated into the current
cursor; implicit command repetition is handled per the SVG spec.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from domoxml.core.ir.model import (
    ClosePath,
    CubicTo,
    LineTo,
    MoveTo,
    PathCommand,
    Point,
    QuadTo,
)

# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

# Split on whitespace, commas, and sign boundaries (a sign that follows a digit/dot starts
# the next coordinate, per the SVG spec).
_TOKEN_RE = re.compile(r"[MmLlHhVvCcQqZzSsTtAa]|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _tokenise(d: str) -> list[str]:
    return _TOKEN_RE.findall(d)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


class ParsedPath(NamedTuple):
    """Result from :func:`parse_svg_path`."""

    commands: list[PathCommand]
    """Normalised absolute-coordinate path commands."""
    bail_reason: str | None
    """Non-``None`` when an unsupported command was encountered; commands up to
    that point are included but the path is incomplete."""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_UNSUPPORTED = frozenset("SsTtAa")
_COORD_CMDS = frozenset("MmLlHhVvCcQqZz")


def _pop(tokens: list[str], index: int) -> tuple[float, int]:
    return float(tokens[index]), index + 1


def parse_svg_path(d: str) -> ParsedPath:
    """Parse an SVG path ``d`` string into normalised absolute IR commands.

    Returns a :class:`ParsedPath` — check ``bail_reason`` before using ``commands``.
    Relative commands are accumulated against the current pen position (cx, cy).
    The implicit repetition rule: after the initial command, repeated coordinate pairs
    reuse the same command letter (``M`` repeats as ``L``, ``m`` as ``l``).
    """
    tokens = _tokenise(d.strip())
    commands: list[PathCommand] = []
    cx, cy = 0.0, 0.0  # current pen position
    subpath_x, subpath_y = 0.0, 0.0  # start of current subpath (for Z)

    i = 0
    cmd = ""
    while i < len(tokens):
        tok = tokens[i]
        if tok.upper() in _COORD_CMDS or tok.upper() in _UNSUPPORTED:
            cmd = tok
            i += 1
        # If no command yet and we have a coordinate: error
        if cmd == "":
            break

        if cmd in _UNSUPPORTED:
            return ParsedPath(commands, f"unsupported SVG command '{cmd}' — bailing to raster")

        # --- Z / z ---
        if cmd in ("Z", "z"):
            commands.append(ClosePath())
            cx, cy = subpath_x, subpath_y
            # Z/z has no arguments; next token must be a new command
            cmd = ""
            continue

        # --- M / m ---
        if cmd == "M":
            if i >= len(tokens):
                break
            x, i = _pop(tokens, i)
            y, i = _pop(tokens, i)
            cx, cy = x, y
            subpath_x, subpath_y = cx, cy
            commands.append(MoveTo(to=Point(x=round(cx), y=round(cy))))
            cmd = "L"  # implicit repeat → lineto
            continue

        if cmd == "m":
            if i >= len(tokens):
                break
            dx, i = _pop(tokens, i)
            dy, i = _pop(tokens, i)
            cx += dx
            cy += dy
            subpath_x, subpath_y = cx, cy
            commands.append(MoveTo(to=Point(x=round(cx), y=round(cy))))
            cmd = "l"  # implicit repeat → relative lineto
            continue

        # --- L / l ---
        if cmd == "L":
            if i >= len(tokens):
                break
            x, i = _pop(tokens, i)
            y, i = _pop(tokens, i)
            cx, cy = x, y
            commands.append(LineTo(to=Point(x=round(cx), y=round(cy))))
            continue

        if cmd == "l":
            if i >= len(tokens):
                break
            dx, i = _pop(tokens, i)
            dy, i = _pop(tokens, i)
            cx += dx
            cy += dy
            commands.append(LineTo(to=Point(x=round(cx), y=round(cy))))
            continue

        # --- H / h ---
        if cmd == "H":
            if i >= len(tokens):
                break
            x, i = _pop(tokens, i)
            cx = x
            commands.append(LineTo(to=Point(x=round(cx), y=round(cy))))
            continue

        if cmd == "h":
            if i >= len(tokens):
                break
            dx, i = _pop(tokens, i)
            cx += dx
            commands.append(LineTo(to=Point(x=round(cx), y=round(cy))))
            continue

        # --- V / v ---
        if cmd == "V":
            if i >= len(tokens):
                break
            y, i = _pop(tokens, i)
            cy = y
            commands.append(LineTo(to=Point(x=round(cx), y=round(cy))))
            continue

        if cmd == "v":
            if i >= len(tokens):
                break
            dy, i = _pop(tokens, i)
            cy += dy
            commands.append(LineTo(to=Point(x=round(cx), y=round(cy))))
            continue

        # --- C / c  (cubic Bézier: x1 y1 x2 y2 x y) ---
        if cmd == "C":
            if i + 5 >= len(tokens):
                break
            x1, i = _pop(tokens, i)
            y1, i = _pop(tokens, i)
            x2, i = _pop(tokens, i)
            y2, i = _pop(tokens, i)
            x, i = _pop(tokens, i)
            y, i = _pop(tokens, i)
            commands.append(
                CubicTo(
                    c1=Point(x=round(x1), y=round(y1)),
                    c2=Point(x=round(x2), y=round(y2)),
                    to=Point(x=round(x), y=round(y)),
                )
            )
            cx, cy = x, y
            continue

        if cmd == "c":
            if i + 5 >= len(tokens):
                break
            dx1, i = _pop(tokens, i)
            dy1, i = _pop(tokens, i)
            dx2, i = _pop(tokens, i)
            dy2, i = _pop(tokens, i)
            dx, i = _pop(tokens, i)
            dy, i = _pop(tokens, i)
            commands.append(
                CubicTo(
                    c1=Point(x=round(cx + dx1), y=round(cy + dy1)),
                    c2=Point(x=round(cx + dx2), y=round(cy + dy2)),
                    to=Point(x=round(cx + dx), y=round(cy + dy)),
                )
            )
            cx += dx
            cy += dy
            continue

        # --- Q / q  (quadratic Bézier: x1 y1 x y) ---
        if cmd == "Q":
            if i + 3 >= len(tokens):
                break
            x1, i = _pop(tokens, i)
            y1, i = _pop(tokens, i)
            x, i = _pop(tokens, i)
            y, i = _pop(tokens, i)
            commands.append(
                QuadTo(
                    c1=Point(x=round(x1), y=round(y1)),
                    to=Point(x=round(x), y=round(y)),
                )
            )
            cx, cy = x, y
            continue

        if cmd == "q":
            if i + 3 >= len(tokens):
                break
            dx1, i = _pop(tokens, i)
            dy1, i = _pop(tokens, i)
            dx, i = _pop(tokens, i)
            dy, i = _pop(tokens, i)
            commands.append(
                QuadTo(
                    c1=Point(x=round(cx + dx1), y=round(cy + dy1)),
                    to=Point(x=round(cx + dx), y=round(cy + dy)),
                )
            )
            cx += dx
            cy += dy
            continue

        # Unknown command: break
        break

    return ParsedPath(commands, None)


# ---------------------------------------------------------------------------
# Scale helpers
# ---------------------------------------------------------------------------


def scale_path_to_emu(
    commands: list[PathCommand],
    *,
    vb_w: float,
    vb_h: float,
    box_emu_w: int,
    box_emu_h: int,
) -> list[PathCommand]:
    """Scale path commands from SVG viewBox units to EMU coordinates.

    ``vb_w``/``vb_h`` are the viewBox dimensions; ``box_emu_w``/``box_emu_h`` are the
    target bounding box in EMUs.  ClosePath has no coordinates and passes through unchanged.
    """
    if vb_w <= 0 or vb_h <= 0:
        return commands

    sx = box_emu_w / vb_w
    sy = box_emu_h / vb_h

    def _pt(p: Point) -> Point:
        return Point(x=round(p.x * sx), y=round(p.y * sy))

    result: list[PathCommand] = []
    for cmd in commands:
        if isinstance(cmd, MoveTo):
            result.append(MoveTo(to=_pt(cmd.to)))
        elif isinstance(cmd, LineTo):
            result.append(LineTo(to=_pt(cmd.to)))
        elif isinstance(cmd, CubicTo):
            result.append(CubicTo(c1=_pt(cmd.c1), c2=_pt(cmd.c2), to=_pt(cmd.to)))
        elif isinstance(cmd, QuadTo):
            result.append(QuadTo(c1=_pt(cmd.c1), to=_pt(cmd.to)))
        else:
            result.append(cmd)  # ClosePath
    return result


# ---------------------------------------------------------------------------
# Reverse: IR path commands → SVG d string
# ---------------------------------------------------------------------------


def commands_to_svg_d(commands: tuple[PathCommand, ...]) -> str:
    """Serialize IR path commands back to an SVG ``d`` attribute string."""
    parts: list[str] = []
    for cmd in commands:
        if isinstance(cmd, MoveTo):
            parts.append(f"M {cmd.to.x} {cmd.to.y}")
        elif isinstance(cmd, LineTo):
            parts.append(f"L {cmd.to.x} {cmd.to.y}")
        elif isinstance(cmd, CubicTo):
            parts.append(f"C {cmd.c1.x} {cmd.c1.y} {cmd.c2.x} {cmd.c2.y} {cmd.to.x} {cmd.to.y}")
        elif isinstance(cmd, QuadTo):
            parts.append(f"Q {cmd.c1.x} {cmd.c1.y} {cmd.to.x} {cmd.to.y}")
        else:
            parts.append("Z")
    return " ".join(parts)
