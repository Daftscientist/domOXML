"""Parse the CSS computed-style strings Chromium reports into typed IR values."""

from __future__ import annotations

import re

from domoxml.core.ir.model import Rgba

_RGB_RE = re.compile(
    r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)",
    re.IGNORECASE,
)
_LENGTH_RE = re.compile(r"(-?[\d.]+)\s*px", re.IGNORECASE)


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
