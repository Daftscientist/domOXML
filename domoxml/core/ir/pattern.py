"""Detect a CSS ``repeating-linear-gradient`` two-colour stripe pattern and map it to a
DrawingML ``a:pattFill`` preset (forward HTML->PPTX), plus the inverse mapping for the reverse
path.

PowerPoint's ``a:pattFill`` is a two-colour preset hatch/stripe (ECMA-376 §20.1.10.51,
``ST_PresetPatternVal``, ~54 presets). On the web the closest *editable* CSS source is a
``repeating-linear-gradient`` with exactly two alternating colours and hard stops, e.g.::

    repeating-linear-gradient(45deg, #111 0, #111 1px, #eee 1px, #eee 4px)

Only clean, unambiguous stripes map natively. The matcher is strict on purpose: three or more
distinct colours, soft (non-coincident) stops, or an off-axis angle yield ``None`` so the
extractor falls back to the existing raster/warning path unchanged.

Forward mapping is deliberately limited to calibrated CSS bands matching Office's fixed preset
density. Light line presets use a 1px foreground line plus a 3px background gap; wide presets
use equal 8px bands:

    | CSS angle  | stripes        | foreground/gap | preset    |
    |------------|----------------|----------------|-----------|
    | 0 / 180    | horizontal     | 1px / 3px      | horz      |
    | 90 / 270   | vertical       | 1px / 3px      | vert      |
    | 45         | up-diag (/)    | 1px / 3px      | ltUpDiag  |
    | 45         | up-diag (/)    | 8px / 8px      | wdUpDiag  |
    | 135        | down-diag (\\) | 1px / 3px      | ltDnDiag  |
    | 135        | down-diag (\\) | 8px / 8px      | dkUpDiag  |

These six presets are exactly the forward-emitted set; the reverse path maps each back to the
identical ``repeating-linear-gradient`` so the round trip is stable.
"""

from __future__ import annotations

import re

from domoxml.core.ir.model import PatternFill, Rgba
from domoxml.core.ir.parse import parse_color

# Angle matching tolerance (deg). Authors write exact axis angles; allow tiny float drift.
_ANGLE_TOL = 1.0
# CSS computed styles may carry small decimal drift around canonical pixel widths.
_WIDTH_TOL = 0.05

_FUNC_RE = re.compile(r"\brepeating-linear-gradient\s*\(", re.IGNORECASE)
_ANGLE_RE = re.compile(r"^\s*(-?[\d.]+)\s*deg\s*$", re.IGNORECASE)
_LEN_RE = re.compile(r"(-?[\d.]+)\s*px", re.IGNORECASE)
_RGB_STRIP_RE = re.compile(r"rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}|[a-zA-Z]+", re.IGNORECASE)

# Canonical native presets keyed by angle. Entries are (preset, foreground width, gap width).
_FORWARD_PATTERNS: dict[int, tuple[tuple[str, float, float], ...]] = {
    0: (("horz", 1.0, 3.0),),
    90: (("vert", 1.0, 3.0),),
    45: (("ltUpDiag", 1.0, 3.0), ("wdUpDiag", 8.0, 8.0)),
    135: (("ltDnDiag", 1.0, 3.0), ("dkUpDiag", 8.0, 8.0)),
}


def _split_top_level(value: str) -> list[str]:
    """Split on commas not inside parentheses (paren-aware; mirrors parse.py)."""
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


def _gradient_body(value: str) -> str | None:
    """Return the inner arguments of the first ``repeating-linear-gradient(...)``, or ``None``.

    Returns ``None`` if there is more than one top-level layer (stacked gradients are not a
    single native pattern)."""
    if len(_split_top_level(value)) > 1:
        return None
    match = _FUNC_RE.search(value)
    if match is None:
        return None
    start = match.end()
    depth = 1
    for i in range(start, len(value)):
        if value[i] == "(":
            depth += 1
        elif value[i] == ")":
            depth -= 1
            if depth == 0:
                return value[start:i]
    return None


def _normalise_angle(deg: float) -> int | None:
    """Snap a CSS angle to one of the four supported axes (0/45/90/135), or ``None``.

    Angles 180/270/225/315 fold onto their 0/90/45/135 equivalents (a stripe pattern is the
    same under a 180 flip)."""
    folded = deg % 180.0
    for axis in (0, 45, 90, 135):
        if abs(folded - axis) <= _ANGLE_TOL or abs(folded - (axis + 180)) <= _ANGLE_TOL:
            return axis
    # 180 folds to 0; handle the exact-180 case (folded == 0 already covers it).
    return None


