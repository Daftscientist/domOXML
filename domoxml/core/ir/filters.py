"""CSS ``filter`` colour functions as plain colour maths.

``brightness``, ``contrast``, ``grayscale``, ``sepia``, ``saturate``, ``hue-rotate``, ``invert``
and ``opacity`` are per-pixel colour operations (Filter Effects Module Level 1), so for content
whose colours are known (a solid or gradient fill, a line, a text colour, an image) they can be
applied to those colours directly and the element needs no raster. ``drop-shadow`` is a shadow.

Only ``blur`` is not here: it needs a neighbourhood, so it stays a native ``a:blur`` effect.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from domoxml.core.ir.model import Rgba

_FUNCTION = re.compile(r"([a-z-]+)\(((?:[^()]|\([^()]*\))*)\)", re.IGNORECASE)
_NUMBER = re.compile(r"^\s*(-?[\d.]+)\s*(%|deg|grad|rad|turn)?\s*$", re.IGNORECASE)

COLOR_FUNCTIONS = frozenset(
    {"brightness", "contrast", "grayscale", "sepia", "saturate", "hue-rotate", "invert", "opacity"}
)


@dataclass(frozen=True)
class FilterFunction:
    """One parsed filter function: its name and numeric argument (a ratio, or degrees)."""

    name: str
    amount: float
    # Raw text inside the parentheses, kept for ``drop-shadow``.
    argument: str = ""


def parse_filters(value: str | None) -> tuple[FilterFunction, ...] | None:
    """Parse a computed ``filter`` value, or ``None`` if any function is not understood.

    Chrome reports ``filter`` as a space-separated list such as ``brightness(1.4) blur(2px)``.
    ``none`` and the empty string give an empty tuple.
    """
    if value is None or value.strip().lower() in ("", "none"):
        return ()
    functions: list[FilterFunction] = []
    consumed = 0
    for match in _FUNCTION.finditer(value):
        if value[consumed : match.start()].strip():
            return None
        consumed = match.end()
        name, argument = match.group(1).lower(), match.group(2).strip()
        if name in COLOR_FUNCTIONS:
            amount = _amount(name, argument)
            if amount is None:
                return None
            functions.append(FilterFunction(name, amount))
        elif name in ("drop-shadow", "blur"):
            functions.append(FilterFunction(name, 0.0, argument))
        else:
            return None
    if value[consumed:].strip():
        return None
    return tuple(functions)


def _amount(name: str, argument: str) -> float | None:
    """The numeric argument: a ratio (``50%`` is 0.5), or degrees for ``hue-rotate``."""
    if argument == "":
        return 0.0 if name == "hue-rotate" else 1.0
    match = _NUMBER.match(argument)
    if match is None:
        return None
    number, unit = float(match.group(1)), (match.group(2) or "").lower()
    if name == "hue-rotate":
        factors = {"": 1.0, "deg": 1.0, "grad": 0.9, "rad": 180.0 / math.pi, "turn": 360.0}
        return number * factors.get(unit, math.nan) if unit != "%" else None
    return number / 100.0 if unit == "%" else number if unit == "" else None


def _matrix(function: FilterFunction) -> tuple[tuple[float, float, float, float], ...]:
    """The 3x4 affine colour matrix (rows R, G, B; columns R, G, B, offset) for one function."""
    a = function.amount
    if function.name == "brightness":
        return ((a, 0, 0, 0), (0, a, 0, 0), (0, 0, a, 0))
    if function.name == "contrast":
        offset = 0.5 - 0.5 * a
        return ((a, 0, 0, offset), (0, a, 0, offset), (0, 0, a, offset))
    if function.name == "invert":
        return ((1 - 2 * a, 0, 0, a), (0, 1 - 2 * a, 0, a), (0, 0, 1 - 2 * a, a))
    if function.name == "grayscale":
        k = 1 - min(1.0, a)
        return (
            (0.2126 + 0.7874 * k, 0.7152 - 0.7152 * k, 0.0722 - 0.0722 * k, 0),
            (0.2126 - 0.2126 * k, 0.7152 + 0.2848 * k, 0.0722 - 0.0722 * k, 0),
            (0.2126 - 0.2126 * k, 0.7152 - 0.7152 * k, 0.0722 + 0.9278 * k, 0),
        )
    if function.name == "sepia":
        k = 1 - min(1.0, a)
        return (
            (0.393 + 0.607 * k, 0.769 - 0.769 * k, 0.189 - 0.189 * k, 0),
            (0.349 - 0.349 * k, 0.686 + 0.314 * k, 0.168 - 0.168 * k, 0),
            (0.272 - 0.272 * k, 0.534 - 0.534 * k, 0.131 + 0.869 * k, 0),
        )
    if function.name == "saturate":
        return (
            (0.213 + 0.787 * a, 0.715 - 0.715 * a, 0.072 - 0.072 * a, 0),
            (0.213 - 0.213 * a, 0.715 + 0.285 * a, 0.072 - 0.072 * a, 0),
            (0.213 - 0.213 * a, 0.715 - 0.715 * a, 0.072 + 0.928 * a, 0),
        )
    if function.name == "hue-rotate":
        c, n = math.cos(math.radians(a)), math.sin(math.radians(a))
        return (
            (
                0.213 + c * 0.787 - n * 0.213,
                0.715 - c * 0.715 - n * 0.715,
                0.072 - c * 0.072 + n * 0.928,
                0,
            ),
            (
                0.213 - c * 0.213 + n * 0.143,
                0.715 + c * 0.285 + n * 0.140,
                0.072 - c * 0.072 - n * 0.283,
                0,
            ),
            (
                0.213 - c * 0.213 - n * 0.787,
                0.715 - c * 0.715 + n * 0.715,
                0.072 + c * 0.928 + n * 0.072,
                0,
            ),
        )
    return ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0))


def is_lowerable(functions: tuple[FilterFunction, ...]) -> bool:
    """Whether every function is a colour function or a drop shadow (nothing needs pixels)."""
    return bool(functions) and all(
        f.name in COLOR_FUNCTIONS or f.name == "drop-shadow" for f in functions
    )


def apply_to_color(color: Rgba, functions: tuple[FilterFunction, ...]) -> Rgba:
    """``color`` after every colour function in order; ``opacity`` scales alpha."""
    red, green, blue, alpha = color.r / 255, color.g / 255, color.b / 255, color.a
    for function in functions:
        if function.name == "opacity":
            alpha *= min(1.0, max(0.0, function.amount))
            continue
        if function.name not in COLOR_FUNCTIONS:
            continue
        rows = _matrix(function)
        red, green, blue = (
            min(1.0, max(0.0, row[0] * red + row[1] * green + row[2] * blue + row[3]))
            for row in rows
        )
    return Rgba(r=round(red * 255), g=round(green * 255), b=round(blue * 255), a=alpha)


def apply_to_image(data: bytes, functions: tuple[FilterFunction, ...]) -> bytes | None:
    """The image bytes with every colour function applied (PNG out), or ``None`` if undecodable."""
    try:
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGBA")
            alpha = image.getchannel("A")
            colour = image.convert("RGB")
            for function in functions:
                if function.name == "opacity":
                    scale = min(1.0, max(0.0, function.amount))
                    table = bytes(round(v * scale) for v in range(256))
                    alpha = Image.frombytes("L", alpha.size, alpha.tobytes().translate(table))
                elif function.name in COLOR_FUNCTIONS:
                    rows = _matrix(function)
                    colour = colour.convert(
                        "RGB",
                        (
                            rows[0][0],
                            rows[0][1],
                            rows[0][2],
                            rows[0][3] * 255,
                            rows[1][0],
                            rows[1][1],
                            rows[1][2],
                            rows[1][3] * 255,
                            rows[2][0],
                            rows[2][1],
                            rows[2][2],
                            rows[2][3] * 255,
                        ),
                    )
            result = colour.convert("RGBA")
            result.putalpha(alpha)
            buffer = BytesIO()
            result.save(buffer, "PNG")
            return buffer.getvalue()
    except (OSError, ValueError):
        return None
