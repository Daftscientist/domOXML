"""Preset DrawingML geometry vertex math (ECMA-376 Part 1 §20.1.10.56).

This module is the **single source of truth** for the polygon vertex formulas used by both:
- the forward path (``domoxml.core.ir.extract`` + ``domoxml.core.ir.parse``) to match
  ``clip-path: polygon(...)`` CSS to a native ``prstGeom``; and
- the reverse path (``domoxml.core.html``) to emit ``clip-path: polygon(...)`` CSS from a
  ``prstGeom`` IR node.

All functions return vertices as ``list[tuple[float, float]]`` in the **unit square** [0,1]²:
  ``(0,0)`` is top-left, ``(1,0)`` is top-right, ``(1,1)`` is bottom-right.

Callers scale to pixel/EMU coordinates by multiplying ``x`` by ``width`` and ``y`` by
``height``.  The returned polygon is a closed shape; do **not** repeat the first vertex.

``adj`` is a mapping of DrawingML guide-name → value where values are in the ECMA-376
normalised fraction space **[0, 1]** (DrawingML stores them as integers in [0, 100000]).
Missing keys fall back to the ECMA-376 default value for that preset.

**Only polygon-expressible presets** are included here — ones whose outlines consist
entirely of straight-line segments at their default ``adj`` values.  Curved presets
(``arc``, ``callout``, ``gear``, ``wave``, ``funnel``, …) are not represented.
"""

from __future__ import annotations

import math
from collections.abc import Callable

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

type Vertices = list[tuple[float, float]]
type VertexFn = Callable[[dict[str, float]], Vertices]

_REGISTRY: dict[str, VertexFn] = {}
# Maps preset name → default adj dict (ECMA-376 normalised fractions).
_DEFAULTS: dict[str, dict[str, float]] = {}


def _register(
    name: str, defaults: dict[str, float] | None = None
) -> Callable[[VertexFn], VertexFn]:
    """Decorator: register a preset vertex function and its adj defaults."""

    def _decorator(fn: VertexFn) -> VertexFn:
        _REGISTRY[name] = fn
        _DEFAULTS[name] = defaults or {}
        return fn

    return _decorator


def _adj(name: str, adj: dict[str, float], default: float) -> float:
    """Look up an adj guide value, clamped to [0, 1]."""
    return max(0.0, min(1.0, adj.get(name, default)))


# ---------------------------------------------------------------------------
# Simple convex shapes
# ---------------------------------------------------------------------------