_BARE_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*$")


def _parse_stop(arg: str) -> tuple[Rgba, float] | None:
    """Parse ``"<color> <len>"`` into ``(colour, position_px)``; ``None`` if no colour.

    The length may be ``Npx`` or a bare ``0`` (CSS allows a unitless zero); a stop with a colour
    but no parseable position is rejected so soft (positionless) gradients do not match."""
    color = parse_color(arg)
    if color is None:
        return None
    match = _LEN_RE.search(arg)
    if match is not None:
        return color, float(match.group(1))
    # Bare numeric position (only a unitless 0 is valid CSS, but accept any for robustness).
    remainder = _RGB_STRIP_RE.sub("", arg).strip()
    bare = _BARE_NUM_RE.search(remainder)
    if bare is not None:
        return color, float(bare.group(1))
    return None


def match_pattern_fill(background_image: str | None) -> PatternFill | None:
    """Map a CSS ``repeating-linear-gradient`` two-colour stripe to a :class:`PatternFill`.

    Returns ``None`` (so the caller keeps its existing raster/gradient handling) unless the
    value is a single ``repeating-linear-gradient`` at 0/45/90/135deg with exactly two
    alternating colours and hard stops matching a calibrated native preset.
    """
    if not background_image or "repeating-linear-gradient" not in background_image.lower():
        return None
    body = _gradient_body(background_image)
    if body is None:
        return None
    args = _split_top_level(body)
    if not args:
        return None

    # First arg may be the angle. Bare colours imply the default 180deg (-> horz).
    angle_deg = 180.0
    angle_match = _ANGLE_RE.match(args[0])
    if angle_match is not None and parse_color(args[0]) is None:
        angle_deg = float(angle_match.group(1))
        args = args[1:]
    elif parse_color(args[0]) is None:
        # A non-angle, non-colour leading token (e.g. "to right") is not supported.
        return None

    axis = _normalise_angle(angle_deg)
    if axis is None:
        return None

    stops = [parsed for arg in args if (parsed := _parse_stop(arg)) is not None]
    # A two-colour hard-stop stripe needs exactly 4 stops: c1@0, c1@W, c2@W, c2@2W.
    if len(stops) != 4:
        return None
    (c0, p0), (c1, p1), (c2, p2), (c3, p3) = stops

    # Exactly two distinct colours, alternating.
    if c0.hex != c1.hex or c2.hex != c3.hex or c0.hex == c2.hex:
        return None
    if c0.a < 1.0 or c2.a < 1.0:
        # Pattern presets are two opaque colours; translucent stripes are not a clean match.
        return None

    # Hard stops: foreground is [p0, p1], background is [p1=p2, p3].
    foreground_width = p1 - p0
    if foreground_width <= 0 or abs(p2 - p1) > 1e-6:
        return None
    gap_width = p3 - p2
    if gap_width <= 0 or abs(p0) > 1e-6:
        return None

    for preset, expected_foreground, expected_gap in _FORWARD_PATTERNS.get(axis, ()):
        if (
            abs(foreground_width - expected_foreground) <= _WIDTH_TOL
            and abs(gap_width - expected_gap) <= _WIDTH_TOL
        ):
            # fg = the stripe (first) colour, bg = the gap (second) colour.
            return PatternFill(preset=preset, fg=c0, bg=c2)
    return None


# ----------------------------------------------------------------------- reverse: pattFill -> CSS

# Inverse of _FORWARD_PRESET: the six presets that round-trip to an exact
# ``repeating-linear-gradient``. Value is ``(angle, foreground width, total period)``.
_REVERSE_EXACT: dict[str, tuple[int, int, int]] = {
    "horz": (0, 1, 4),
    "vert": (90, 1, 4),
    "ltUpDiag": (45, 1, 4),
    "wdUpDiag": (45, 8, 16),
    "ltDnDiag": (135, 1, 4),
    "dkUpDiag": (135, 8, 16),
}

