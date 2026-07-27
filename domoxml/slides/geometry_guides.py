"""Evaluate DrawingML custom-geometry guide formulas."""

from __future__ import annotations

import math
from collections.abc import Mapping

_ANGLE_UNIT = 60_000


def _divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        raise ValueError("custom-geometry guide divides by zero")
    return numerator / denominator


def _resolve(token: str, values: Mapping[str, float]) -> float:
    try:
        return float(token)
    except ValueError:
        try:
            return values[token]
        except KeyError as error:
            raise ValueError(f"unknown custom-geometry guide {token!r}") from error


def evaluate_formula(formula: str, values: Mapping[str, float]) -> float:
    """Evaluate one ECMA-376 ``ST_GeomGuideFormula`` expression."""
    parts = formula.split()
    if not parts:
        raise ValueError("empty custom-geometry guide formula")
    operation, operands = parts[0], parts[1:]
    args = tuple(_resolve(token, values) for token in operands)

    if operation == "val" and len(args) == 1:
        return args[0]
    if operation == "*/" and len(args) == 3:
        return _divide(args[0] * args[1], args[2])
    if operation == "+-" and len(args) == 3:
        return args[0] + args[1] - args[2]
    if operation == "+/" and len(args) == 3:
        return _divide(args[0] + args[1], args[2])
    if operation == "?:" and len(args) == 3:
        return args[1] if args[0] > 0 else args[2]
    if operation == "abs" and len(args) == 1:
        return abs(args[0])
    if operation == "sqrt" and len(args) == 1:
        return math.sqrt(args[0])
    if operation == "max" and len(args) == 2:
        return max(args)
    if operation == "min" and len(args) == 2:
        return min(args)
    if operation == "pin" and len(args) == 3:
        return min(max(args[0], args[1]), args[2])
    if operation == "mod" and len(args) == 3:
        return math.sqrt(sum(value * value for value in args))
    if operation in {"sin", "cos", "tan"} and len(args) == 2:
        angle = math.radians(args[1] / _ANGLE_UNIT)
        function = {"sin": math.sin, "cos": math.cos, "tan": math.tan}[operation]
        return args[0] * function(angle)
    if operation == "at2" and len(args) == 2:
        return math.degrees(math.atan2(args[1], args[0])) * _ANGLE_UNIT
    if operation in {"cat2", "sat2"} and len(args) == 3:
        angle = math.atan2(args[2], args[1])
        function = math.cos if operation == "cat2" else math.sin
        return args[0] * function(angle)
    raise ValueError(f"unsupported custom-geometry guide formula {formula!r}")


def evaluate_guides(
    formulas: tuple[tuple[str, str], ...],
    *,
    width: int,
    height: int,
) -> dict[str, float]:
    """Resolve an ordered DrawingML guide list against the standard shape variables."""
    values: dict[str, float] = {
        "w": width,
        "h": height,
        "l": 0,
        "t": 0,
        "r": width,
        "b": height,
        "wd2": width / 2,
        "wd3": width / 3,
        "wd4": width / 4,
        "wd5": width / 5,
        "wd6": width / 6,
        "wd8": width / 8,
        "wd10": width / 10,
        "hd2": height / 2,
        "hd3": height / 3,
        "hd4": height / 4,
        "hd5": height / 5,
        "hd6": height / 6,
        "hd8": height / 8,
        "hd10": height / 10,
        "hc": width / 2,
        "vc": height / 2,
        "ss": min(width, height),
        "ls": max(width, height),
        "cd2": 10_800_000,
        "cd4": 5_400_000,
        "cd8": 2_700_000,
        "3cd4": 16_200_000,
        "3cd8": 8_100_000,
        "5cd8": 13_500_000,
        "7cd8": 18_900_000,
    }
    for name, formula in formulas:
        values[name] = evaluate_formula(formula, values)
    return values


def resolve_guide(token: str | None, values: Mapping[str, float]) -> int:
    """Resolve one coordinate or angle token to the integer carried by the IR."""
    if token is None:
        raise ValueError("missing custom-geometry coordinate")
    return round(_resolve(token, values))
