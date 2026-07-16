"""Parse the CSS computed-style strings Chromium reports into typed IR values.

Every parser is total and side-effect-free: it returns a typed value or ``None`` when the
CSS can't be mapped to a native OOXML construct, so the extractor can fall back to raster.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from domoxml.core.ir.model import GradientFill, GradientStop, Line, LineSpacing, Rgba, Shadow
from domoxml.core.units import px_to_emu, px_to_pt

_RGB_RE = re.compile(
    r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)",
    re.IGNORECASE,
)
_LENGTH_RE = re.compile(r"(-?[\d.]+)\s*px", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(-?[\d.]+)\s*%")
_ANGLE_RE = re.compile(r"(-?[\d.]+)\s*deg", re.IGNORECASE)
_FUNC_RE = re.compile(r"\b(linear|radial|conic)-gradient\s*\(", re.IGNORECASE)


def parse_color(value: str | None) -> Rgba | None:
    """Parse a CSS ``rgb()/rgba()`` string into :class:`Rgba`, or ``None`` if unparseable."""
    if not value:
        return None
    match = _RGB_RE.search(value)
    if match is None:
        return None
    r, g, b = (round(float(match.group(i))) for i in (1, 2, 3))
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return Rgba(r=r, g=g, b=b, a=alpha)


def parse_length_px(value: str | None) -> float:
    """The first ``px`` length found in ``value`` (via ``_LENGTH_RE``), or 0.0 if there is none.

    Only the first match is returned, e.g. ``"12px 4px 4px 12px"`` → ``12.0``.
    """
    if not value:
        return 0.0
    match = _LENGTH_RE.search(value)
    return float(match.group(1)) if match else 0.0


def parse_radius_px(value: str | None, *, shorter_side_px: float) -> float:
    """Resolve a CSS border radius against a box's shorter side."""
    if not value:
        return 0.0
    length = _LENGTH_RE.search(value)
    if length is not None:
        return float(length.group(1))
    percent = _PERCENT_RE.search(value)
    return shorter_side_px * float(percent.group(1)) / 100 if percent is not None else 0.0


def is_bold(font_weight: str | None) -> bool:
    """True for ``bold``/``bolder`` or a numeric weight >= 600."""
    if not font_weight:
        return False
    weight = font_weight.strip().lower()
    if weight in {"bold", "bolder"}:
        return True
    try:
        return int(weight) >= 600
    except ValueError:
        return False


# --------------------------------------------------------------------------- run decorations


def parse_decoration(value: str | None) -> tuple[bool, bool]:
    """Map CSS ``text-decoration-line`` to ``(underline, strike)`` flags.

    A value can name both (``"underline line-through"``); ``"none"``/empty yields ``(False,
    False)``. ``overline`` has no DrawingML run equivalent and is ignored."""
    if not value:
        return False, False
    tokens = value.strip().lower().split()
    return ("underline" in tokens, "line-through" in tokens)


def parse_caps(
    text_transform: str | None, font_variant_caps: str | None
) -> Literal["all", "small"] | None:
    """Map CSS ``text-transform``/``font-variant-caps`` to an ``a:rPr cap`` token.

    ``text-transform: uppercase`` → ``"all"``; ``font-variant-caps`` containing ``small-caps``
    → ``"small"``. ``uppercase`` wins when both are present (it is the stronger transform)."""
    transform = (text_transform or "").strip().lower()
    if transform == "uppercase":
        return "all"
    variant = (font_variant_caps or "").strip().lower()
    if "small-caps" in variant:
        return "small"
    return None


def parse_letter_spacing_pt(value: str | None) -> float:
    """Map CSS ``letter-spacing`` (a ``px`` length, ``"normal"``, or empty) to points.

    ``"normal"`` and unparseable values yield ``0.0``. May be negative (tracking-in)."""
    if not value or value.strip().lower() == "normal":
        return 0.0
    match = _LENGTH_RE.search(value)
    # CSS px → points (1pt = 1/72in, 96px = 1in).
    return float(match.group(1)) * 72.0 / 96.0 if match is not None else 0.0


# --------------------------------------------------------------------------- borders


def _dash_style(
    style_token: str,
) -> tuple[Literal["solid", "dash", "dot"], str | None]:
    """Map a CSS border-style token to a ``(DashStyle, warning_message | None)`` pair.

    Unsupported styles (``double``, ``groove``, ``ridge``, ``inset``, ``outset``) are
    approximated as ``solid`` with an explanatory warning."""
    if style_token == "dashed":
        return "dash", None
    if style_token == "dotted":
        return "dot", None
    if style_token == "double":
        return "solid", "double border approximated as solid"
    if style_token in {"groove", "ridge", "inset", "outset"}:
        return "solid", f"3D border style '{style_token}' approximated as solid"
    return "solid", None