@_register("triangle", {"adj": 0.5})
def _triangle(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Isoceles triangle; adj = position of apex along the top (0=left, 1=right).
    # ECMA: bottom-left, bottom-right, apex-top.
    a = _adj("adj", adj, 0.5)
    return [(0.0, 1.0), (1.0, 1.0), (a, 0.0)]


@_register("rtTriangle")
def _rt_triangle(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Right-angle triangle: right angle at bottom-left.
    return [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


@_register("diamond")
def _diamond(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    return [(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5)]


@_register("pentagon", {"adj": 105_400 / 100_000})
def _pentagon(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Regular pentagon.  ECMA uses a guide but default is a regular pentagon.
    # Vertices at angles: -90, -90+72, -90+144, -90+216, -90+288 from centre.
    verts: Vertices = []
    for k in range(5):
        angle = math.radians(-90 + k * 72)
        verts.append((0.5 + 0.5 * math.cos(angle), 0.5 + 0.5 * math.sin(angle)))
    return verts


@_register("hexagon", {"adj": 25_000 / 100_000})
def _hexagon(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Flat-top hexagon.  ``adj`` sets the short-side length as a fraction of width.
    # ECMA default adj = 25000, meaning the flat top = 25% of width each side inset.
    a = _adj("adj", adj, 25_000 / 100_000)
    return [
        (a, 0.0),
        (1.0 - a, 0.0),
        (1.0, 0.5),
        (1.0 - a, 1.0),
        (a, 1.0),
        (0.0, 0.5),
    ]


@_register("octagon", {"adj": 29_289 / 100_000})
def _octagon(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 29_289 / 100_000)
    return [
        (a, 0.0),
        (1.0 - a, 0.0),
        (1.0, a),
        (1.0, 1.0 - a),
        (1.0 - a, 1.0),
        (a, 1.0),
        (0.0, 1.0 - a),
        (0.0, a),
    ]


# ---------------------------------------------------------------------------
# Quadrilaterals
# ---------------------------------------------------------------------------


@_register("parallelogram", {"adj": 25_000 / 100_000})
def _parallelogram(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Slants right; ``adj`` = shear fraction of width.
    a = _adj("adj", adj, 25_000 / 100_000)
    return [(a, 0.0), (1.0, 0.0), (1.0 - a, 1.0), (0.0, 1.0)]


@_register("trapezoid", {"adj": 25_000 / 100_000})
def _trapezoid(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Bottom-wider trapezoid; ``adj`` = inset of top corners from each side.
    a = _adj("adj", adj, 25_000 / 100_000)
    return [(0.0, 1.0), (1.0, 1.0), (1.0 - a, 0.0), (a, 0.0)]


# ---------------------------------------------------------------------------
# Arrow / chevron shapes
# ---------------------------------------------------------------------------


@_register("chevron", {"adj": 50_000 / 100_000})
def _chevron(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Right-pointing chevron (open arrow without a tail).
    # ``adj`` = position of the notch from the left (depth of the cut).
    a = _adj("adj", adj, 50_000 / 100_000)
    return [
        (0.0, 0.0),
        (a, 0.0),
        (1.0, 0.5),
        (a, 1.0),
        (0.0, 1.0),
        (1.0 - a, 0.5),
    ]


@_register("rightArrow", {"adj": 50_000 / 100_000, "adj2": 50_000 / 100_000})
def _right_arrow(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # ``adj`` = width of the arrowhead as fraction of total width.
    # ``adj2`` = shaft height as fraction of total height (centred).
    a = _adj("adj", adj, 50_000 / 100_000)
    b = _adj("adj2", adj, 50_000 / 100_000)
    shaft_top = (1.0 - b) / 2.0
    shaft_bot = 1.0 - shaft_top
    return [
        (0.0, shaft_top),
        (1.0 - a, shaft_top),
        (1.0 - a, 0.0),
        (1.0, 0.5),
        (1.0 - a, 1.0),
        (1.0 - a, shaft_bot),
        (0.0, shaft_bot),
    ]


@_register("leftArrow", {"adj": 50_000 / 100_000, "adj2": 50_000 / 100_000})
def _left_arrow(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 50_000 / 100_000)
    b = _adj("adj2", adj, 50_000 / 100_000)
    shaft_top = (1.0 - b) / 2.0
    shaft_bot = 1.0 - shaft_top
    return [
        (0.0, 0.5),
        (a, 0.0),
        (a, shaft_top),
        (1.0, shaft_top),
        (1.0, shaft_bot),
        (a, shaft_bot),
        (a, 1.0),
    ]


@_register("upArrow", {"adj": 50_000 / 100_000, "adj2": 50_000 / 100_000})
def _up_arrow(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 50_000 / 100_000)
    b = _adj("adj2", adj, 50_000 / 100_000)
    shaft_left = (1.0 - b) / 2.0
    shaft_right = 1.0 - shaft_left
    return [
        (0.5, 0.0),
        (1.0, a),
        (shaft_right, a),
        (shaft_right, 1.0),
        (shaft_left, 1.0),
        (shaft_left, a),
        (0.0, a),
    ]


@_register("downArrow", {"adj": 50_000 / 100_000, "adj2": 50_000 / 100_000})
def _down_arrow(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 50_000 / 100_000)
    b = _adj("adj2", adj, 50_000 / 100_000)
    shaft_left = (1.0 - b) / 2.0
    shaft_right = 1.0 - shaft_left
    return [
        (shaft_left, 0.0),
        (shaft_right, 0.0),
        (shaft_right, 1.0 - a),
        (1.0, 1.0 - a),
        (0.5, 1.0),
        (0.0, 1.0 - a),
        (shaft_left, 1.0 - a),
    ]


# ---------------------------------------------------------------------------
# Plus / cross
# ---------------------------------------------------------------------------


@_register("plus", {"adj": 25_000 / 100_000})
def _plus(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    # Symmetric plus/cross; ``adj`` = arm half-width fraction of the shorter side.
    a = _adj("adj", adj, 25_000 / 100_000)
    return [
        (a, 0.0),
        (1.0 - a, 0.0),
        (1.0 - a, a),
        (1.0, a),
        (1.0, 1.0 - a),
        (1.0 - a, 1.0 - a),
        (1.0 - a, 1.0),
        (a, 1.0),
        (a, 1.0 - a),
        (0.0, 1.0 - a),
        (0.0, a),
        (a, a),
    ]


# ---------------------------------------------------------------------------
# Star shapes — polygon approximations (no curves)
# ---------------------------------------------------------------------------


def _star_vertices(n: int, inner_r: float) -> Vertices:
    """Regular n-pointed star with given inner radius (outer = 0.5)."""
    verts: list[tuple[float, float]] = []
    for k in range(n):
        # Outer point
        outer_angle = math.radians(-90 + k * 360 / n)
        verts.append((0.5 + 0.5 * math.cos(outer_angle), 0.5 + 0.5 * math.sin(outer_angle)))
        # Inner valley
        inner_angle = math.radians(-90 + (k + 0.5) * 360 / n)
        verts.append((0.5 + inner_r * math.cos(inner_angle), 0.5 + inner_r * math.sin(inner_angle)))
    return verts


@_register("star4", {"adj": 12_500 / 100_000})
def _star4(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 12_500 / 100_000)
    return _star_vertices(4, a)


@_register("star5", {"adj": 19_098 / 100_000})
def _star5(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 19_098 / 100_000)
    return _star_vertices(5, a)


@_register("star8", {"adj": 20_451 / 100_000})
def _star8(adj: dict[str, float]) -> Vertices:  # pyright: ignore[reportUnusedFunction]
    a = _adj("adj", adj, 20_451 / 100_000)
    return _star_vertices(8, a)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Preset names for which this module can produce a polygon (``clip-path: polygon(...)``).
#: ``rect``/``roundRect``/``ellipse`` are intentionally absent — handled by the border-radius
#: path.  Curved presets (waves, callouts, gears, …) are also absent.
POLYGON_PRESETS: frozenset[str] = frozenset(_REGISTRY)


def preset_vertices(kind: str, adj: dict[str, float] | None = None) -> Vertices | None:
    """Return unit-square vertices for ``kind`` with ``adj`` overrides, or ``None`` if
    ``kind`` is not a polygon-expressible preset (ellipse, roundRect, rect, or curved)."""
    fn = _REGISTRY.get(kind)
    if fn is None:
        return None
    merged: dict[str, float] = dict(_DEFAULTS.get(kind, {}))
    if adj:
        merged.update(adj)
    return fn(merged)


def preset_defaults(kind: str) -> dict[str, float]:
    """Return the default adj mapping for ``kind`` (empty dict if kind is unknown or has no adj)."""
    return dict(_DEFAULTS.get(kind, {}))


# ---------------------------------------------------------------------------
# Polygon matching (forward path)
# ---------------------------------------------------------------------------

# Tolerance: each vertex must be within this fraction of the bounding-box diagonal.
_MATCH_TOLERANCE: float = 0.015  # 1.5%


def _normalise_polygon(
    raw: list[tuple[float, float]], width: float, height: float
) -> list[tuple[float, float]]:
    """Convert absolute pixel polygon to unit-square coordinates."""
    if width <= 0 or height <= 0:
        return []
    return [(x / width, y / height) for x, y in raw]


def _vertices_close(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
    tol: float,
) -> bool:
    """True when every vertex in ``a`` is within ``tol`` of the corresponding vertex in ``b``."""
    if len(a) != len(b):
        return False
    return all(
        abs(ax - bx) <= tol and abs(ay - by) <= tol for (ax, ay), (bx, by) in zip(a, b, strict=True)
    )


def _cyclic_match(
    candidate: list[tuple[float, float]],
    reference: list[tuple[float, float]],
    tol: float,
) -> bool:
    """True when ``candidate`` matches ``reference`` at any cyclic rotation (or reversed)."""
    n = len(candidate)
    if len(reference) != n:
        return False
    # Try all cyclic rotations of reference
    for start in range(n):
        rotated = reference[start:] + reference[:start]
        if _vertices_close(candidate, rotated, tol):
            return True
    # Also try reversed reference
    rev = list(reversed(reference))
    for start in range(n):
        rotated = rev[start:] + rev[:start]
        if _vertices_close(candidate, rotated, tol):
            return True
    return False


def match_polygon(
    polygon: list[tuple[float, float]],
    width_px: float,
    height_px: float,
    *,
    tolerance: float = _MATCH_TOLERANCE,
) -> str | None:
    """Try to match a ``clip-path: polygon(...)`` against the registered polygon presets.

    ``polygon`` is a list of ``(x_px, y_px)`` absolute pixel coordinates.
    ``width_px``/``height_px`` are the element's bounding box dimensions.

    Returns the matched preset name (``GeometryKind`` literal) or ``None``.

    The comparison is done in the unit square, with cyclic and reversed-winding tolerance,
    so that the authoring order of vertices does not matter.
    """
    if not polygon or width_px <= 0 or height_px <= 0:
        return None
    candidate = _normalise_polygon(polygon, width_px, height_px)
    n = len(candidate)
    for kind, fn in _REGISTRY.items():
        defaults = _DEFAULTS.get(kind, {})
        ref = fn(defaults)
        if len(ref) != n:
            continue
        if _cyclic_match(candidate, ref, tolerance):
            return kind
    return None
