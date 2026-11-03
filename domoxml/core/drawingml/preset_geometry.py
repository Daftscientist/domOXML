"""Outlines for every DrawingML preset shape, evaluated from the ECMA-376 definitions.

``prstGeom`` names a shape PowerPoint draws itself from a guide list and a path list. The IR only
carries a few presets as named geometry; for the rest this evaluates the standard's guide formulas
at the shape's size and adjust values and returns the outline as a plain custom geometry, so the
silhouette survives as an editable shape in PPTX and HTML.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from domoxml.core.ir.model import (
    ArcTo,
    ClosePath,
    CubicTo,
    CustomGeometry,
    LineTo,
    MoveTo,
    PathCommand,
    Point,
    QuadTo,
)

_DEFINITIONS = Path(__file__).with_name("preset_shapes.xml")
_SHADED = frozenset({"norm", "lighten", "lightenLess", "darken", "darkenLess"})
_ANGLE = 60_000.0  # DrawingML angles are in 60000ths of a degree


class _Unsupported(Exception):
    """A formula or path command this evaluator does not know."""


@lru_cache(maxsize=1)
def _definitions() -> Element:
    return ElementTree.parse(str(_DEFINITIONS)).getroot()


def preset_names() -> frozenset[str]:
    """Every preset the bundled definitions describe."""
    return frozenset(child.tag for child in _definitions())


def _tag(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _builtin(width: float, height: float) -> dict[str, float]:
    short, long_ = min(width, height), max(width, height)
    values = {
        "l": 0.0,
        "t": 0.0,
        "r": width,
        "b": height,
        "w": width,
        "h": height,
        "hc": width / 2,
        "vc": height / 2,
        "ss": short,
        "ls": long_,
        "cd2": 180 * _ANGLE,
        "cd4": 90 * _ANGLE,
        "cd8": 45 * _ANGLE,
        "3cd4": 270 * _ANGLE,
        "3cd8": 135 * _ANGLE,
        "5cd8": 225 * _ANGLE,
        "7cd8": 315 * _ANGLE,
    }
    for divisor in (2, 3, 4, 5, 6, 8, 10, 12, 16, 32):
        values[f"wd{divisor}"] = width / divisor
        values[f"hd{divisor}"] = height / divisor
        values[f"ssd{divisor}"] = short / divisor
        values[f"lsd{divisor}"] = long_ / divisor
    return values


def _evaluate(formula: str, env: Mapping[str, float]) -> float:
    operator, *operands = formula.split()

    def value(token: str) -> float:
        try:
            return float(token)
        except ValueError:
            if token not in env:
                raise _Unsupported(f"unknown guide {token!r}") from None
            return env[token]

    args = [value(token) for token in operands]
    match operator:
        case "val":
            return args[0]
        case "*/":
            return args[0] * args[1] / args[2] if args[2] else 0.0
        case "+-":
            return args[0] + args[1] - args[2]
        case "+/":
            return (args[0] + args[1]) / args[2] if args[2] else 0.0
        case "?:":
            return args[1] if args[0] > 0 else args[2]
        case "abs":
            return abs(args[0])
        case "sqrt":
            return math.sqrt(max(args[0], 0.0))
        case "max":
            return max(args[0], args[1])
        case "min":
            return min(args[0], args[1])
        case "mod":
            return math.sqrt(args[0] ** 2 + args[1] ** 2 + args[2] ** 2)
        case "pin":
            return max(args[0], min(args[1], args[2]))
        case "sin":
            return args[0] * math.sin(math.radians(args[1] / _ANGLE))
        case "cos":
            return args[0] * math.cos(math.radians(args[1] / _ANGLE))
        case "tan":
            return args[0] * math.tan(math.radians(args[1] / _ANGLE))
        case "at2":
            return math.degrees(math.atan2(args[1], args[0])) * _ANGLE
        case "cat2":
            return args[0] * math.cos(math.atan2(args[2], args[1]))
        case "sat2":
            return args[0] * math.sin(math.atan2(args[2], args[1]))
    raise _Unsupported(f"unknown operator {operator!r}")


def _guides(definition: Element, env: dict[str, float], overrides: Mapping[str, float]) -> None:
    """Fill ``env`` with the adjust values (``overrides`` win) and every computed guide."""
    for container in ("avLst", "gdLst"):
        for node in definition:
            if _tag(node) != container:
                continue
            for guide in node:
                name = guide.get("name", "")
                if container == "avLst" and name in overrides:
                    env[name] = overrides[name]
                else:
                    env[name] = _evaluate(guide.get("fmla", ""), env)


def _point(element: Element, env: Mapping[str, float], scale: tuple[float, float]) -> Point:
    def coordinate(token: str, factor: float) -> int:
        try:
            raw = float(token)
        except ValueError:
            raw = env[token]
        return round(raw * factor)

    return Point(
        x=coordinate(element.get("x", "0"), scale[0]),
        y=coordinate(element.get("y", "0"), scale[1]),
    )


def _number(token: str | None, env: Mapping[str, float]) -> float:
    if token is None:
        return 0.0
    try:
        return float(token)
    except ValueError:
        return env[token]


def preset_geometry(
    name: str, width_emu: int, height_emu: int, adjusts: Mapping[str, float] | None = None
) -> tuple[CustomGeometry | None, bool]:
    """The outline of preset ``name`` at the given size as a custom geometry.

    Returns ``(geometry, complete)``. ``complete`` is false when the preset also draws
    stroke-only or shaded sub-paths that a single filled outline cannot carry. ``geometry`` is
    ``None`` for an unknown preset or one whose formulas this cannot evaluate.
    """
    definition = _definitions().find(name)
    if definition is None:
        return None, False
    # A horizontal or vertical line has no extent on one axis; the path space still needs one.
    width_emu, height_emu = max(1, width_emu), max(1, height_emu)
    env = _builtin(float(width_emu), float(height_emu))
    try:
        _guides(definition, env, adjusts or {})
        filled: list[PathCommand] = []
        stroked: list[PathCommand] = []
        for path_list in (node for node in definition if _tag(node) == "pathLst"):
            for path in path_list:
                # Shaded faces are real area of the silhouette; they take the shape's one fill.
                fill = "norm" if path.get("fill", "norm") in _SHADED else path.get("fill", "norm")
                path_w = float(path.get("w") or 0) or float(width_emu)
                path_h = float(path.get("h") or 0) or float(height_emu)
                scale = (width_emu / path_w, height_emu / path_h)
                (filled if fill == "norm" else stroked).extend(_path_commands(path, env, scale))
        # A preset made only of strokes (a line) is those strokes; otherwise they are dropped.
        commands = filled or stroked
        complete = not (filled and stroked) and not _has_shading(definition)
    except (_Unsupported, KeyError, ValueError, ZeroDivisionError):
        return None, False
    if not commands:
        return None, False
    return (
        CustomGeometry(width_emu=width_emu, height_emu=height_emu, path=tuple(commands)),
        complete,
    )


def _has_shading(definition: Element) -> bool:
    return any(
        path.get("fill") in _SHADED - {"norm"}
        for node in definition
        if _tag(node) == "pathLst"
        for path in node
    )


def _path_commands(
    path: Element, env: Mapping[str, float], scale: tuple[float, float]
) -> list[PathCommand]:
    commands: list[PathCommand] = []
    for step in path:
        kind = _tag(step)
        points = [_point(point, env, scale) for point in step if _tag(point) == "pt"]
        if kind == "moveTo":
            commands.append(MoveTo(to=points[0]))
        elif kind == "lnTo":
            commands.append(LineTo(to=points[0]))
        elif kind == "cubicBezTo":
            commands.append(CubicTo(c1=points[0], c2=points[1], to=points[2]))
        elif kind == "quadBezTo":
            commands.append(QuadTo(c1=points[0], to=points[1]))
        elif kind == "arcTo":
            radius_x = _number(step.get("wR"), env) * scale[0]
            radius_y = _number(step.get("hR"), env) * scale[1]
            if radius_x <= 0 or radius_y <= 0:
                continue  # a zero-radius corner is a sharp one: the arc draws nothing
            commands.append(
                ArcTo(
                    width_radius=max(1, round(radius_x)),
                    height_radius=max(1, round(radius_y)),
                    start_angle=round(_number(step.get("stAng"), env)),
                    sweep_angle=round(_number(step.get("swAng"), env)),
                )
            )
        elif kind == "close":
            commands.append(ClosePath())
        else:
            raise _Unsupported(f"unknown path command {kind!r}")
    return commands