def parse_border_side(
    width: str | None, style: str | None, color: str | None
) -> tuple[Line | None, str | None]:
    """Map one CSS border side (computed width/style/colour) to a ``(Line, warning)`` pair.

    Returns ``(None, None)`` when there is no visible border (zero width,
    ``none``/``hidden`` style, transparent). The warning string is non-``None`` when the
    style is approximated (e.g. ``double`` → ``solid``)."""
    style_token = (style or "none").strip().lower()
    if style_token in {"none", "hidden"}:
        return None, None
    width_px = parse_length_px(width)
    if width_px <= 0:
        return None, None
    rgba = parse_color(color)
    if rgba is None or rgba.a <= 0:
        return None, None
    dash, warn = _dash_style(style_token)
    return Line(color=rgba, width_emu=px_to_emu(width_px), dash=dash), warn


# --------------------------------------------------------------------------- para spacing/indent


def parse_line_height(value: str | None) -> LineSpacing | None:
    """Map a CSS ``line-height`` computed value to a :class:`LineSpacing`, or ``None``.

    Chromium resolves ``normal`` to a ``px`` value, but to avoid encoding a font-metric
    default we skip values that look like browser-resolved normal (no explicit authoring).
    The caller should pass ``"normal"`` directly when the author wrote ``normal``; here we
    map ``"normal"`` → ``None``.

    - Unitless / percent (e.g. ``"1.6"``, ``"160%"``) → ``percent``
    - ``px`` value → ``points`` (converted)
    """
    if not value or value.strip().lower() == "normal":
        return None
    v = value.strip()
    # Percentage form: "160%"
    pct = _PERCENT_RE.match(v)
    if pct:
        return LineSpacing(percent=float(pct.group(1)) / 100.0)
    # px form: "24px"
    px = _LENGTH_RE.match(v)
    if px:
        pt = px_to_pt(float(px.group(1)))
        return LineSpacing(points=pt) if pt > 0 else None
    # Unitless form: "1.5"
    try:
        factor = float(v)
        if factor > 0:
            return LineSpacing(percent=factor)
    except ValueError:
        pass
    return None


def parse_margin_pt(value: str | None) -> float:
    """Parse the first ``px`` length in a CSS margin/padding computed value to points."""
    if not value:
        return 0.0
    px = parse_length_px(value)
    return px_to_pt(px) if px > 0 else 0.0


# CSS list-style-type → DrawingML buChar char
_LIST_STYLE_TO_BU_CHAR: dict[str, str] = {
    "disc": "•",  # •
    "circle": "○",  # ○
    "square": "▪",  # ▪
}

# CSS list-style-type → DrawingML buAutoNum scheme
_LIST_STYLE_TO_AUTONUM: dict[str, str] = {
    "decimal": "arabicPeriod",
    "lower-latin": "alphaLcPeriod",  # alias (overridden by lower-alpha in reverse)
    "upper-latin": "alphaUcPeriod",  # alias (overridden by upper-alpha in reverse)
    "lower-alpha": "alphaLcPeriod",
    "upper-alpha": "alphaUcPeriod",
    "lower-roman": "romanLcPeriod",
    "upper-roman": "romanUcPeriod",
}

# DrawingML buChar char → CSS list-style-type (reverse)
_BU_CHAR_TO_LIST_STYLE: dict[str, str] = {v: k for k, v in _LIST_STYLE_TO_BU_CHAR.items()}

# DrawingML buAutoNum scheme → CSS list-style-type (reverse)
_AUTONUM_TO_LIST_STYLE: dict[str, str] = {v: k for k, v in _LIST_STYLE_TO_AUTONUM.items()}


def bu_char_to_css_list_style(char: str) -> str:
    """Map a buChar glyph to a CSS list-style-type, or fall back to the raw char via content."""
    return _BU_CHAR_TO_LIST_STYLE.get(char, char)


def autonum_to_css_list_style(scheme: str) -> str:
    """Map a buAutoNum scheme to a CSS list-style-type, defaulting to ``decimal``."""
    return _AUTONUM_TO_LIST_STYLE.get(scheme, "decimal")


def css_list_style_to_bu_char(list_style: str) -> str:
    """Map a CSS list-style-type to its DrawingML buChar glyph, defaulting to ``•``."""
    return _LIST_STYLE_TO_BU_CHAR.get(list_style, "•")