# Every other ECMA preset is approximated with an 8x8 SVG tile. The value chooses the tile
# geometry family; the warning notes the approximation. This is not exhaustive geometry — it is
# a deliberately small, recognisable approximation (lines/dots/grid/diagonals).
_HORZ_PRESETS = frozenset(
    {"horz", "ltHorz", "dkHorz", "narHorz", "horzBrick", "dashHorz", "smGrid", "lgGrid"}
)
_VERT_PRESETS = frozenset({"vert", "ltVert", "dkVert", "narVert", "dashVert"})
_UP_PRESETS = frozenset({"upDiag", "ltUpDiag", "dkUpDiag", "wdUpDiag", "diagBrick", "dashUpDiag"})
_DN_PRESETS = frozenset({"dnDiag", "ltDnDiag", "dkDnDiag", "wdDnDiag", "dashDnDiag"})
_GRID_PRESETS = frozenset({"cross", "smGrid", "lgGrid", "weave", "plaid", "trellis"})
_DIAG_GRID_PRESETS = frozenset({"diagCross", "openDmnd", "solidDmnd", "dotDmnd", "shingle"})
_DOT_PRESETS = frozenset(
    {"pct5", "pct10", "pct20", "pct25", "dotGrid", "smConfetti", "lgConfetti", "sphere", "dotDmnd"}
)


def _hex_to_rgb(hex6: str) -> str:
    """``"AABBCC"`` -> ``"rgb(170,187,204)"`` so emitted CSS round-trips through the matcher
    (which reads browser-computed ``rgb()`` values)."""
    r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    return f"rgb({r},{g},{b})"


def _svg_tile(fg_hex: str, bg_hex: str, kind: str) -> str:
    """An 8x8 SVG tile (data URI) approximating a pattern preset, tiled via background-repeat."""
    body = {
        "horz": '<rect width="8" height="8" fill="#BG"/><rect width="8" height="2" fill="#FG"/>',
        "vert": '<rect width="8" height="8" fill="#BG"/><rect width="2" height="8" fill="#FG"/>',
        "up": '<rect width="8" height="8" fill="#BG"/>'
        '<path d="M0 8 L8 0" stroke="#FG" stroke-width="1.5"/>',
        "dn": '<rect width="8" height="8" fill="#BG"/>'
        '<path d="M0 0 L8 8" stroke="#FG" stroke-width="1.5"/>',
        "grid": '<rect width="8" height="8" fill="#BG"/>'
        '<path d="M0 0 H8 M0 0 V8" stroke="#FG" stroke-width="1"/>',
        "diagGrid": '<rect width="8" height="8" fill="#BG"/>'
        '<path d="M0 8 L8 0 M0 0 L8 8" stroke="#FG" stroke-width="1"/>',
        "dot": '<rect width="8" height="8" fill="#BG"/><circle cx="2" cy="2" r="1.3" fill="#FG"/>',
    }[kind]
    svg = (
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 8 8">'
            f"{body}</svg>"
        )
        .replace("#FG", f"#{fg_hex}")
        .replace("#BG", f"#{bg_hex}")
    )
    # Percent-encode the few characters that matter in a data URI (no base64 -> human readable).
    encoded = svg.replace("#", "%23").replace("<", "%3C").replace(">", "%3E").replace('"', "'")
    return f'url("data:image/svg+xml,{encoded}")'


def _tile_kind(preset: str) -> str:
    if preset in _DOT_PRESETS:
        return "dot"
    if preset in _DIAG_GRID_PRESETS:
        return "diagGrid"
    if preset in _GRID_PRESETS:
        return "grid"
    if preset in _UP_PRESETS:
        return "up"
    if preset in _DN_PRESETS:
        return "dn"
    if preset in _VERT_PRESETS:
        return "vert"
    # default to horizontal lines for any unknown/remaining preset
    return "horz"


def pattern_to_css(fg_hex: str, bg_hex: str, preset: str) -> tuple[str, str, bool]:
    """Map an ``a:pattFill`` to CSS. Returns ``(property, value, approximated)`` where
    ``property`` is ``background`` (for the exact repeating-linear-gradient presets) or
    ``background-image`` (for the SVG-tile approximations), and ``approximated`` is ``True`` when
    a :class:`ConversionWarning` should be emitted.

    Colours are 6-digit hex strings (no ``#``).
    """
    exact = _REVERSE_EXACT.get(preset)
    if exact is not None:
        angle, foreground_width, period = exact
        fg = _hex_to_rgb(fg_hex)
        bg = _hex_to_rgb(bg_hex)
        value = (
            f"repeating-linear-gradient({angle}deg,"
            f"{fg} 0,{fg} {foreground_width}px,"
            f"{bg} {foreground_width}px,{bg} {period}px)"
        )
        return ("background", value, False)
    return ("background-image", _svg_tile(fg_hex, bg_hex, _tile_kind(preset)), True)
