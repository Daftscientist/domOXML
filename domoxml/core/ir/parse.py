"""Parse the CSS computed-style strings Chromium reports into typed IR values.

Every parser is total and side-effect-free: it returns a typed value or ``None`` when the
CSS can't be mapped to a native OOXML construct, so the extractor can fall back to raster.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from domoxml.core.ir.model import (
    Blur,
    FillOverlay,
    FillOverlayBlend,
    GradientFill,
    GradientStop,
    Line,
    LineSpacing,
    Reflection,
    Rgba,
    Shadow,
    SoftEdge,
    SolidFill,
)
from domoxml.core.units import px_to_emu, px_to_pt

_RGB_RE = re.compile(
    r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)",
    re.IGNORECASE,
)
_LENGTH_RE = re.compile(r"(-?[\d.]+)\s*px", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(-?[\d.]+)\s*%")
_ANGLE_RE = re.compile(r"(-?[\d.]+)\s*deg", re.IGNORECASE)
_FUNC_RE = re.compile(r"\b(linear|radial|conic)-gradient\s*\(", re.IGNORECASE)
_BLUR_FILTER_RE = re.compile(r"blur\(\s*([\d.]+)px\s*\)", re.IGNORECASE)
_BOX_REFLECTION_RE = re.compile(r"^below\s+([\d.]+)px\s+", re.IGNORECASE)
_SOFT_EDGE_INNER_END_RE = re.compile(r"(\d+(?:\.\d+)?|\.\d+)px\s*$", re.IGNORECASE)
_SOFT_EDGE_FAR_INNER_END_RE = re.compile(
    r"calc\(\s*100%\s*-\s*(\d+(?:\.\d+)?|\.\d+)px\s*\)\s*$",
    re.IGNORECASE,
)
_SOFT_EDGE_ZERO_END_RE = re.compile(r"(?:0(?:\.0+)?(?:px|%))\s*$", re.IGNORECASE)
_SOFT_EDGE_FULL_END_RE = re.compile(r"100(?:\.0+)?%\s*$", re.IGNORECASE)
_FILL_OVERLAY_BLEND: dict[str, FillOverlayBlend] = {
    "multiply": "mult",
    "screen": "screen",
    "darken": "darken",
    "lighten": "lighten",
}


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


def parse_blur_filter(value: str | None) -> Blur | None:
    """Map a lone CSS ``blur(<px>)`` filter to native DrawingML blur.

    Compound filters and non-pixel lengths remain on the layered fallback path because their
    ordering and units cannot be represented by one ``a:blur`` node without approximation.
    """
    if not value or value.strip().lower() == "none":
        return None
    match = _BLUR_FILTER_RE.fullmatch(value.strip())
    if match is None:
        return None
    return Blur(radius_emu=px_to_emu(float(match.group(1))))


def parse_box_reflection(value: str | None) -> Reflection | None:
    """Map a conservative computed ``-webkit-box-reflect`` value to DrawingML reflection.

    PowerPoint's current IR models a reflection below the shape. Other directions, non-pixel
    gaps, and masks outside a vertical two-stop 0%-to-100% fade stay on the element-layer path.
    CSS box reflection has no independent blur control, so authored CSS maps to ``blur_emu=0``.
    """
    if not value or value.strip().lower() == "none":
        return None
    normalized = value.strip()
    match = _BOX_REFLECTION_RE.match(normalized)
    gradient = _gradient_body(normalized)
    if match is None or gradient is None or gradient[1]:
        return None
    parts = [part.strip() for part in _split_top_level(gradient[0])]
    if parts and parse_color(parts[0]) is None:
        direction = parts.pop(0).lower()
        if direction not in {"to bottom", "180deg"}:
            return None
    if len(parts) != 2:
        return None
    colors = tuple(parse_color(part) for part in parts)
    positions = tuple(_PERCENT_RE.search(part) for part in parts)
    if any(color is None for color in colors) or any(position is None for position in positions):
        return None
    start_position, end_position = positions
    if (
        start_position is None
        or end_position is None
        or float(start_position.group(1)) != 0.0
        or float(end_position.group(1)) != 100.0
    ):
        return None
    start_color, end_color = colors
    assert start_color is not None and end_color is not None
    return Reflection(
        distance_emu=px_to_emu(float(match.group(1))),
        start_alpha=start_color.a,
        end_alpha=end_color.a,
    )


def _soft_edge_axis(layer: str, *, direction: str) -> float | None:
    """Return the feather radius for one strict computed linear-gradient mask axis."""
    normalized = layer.strip()
    prefix = "linear-gradient("
    if not normalized.lower().startswith(prefix) or not normalized.endswith(")"):
        return None
    parts = [part.strip() for part in _split_top_level(normalized[len(prefix) : -1])]
    if parts and parse_color(parts[0]) is None:
        actual_direction = parts.pop(0).lower()
        if actual_direction != direction:
            return None
    elif direction != "to bottom":
        return None
    if len(parts) != 4:
        return None
    colors = tuple(parse_color(part) for part in parts)
    if any(color is None for color in colors):
        return None
    first, near_inner, far_inner, last = colors
    assert first is not None and near_inner is not None
    assert far_inner is not None and last is not None
    if first.a != 0.0 or near_inner.a != 1.0 or far_inner.a != 1.0 or last.a != 0.0:
        return None
    near_match = _SOFT_EDGE_INNER_END_RE.search(parts[1])
    far_match = _SOFT_EDGE_FAR_INNER_END_RE.search(parts[2])
    if (
        _SOFT_EDGE_ZERO_END_RE.search(parts[0]) is None
        or near_match is None
        or far_match is None
        or _SOFT_EDGE_FULL_END_RE.search(parts[3]) is None
    ):
        return None
    near_radius = float(near_match.group(1))
    far_radius = float(far_match.group(1))
    if near_radius <= 0.0 or near_radius != far_radius:
        return None
    return near_radius


def _soft_edge_ellipse(layer: str) -> float | None:
    """Return the feather radius for the strict computed ellipse mask form."""
    normalized = layer.strip()
    prefix = "radial-gradient("
    if not normalized.lower().startswith(prefix) or not normalized.endswith(")"):
        return None
    parts = [part.strip() for part in _split_top_level(normalized[len(prefix) : -1])]
    if len(parts) != 3 or parts[0].lower() != "closest-side":
        return None
    inner, outer = parse_color(parts[1]), parse_color(parts[2])
    radius = _SOFT_EDGE_FAR_INNER_END_RE.search(parts[1])
    if (
        inner is None
        or outer is None
        or inner.a != 1.0
        or outer.a != 0.0
        or radius is None
        or _SOFT_EDGE_FULL_END_RE.search(parts[2]) is None
    ):
        return None
    radius_px = float(radius.group(1))
    return radius_px if radius_px > 0.0 else None


def _default_two_layer_mask_value(value: str | None, expected: str) -> bool:
    if value is None:
        return True
    return [part.strip().lower() for part in _split_top_level(value)] in (
        [expected],
        [expected, expected],
    )


def parse_soft_edge_mask(
    value: str | None,
    composite: str | None,
    *,
    repeat: str | None = None,
    position: str | None = None,
    size: str | None = None,
    origin: str | None = None,
    clip: str | None = None,
    mode: str | None = None,
    ellipse: bool = False,
) -> SoftEdge | None:
    """Map domOXML's conservative CSS feather masks to DrawingML soft edge.

    Rectangles require two intersecting alpha gradients with equal pixel radii. Ellipses require a
    closest-side radial alpha gradient. Other masks stay on the visible element-layer path rather
    than being approximated as ``a:softEdge``.
    """
    if not value or value.strip().lower() == "none":
        return None
    layers = _split_top_level(value)
    composites = [part.strip().lower() for part in _split_top_level(composite or "")]
    expected_layers = 1 if ellipse else 2
    if len(layers) != expected_layers or composites not in (
        ["intersect"],
        ["intersect", "intersect"],
    ):
        return None
    if not all(
        (
            _default_two_layer_mask_value(repeat, "repeat"),
            _default_two_layer_mask_value(position, "0% 0%"),
            _default_two_layer_mask_value(size, "auto"),
            _default_two_layer_mask_value(origin, "border-box"),
            _default_two_layer_mask_value(clip, "border-box"),
            _default_two_layer_mask_value(mode, "match-source"),
        )
    ):
        return None
    if ellipse:
        radius = _soft_edge_ellipse(layers[0])
        return SoftEdge(radius_emu=px_to_emu(radius)) if radius is not None else None
    horizontal = _soft_edge_axis(layers[0], direction="to right")
    vertical = _soft_edge_axis(layers[1], direction="to bottom")
    if horizontal is None or vertical is None or horizontal != vertical:
        return None
    return SoftEdge(radius_emu=px_to_emu(horizontal))


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


def parse_fill_overlay(
    background_image: str | None,
    background_color: str | None,
    blend_mode: str | None,
    *,
    background_size: str | None = None,
    background_position: str | None = None,
    background_repeat: str | None = None,
    background_origin: str | None = None,
    background_clip: str | None = None,
) -> tuple[SolidFill, FillOverlay] | None:
    """Parse one uniform CSS gradient with a proven DrawingML blend equivalent."""
    blend = (blend_mode or "normal").strip().lower()
    if "," in blend or blend not in _FILL_OVERLAY_BLEND:
        return None
    geometry = _background_layer_values(
        1,
        background_size=background_size,
        background_position=background_position,
        background_repeat=background_repeat,
        background_origin=background_origin,
        background_clip=background_clip,
    )
    if geometry is None or not _overlay_layer_covers_shape(geometry, 0):
        return None
    base_color = parse_color(background_color)
    overlay = parse_gradient(background_image)
    if base_color is None or base_color.a <= 0.0 or overlay is None:
        return None
    overlay_color = overlay.stops[0].color
    if any(stop.color != overlay_color for stop in overlay.stops[1:]):
        return None
    return (
        SolidFill(color=base_color),
        FillOverlay(
            fill=SolidFill(color=overlay_color),
            blend=_FILL_OVERLAY_BLEND[blend],
        ),
    )


def fill_overlay_base_styles(
    background_image: str | None,
    blend_mode: str | None,
    effect: FillOverlay,
    *,
    background_size: str | None = None,
    background_position: str | None = None,
    background_repeat: str | None = None,
    background_origin: str | None = None,
    background_clip: str | None = None,
) -> dict[str, str] | None:
    """Remove one validated normalized-HTML overlay layer and recover base-layer CSS."""
    layers = _split_top_level(background_image or "")
    modes = [part.strip().lower() for part in _split_top_level(blend_mode or "")]
    expected = {
        "mult": "multiply",
        "screen": "screen",
        "darken": "darken",
        "lighten": "lighten",
    }[effect.blend]
    if not layers or len(modes) != len(layers) or modes[0] != expected:
        return None
    if any(mode != "normal" for mode in modes[1:]):
        return None
    overlay = parse_gradient(layers[0])
    if overlay is None or any(
        (stop.color.r, stop.color.g, stop.color.b)
        != (effect.fill.color.r, effect.fill.color.g, effect.fill.color.b)
        or abs(stop.color.a - effect.fill.color.a) > (1 / 255)
        for stop in overlay.stops
    ):
        return None
    geometry = _background_layer_values(
        len(layers),
        background_size=background_size,
        background_position=background_position,
        background_repeat=background_repeat,
        background_origin=background_origin,
        background_clip=background_clip,
    )
    if geometry is None or not _overlay_layer_covers_shape(geometry, 0):
        return None
    base_styles = {
        "backgroundImage": ",".join(layers[1:]) or "none",
        "backgroundBlendMode": ",".join(modes[1:]) or "normal",
    }
    for css_name, style_name in (
        ("backgroundSize", "backgroundSize"),
        ("backgroundPosition", "backgroundPosition"),
        ("backgroundRepeat", "backgroundRepeat"),
        ("backgroundOrigin", "backgroundOrigin"),
        ("backgroundClip", "backgroundClip"),
    ):
        values = geometry[css_name]
        base_styles[style_name] = ",".join(values[1:]) or values[0]
    return base_styles


def _background_layer_values(
    layer_count: int,
    *,
    background_size: str | None,
    background_position: str | None,
    background_repeat: str | None,
    background_origin: str | None,
    background_clip: str | None,
) -> dict[str, tuple[str, ...]] | None:
    defaults = {
        "backgroundSize": "auto",
        "backgroundPosition": "0% 0%",
        "backgroundRepeat": "repeat",
        "backgroundOrigin": "padding-box",
        "backgroundClip": "border-box",
    }
    raw = {
        "backgroundSize": background_size,
        "backgroundPosition": background_position,
        "backgroundRepeat": background_repeat,
        "backgroundOrigin": background_origin,
        "backgroundClip": background_clip,
    }
    resolved: dict[str, tuple[str, ...]] = {}
    for name, default in defaults.items():
        parts = tuple(part.strip().lower() for part in _split_top_level(raw[name] or default))
        if not parts or len(parts) > layer_count:
            return None
        resolved[name] = tuple(parts[index % len(parts)] for index in range(layer_count))
    return resolved


def _overlay_layer_covers_shape(geometry: dict[str, tuple[str, ...]], index: int) -> bool:
    size = geometry["backgroundSize"][index]
    return (
        size in {"auto", "auto auto", "100% 100%"}
        and geometry["backgroundPosition"][index] == "0% 0%"
        and geometry["backgroundOrigin"][index] == "padding-box"
        and geometry["backgroundClip"][index] == "border-box"
    )


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