def css_list_style_to_autonum(list_style: str) -> str | None:
    """Map a CSS list-style-type to a DrawingML buAutoNum scheme, or ``None`` if not ordered."""
    return _LIST_STYLE_TO_AUTONUM.get(list_style)


# --------------------------------------------------------------------------- box-shadow


def _split_top_level(value: str) -> list[str]:
    """Split on commas that are not inside parentheses (separates gradient/shadow layers)."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def parse_shadow(value: str | None) -> Shadow | None:
    """Map the first layer of a CSS ``box-shadow`` to a :class:`Shadow``, or ``None`` when
    there is no shadow. Spread radius (4th length) is stored in ``spread_emu``; it will be
    converted to OOXML grow factors by the DrawingML writer when shape dims are known."""
    if not value or value.strip().lower() == "none":
        return None
    layer = _split_top_level(value)[0]
    rgba = parse_color(layer) or Rgba(r=0, g=0, b=0, a=0.5)
    inset = "inset" in layer.lower()
    lengths = [float(m) for m in _LENGTH_RE.findall(layer)]
    if len(lengths) < 2:
        return None
    offset_x, offset_y = lengths[0], lengths[1]
    blur = lengths[2] if len(lengths) > 2 else 0.0
    spread = lengths[3] if len(lengths) > 3 else 0.0
    distance = math.hypot(offset_x, offset_y)
    # OOXML direction: 0° = East, 90° = South (y grows downward, same as CSS offsets).
    direction = math.degrees(math.atan2(offset_y, offset_x)) % 360.0
    return Shadow(
        color=rgba,
        blur_emu=px_to_emu(blur),
        distance_emu=px_to_emu(distance),
        direction_deg=direction,
        inset=inset,
        spread_emu=px_to_emu(spread),
    )


# --------------------------------------------------------------------------- gradients


def _gradient_body(value: str) -> tuple[str, bool] | None:
    """Return ``(inner-args, is_radial)`` for the first linear/radial gradient, or ``None``.

    ``conic-gradient`` (no native OOXML mapping) returns ``None`` so the element rasterises.
    """
    match = _FUNC_RE.search(value)
    if match is None or match.group(1).lower() == "conic":
        return None
    start = match.end()
    depth = 1
    for i in range(start, len(value)):
        if value[i] == "(":
            depth += 1
        elif value[i] == ")":
            depth -= 1
            if depth == 0:
                return value[start:i], match.group(1).lower() == "radial"
    return None


def _parse_stops(args: list[str]) -> tuple[GradientStop, ...]:
    """Parse the colour-stop arguments of a gradient into evenly-or-explicitly placed stops."""
    raw: list[tuple[Rgba, float | None]] = []
    for arg in args:
        color = parse_color(arg)
        if color is None:
            continue
        pct = _PERCENT_RE.search(arg)
        raw.append((color, float(pct.group(1)) / 100.0 if pct else None))
    if not raw:
        return ()
    # Fill in any missing positions by spreading them evenly across [0, 1].
    last = len(raw) - 1
    stops: list[GradientStop] = []
    for index, (color, pos) in enumerate(raw):
        resolved = pos if pos is not None else (index / last if last else 0.0)
        stops.append(GradientStop(pos=min(1.0, max(0.0, resolved)), color=color))
    return tuple(stops)


def parse_gradient(value: str | None) -> GradientFill | None:
    """Map a CSS ``linear-gradient``/``radial-gradient`` to a :class:`GradientFill`.

    Returns ``None`` for ``none``, ``url(...)``, ``conic-gradient``, stacked gradient layers,
    or any gradient with fewer than two parseable colour stops — those rasterise instead.
    """
    if not value or value.strip().lower() in {"none", ""}:
        return None
    if len(_split_top_level(value)) > 1:
        # Stacked, comma-separated layers have no single native fill — rasterise instead.
        # (Commas *inside* one gradient stay together: _split_top_level is paren-aware.)
        return None
    body = _gradient_body(value)
    if body is None:
        return None
    inner, radial = body
    args = _split_top_level(inner)
    angle = 180.0
    if args and _ANGLE_RE.search(args[0]) and parse_color(args[0]) is None:
        angle = float(_ANGLE_RE.search(args[0]).group(1))  # type: ignore[union-attr]
        args = args[1:]
    elif args and "to " in args[0].lower() and parse_color(args[0]) is None:
        angle = _KEYWORD_ANGLE.get(args[0].strip().lower(), 180.0)
        args = args[1:]
    stops = _parse_stops(args)
    if len(stops) < 2:
        return None
    return GradientFill(stops=stops, angle_deg=angle, radial=radial)


_KEYWORD_ANGLE = {
    "to top": 0.0,
    "to right": 90.0,
    "to bottom": 180.0,
    "to left": 270.0,
    "to top right": 45.0,
    "to bottom right": 135.0,
    "to bottom left": 225.0,
    "to top left": 315.0,
}


# --------------------------------------------------------------------------- clip-path polygon


_POLYGON_RE = re.compile(r"polygon\s*\(([^)]+)\)", re.IGNORECASE)
_COORD_SEP_RE = re.compile(r",\s*")


def parse_polygon(
    clip_path: str | None, *, width_px: float, height_px: float
) -> list[tuple[float, float]] | None:
    """Parse a ``clip-path: polygon(...)`` into absolute pixel coordinates.

    Each vertex is ``(x_px, y_px)``.  Returns ``None`` when the clip-path is absent, is not a
    polygon, or contains vertices we cannot convert to absolute px (e.g. ``calc(...)``).

    Only ``px`` and ``%`` length values are supported — they cover the full authoring surface
    for the forward path.
    """
    if not clip_path or clip_path.strip().lower() in {"none", ""}:
        return None
    match = _POLYGON_RE.search(clip_path)
    if match is None:
        return None
    inner = match.group(1)
    vertices: list[tuple[float, float]] = []
    for pair in _COORD_SEP_RE.split(inner.strip()):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split()
        if len(parts) != 2:
            return None  # unexpected token structure — bail out
        px_vals: list[float] = []
        for part, dim in zip(parts, (width_px, height_px), strict=True):
            px_m = _LENGTH_RE.match(part)
            pct_m = _PERCENT_RE.match(part)
            if px_m:
                px_vals.append(float(px_m.group(1)))
            elif pct_m:
                px_vals.append(float(pct_m.group(1)) / 100.0 * dim)
            else:
                return None  # calc(...) or other unsupported value
        vertices.append((px_vals[0], px_vals[1]))
    return vertices if len(vertices) >= 3 else None


# --------------------------------------------------------------------------- background size/pos


def parse_background_size(
    value: str | None,
    *,
    box_width_px: float | None = None,
    box_height_px: float | None = None,
) -> tuple[str, tuple[float, float] | None]:
    """Classify a CSS ``background-size`` computed value.

    Returns ``(mode, explicit_px)`` where ``mode`` is ``"cover"``, ``"contain"``, ``"auto"``, or
    ``"explicit"``. ``explicit_px`` is the resolved ``(width_px, height_px)`` pair for a two-value
    pixel or percentage size. Percentages require the corresponding box dimensions. Single-value
    and unsupported sizes fall back to ``"auto"`` (the caller treats them as a plain stretch)."""
    if not value:
        return "auto", None
    token = value.strip().lower()
    if token == "cover":
        return "cover", None
    if token == "contain":
        return "contain", None
    parts = token.split()
    if len(parts) == 2:
        resolved: list[float] = []
        for part, dimension in zip(parts, (box_width_px, box_height_px), strict=True):
            length = _LENGTH_RE.fullmatch(part)
            percent = _PERCENT_RE.fullmatch(part)
            if length is not None:
                resolved.append(float(length.group(1)))
            elif percent is not None and dimension is not None:
                resolved.append(float(percent.group(1)) / 100.0 * dimension)
            else:
                break
        if len(resolved) == 2:
            return "explicit", (resolved[0], resolved[1])
    return "auto", None


def parse_background_position(value: str | None) -> tuple[float, float]:
    """Map a CSS ``background-position`` computed value to ``(x, y)`` fractions in ``[0, 1]``.

    Chromium reports positions as percentages or px against the *positioning area*. Percentages
    map directly to fractions; keyword forms (left/center/right/top/bottom) are handled; px and
    unparseable values default to the CSS centre (``0.5``)."""
    if not value:
        return 0.5, 0.5
    token = value.strip().lower()
    keywords = {
        "left": 0.0,
        "right": 1.0,
        "top": 0.0,
        "bottom": 1.0,
        "center": 0.5,
    }
    parts = token.split()
    coords: list[float] = []
    for part in parts[:2]:
        pct = _PERCENT_RE.match(part)
        if pct is not None:
            coords.append(max(0.0, min(1.0, float(pct.group(1)) / 100.0)))
        elif part in keywords:
            coords.append(keywords[part])
        else:
            coords.append(0.5)
    while len(coords) < 2:
        coords.append(0.5)
    return coords[0], coords[1]
