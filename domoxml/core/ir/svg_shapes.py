"""An inline SVG as editable native shapes: one free-form shape per drawn element.

PowerPoint can draw SVG as a picture, but a picture cannot be edited. Most SVG is paths, basic
shapes, solid and linear-gradient paints, strokes and groups, and each of those has a native form:
a custom-geometry shape with its own fill and outline. This reads the standalone SVG the snapshot
captured (paint already inlined on every element), flattens groups and transforms into slide
coordinates and returns the shapes, or ``None`` when anything is used that has no exact native
form (filters, masks, clips, patterns, text, images, markers, ``<use>``, radial gradients with a
moved focus, non-uniform scaling of strokes). The caller then keeps the SVG as a vector picture.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException, ElementTree

from domoxml.core.ir.model import (
    Box,
    ClosePath,
    CubicTo,
    CustomGeometry,
    GradientFill,
    GradientStop,
    Line,
    LineTo,
    MoveTo,
    PathCommand,
    Point,
    Rgba,
    Shadow,
    ShapeNode,
    SolidFill,
)
from domoxml.core.ir.parse import parse_color
from domoxml.core.units import px_to_emu

_SVG = "http://www.w3.org/2000/svg"
_XLINK = "http://www.w3.org/1999/xlink"
_KAPPA = 0.5522847498
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_UNSUPPORTED = {
    "text",
    "image",
    "use",
    "symbol",
    "foreignobject",
    "pattern",
    "mask",
    "clippath",
    "marker",
    "filter",
    "switch",
    "a",
}
_PASSIVE = {"defs", "title", "desc", "metadata", "style", "lineargradient", "radialgradient"}
_CAPS = {"butt": "flat", "round": "round", "square": "square"}
_JOINS = {"miter": "miter", "round": "round", "bevel": "bevel", "miter-clip": "miter"}

type Pair = tuple[float, float]
type Segment = tuple[str, list[Pair]]


class _Unsupported(Exception):
    """The SVG uses something that has no exact native form."""


@dataclass(frozen=True)
class Affine:
    """``x' = a x + c y + e``, ``y' = b x + d y + f``."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def then(self, other: Affine) -> Affine:
        """``other`` applied first, then ``self``."""
        return Affine(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )

    def apply(self, point: Pair) -> Pair:
        x, y = point
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f

    def scale(self) -> float:
        """The uniform scale, or ``-1`` when the matrix stretches or skews unevenly."""
        sx, sy = math.hypot(self.a, self.b), math.hypot(self.c, self.d)
        orthogonal = abs(self.a * self.c + self.b * self.d) < 1e-6 * max(sx * sy, 1e-9)
        return sx if abs(sx - sy) <= 1e-6 * max(sx, sy, 1e-9) and orthogonal else -1.0


def _transform(text: str | None) -> Affine:
    result = Affine()
    for raw_name, body in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        name = raw_name.lower()
        v = [float(n) for n in _NUMBER.findall(body)]
        if name == "matrix" and len(v) == 6:
            step = Affine(*v)
        elif name == "translate" and v:
            step = Affine(e=v[0], f=v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            step = Affine(a=v[0], d=v[1] if len(v) > 1 else v[0])
        elif name == "rotate" and v:
            r = math.radians(v[0])
            turn = Affine(math.cos(r), math.sin(r), -math.sin(r), math.cos(r))
            if len(v) == 3:
                step = Affine(e=v[1], f=v[2]).then(turn).then(Affine(e=-v[1], f=-v[2]))
            else:
                step = turn
        elif name == "skewx" and v:
            step = Affine(c=math.tan(math.radians(v[0])))
        elif name == "skewy" and v:
            step = Affine(b=math.tan(math.radians(v[0])))
        else:
            raise _Unsupported(name)
        result = result.then(step)
    return result


def svg_to_shapes(
    source: str, *, box: Box, width_px: float, height_px: float
) -> list[ShapeNode] | None:
    """Native shapes for the SVG ``source`` drawn into ``box``, or ``None`` if it cannot be."""
    try:
        root = ElementTree.fromstring(source)
    except (ElementTree.ParseError, DefusedXmlException):
        return None
    try:
        reader = _Reader(root, box, width_px, height_px)
        shapes = reader.shapes()
    except (_Unsupported, ValueError, IndexError, ZeroDivisionError, OverflowError):
        return None
    return shapes or None


class _Reader:
    def __init__(self, root: Element, box: Box, width_px: float, height_px: float) -> None:
        if _local(root) != "svg":
            raise _Unsupported("root")
        self.root, self.box = root, box
        self.width_px, self.height_px = width_px, height_px
        self.gradients = {
            element.get("id", ""): element
            for element in root.iter()
            if _local(element) in ("lineargradient", "radialgradient") and element.get("id")
        }
        view = [float(n) for n in _NUMBER.findall(root.get("viewBox", ""))]
        if len(view) != 4:
            view = [0.0, 0.0, width_px, height_px]
        vx, vy, vw, vh = view
        if vw <= 0 or vh <= 0:
            raise _Unsupported("viewBox")
        align = (root.get("preserveAspectRatio") or "xMidYMid meet").split()
        if "slice" in align:
            raise _Unsupported("slice")
        if align[0].lower() == "none":
            sx, sy, tx, ty = width_px / vw, height_px / vh, 0.0, 0.0
        else:
            sx = sy = min(width_px / vw, height_px / vh)
            fx = {"min": 0.0, "mid": 0.5, "max": 1.0}.get(align[0][1:4].lower(), 0.5)
            fy = {"min": 0.0, "mid": 0.5, "max": 1.0}.get(align[0][5:8].lower(), 0.5)
            tx, ty = (width_px - vw * sx) * fx, (height_px - vh * sy) * fy
        self.base = Affine(sx, 0.0, 0.0, sy, tx - vx * sx, ty - vy * sy)

    def shapes(self) -> list[ShapeNode]:
        return list(self._walk(self.root, self.base, 1.0, None))

    def _walk(
        self, element: Element, matrix: Affine, opacity: float, shadow: Shadow | None
    ) -> Iterator[ShapeNode]:
        for child in element:
            name = _local(child)
            if name in _PASSIVE:
                continue
            if name in _UNSUPPORTED:
                raise _Unsupported(name)
            if _hidden(child):
                continue
            marker = child.get("data-domoxml-shadow")
            if marker is not None and name == "g":
                if shadow is not None:
                    raise _Unsupported("nested shadows")
                yield from self._walk(
                    child, matrix.then(_transform(child.get("transform"))), opacity, _shadow(marker)
                )
                continue
            if _attr(child, "filter") not in (None, "none") or _attr(child, "mask") not in (
                None,
                "none",
            ):
                raise _Unsupported("filter or mask")
            if _attr(child, "clip-path") not in (None, "none"):
                raise _Unsupported("clip-path")
            if any(
                _attr(child, key) not in (None, "none")
                for key in ("marker-start", "marker-mid", "marker-end")
            ):
                raise _Unsupported("marker")
            here = matrix.then(_transform(child.get("transform")))
            faded = opacity * _number(_attr(child, "opacity"), 1.0)
            if name == "g":
                yield from self._walk(child, here, faded, shadow)
            elif name in ("path", "rect", "circle", "ellipse", "line", "polyline", "polygon"):
                shape = self._shape(child, name, here, faded)
                if shape is not None:
                    yield shape.model_copy(update={"effects": (shadow,)}) if shadow else shape
            else:
                raise _Unsupported(name)

    def _shape(
        self, element: Element, name: str, matrix: Affine, opacity: float
    ) -> ShapeNode | None:
        local = _segments(element, name)
        if not local:
            return None
        own = [p for _kind, points in local for p in points]
        local_bounds = (
            min(p[0] for p in own),
            min(p[1] for p in own),
            max(p[0] for p in own),
            max(p[1] for p in own),
        )
        segments = [(kind, [matrix.apply(p) for p in points]) for kind, points in local]
        every = [p for _kind, points in segments for p in points]
        left, top = min(p[0] for p in every), min(p[1] for p in every)
        right, bottom = max(p[0] for p in every), max(p[1] for p in every)
        fill = self._fill(element, opacity, local_bounds, matrix)
        stroke = self._stroke(element, opacity, matrix)
        if fill is None and stroke is None:
            return None
        # An SVG clips its artwork to its own viewport; shapes would draw past it.
        reach = (stroke.width_emu / 9525 / 2) if stroke is not None else 0.0
        if (
            left - reach < -0.5
            or top - reach < -0.5
            or right + reach > self.width_px + 0.5
            or bottom + reach > self.height_px + 0.5
        ):
            raise _Unsupported("outside the viewport")
        width_emu, height_emu = max(1, px_to_emu(right - left)), max(1, px_to_emu(bottom - top))
        origin_x, origin_y = self.box.x + px_to_emu(left), self.box.y + px_to_emu(top)
        path: list[PathCommand] = []
        for kind, points in segments:
            emu = [Point(x=px_to_emu(x - left), y=px_to_emu(y - top)) for x, y in points]
            if kind == "M":
                path.append(MoveTo(to=emu[0]))
            elif kind == "L":
                path.append(LineTo(to=emu[0]))
            elif kind == "C":
                path.append(CubicTo(c1=emu[0], c2=emu[1], to=emu[2]))
            else:
                path.append(ClosePath())
        return ShapeNode(
            box=Box(x=origin_x, y=origin_y, width=width_emu, height=height_emu),
            custom_geom=CustomGeometry(
                width_emu=width_emu, height_emu=height_emu, path=tuple(path)
            ),
            fill=fill,
            line=stroke,
        )

    # paint ---------------------------------------------------------------------------------

    def _fill(
        self,
        element: Element,
        opacity: float,
        bounds: tuple[float, float, float, float],
        matrix: Affine,
    ) -> SolidFill | GradientFill | None:
        value = (_attr(element, "fill") or "black").strip()
        if value in ("none", "transparent"):
            return None
        alpha = _number(_attr(element, "fill-opacity"), 1.0) * opacity
        if value.startswith("url("):
            return self._gradient(value, alpha, bounds, matrix)
        color = _colour(value)
        if color is None:
            raise _Unsupported("fill")
        return SolidFill(color=_with_alpha(color, alpha))

    def _stroke(self, element: Element, opacity: float, matrix: Affine) -> Line | None:
        value = (_attr(element, "stroke") or "none").strip()
        width = _number(_attr(element, "stroke-width"), 1.0)
        if value in ("none", "transparent") or width <= 0:
            return None
        scale = matrix.scale()
        if scale < 0:
            raise _Unsupported("stroke under uneven scale")
        if value.startswith("url("):
            raise _Unsupported("gradient stroke")
        color = _colour(value)
        if color is None:
            raise _Unsupported("stroke")
        width_px = width * scale
        dashes = [float(n) for n in _NUMBER.findall(_attr(element, "stroke-dasharray") or "")]
        if dashes and _number(_attr(element, "stroke-dashoffset"), 0.0) != 0.0:
            raise _Unsupported("dash offset")
        pattern = (
            tuple(length / width for length in dashes)
            if dashes and any(length > 0 for length in dashes)
            else ()
        )
        return Line(
            color=_with_alpha(color, _number(_attr(element, "stroke-opacity"), 1.0) * opacity),
            width_emu=max(1, px_to_emu(width_px)),
            custom_dash=pattern,
            cap=_CAPS.get(_attr(element, "stroke-linecap") or "butt", "flat"),  # type: ignore[arg-type]
            join=_JOINS.get(_attr(element, "stroke-linejoin") or "miter", "miter"),  # type: ignore[arg-type]
        )

    def _gradient(
        self,
        reference: str,
        alpha: float,
        bounds: tuple[float, float, float, float],
        matrix: Affine,
    ) -> GradientFill:
        found = re.search(r"#([^)\"'\s]+)", reference)
        gradient = self.gradients.get(found.group(1)) if found else None
        if (
            gradient is None
            or gradient.get("gradientTransform")
            or gradient.get("spreadMethod") not in (None, "pad")
        ):
            raise _Unsupported("gradient")
        stops = self._stops(gradient, alpha)
        if _local(gradient) == "radialgradient":
            plain = all(
                gradient.get(k, v) in (v, v.replace("%", ""))
                for k, v in (("cx", "50%"), ("cy", "50%"))
            )
            if (
                gradient.get("gradientUnits") == "userSpaceOnUse"
                or not plain
                or gradient.get("fx")
                or gradient.get("fy")
            ):
                raise _Unsupported("radial gradient")
            return GradientFill(stops=stops, radial=True)
        units = gradient.get("gradientUnits", "objectBoundingBox")
        x1, y1 = _unit(gradient.get("x1", "0%")), _unit(gradient.get("y1", "0%"))
        x2, y2 = _unit(gradient.get("x2", "100%")), _unit(gradient.get("y2", "0%"))
        left, top, right, bottom = bounds
        if units == "objectBoundingBox":
            # The axis is laid out on the element's own box and then carried by its transform.
            start = matrix.apply((left + x1 * (right - left), top + y1 * (bottom - top)))
            end = matrix.apply((left + x2 * (right - left), top + y2 * (bottom - top)))
        else:
            start, end = matrix.apply((x1, y1)), matrix.apply((x2, y2))
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            raise _Unsupported("degenerate gradient")
        # The shape's own extent along the gradient axis fixes where its first and last colour fall.
        corners = [matrix.apply((x, y)) for x in (left, right) for y in (top, bottom)]
        along = [
            ((x - start[0]) * dx + (y - start[1]) * dy) / (length * length) for x, y in corners
        ]
        low, high = min(along), max(along)
        if high - low <= 1e-9:
            raise _Unsupported("degenerate gradient")
        remapped = tuple(
            GradientStop(pos=min(1.0, max(0.0, (s.pos - low) / (high - low))), color=s.color)
            for s in stops
        )
        angle = math.degrees(math.atan2(dx, -dy)) % 360.0
        return GradientFill(stops=remapped, angle_deg=angle)

    def _stops(self, gradient: Element, alpha: float) -> tuple[GradientStop, ...]:
        source = gradient
        chain = 0
        while not list(source.iter(f"{{{_SVG}}}stop")) and chain < 8:
            href = source.get(f"{{{_XLINK}}}href") or source.get("href") or ""
            nxt = self.gradients.get(href.lstrip("#"))
            if nxt is None:
                break
            source, chain = nxt, chain + 1
        stops: list[GradientStop] = []
        last = 0.0
        for stop in source.iter(f"{{{_SVG}}}stop"):
            offset = max(last, min(1.0, _unit(stop.get("offset", "0"))))
            colour = _colour(_attr(stop, "stop-color") or "black")
            if colour is None:
                raise _Unsupported("stop")
            weight = _number(_attr(stop, "stop-opacity"), 1.0) * alpha
            stops.append(GradientStop(pos=offset, color=_with_alpha(colour, weight)))
            last = offset
        if len(stops) < 2:
            raise _Unsupported("gradient stops")
        return tuple(stops)


# --------------------------------------------------------------------------- geometry


def _length(value: str | None, default: float) -> float:
    """A geometry length in user units; percentages and font-relative units have no fixed value."""
    text = (value or "").strip()
    if text.endswith(("%", "em", "ex", "rem")):
        raise _Unsupported("relative length")
    return _number(text, default)


def _segments(element: Element, name: str) -> list[Segment]:
    """The element's outline in user units as ``M``/``L``/``C``/``Z`` segments."""
    if name == "path":
        return _path_segments(element.get("d", ""))
    if name == "rect":
        x, y = _length(element.get("x"), 0.0), _length(element.get("y"), 0.0)
        w, h = _length(element.get("width"), 0.0), _length(element.get("height"), 0.0)
        if w <= 0 or h <= 0:
            return []
        rx, ry = element.get("rx"), element.get("ry")
        radius_x = _length(rx, _length(ry, 0.0))
        radius_y = _length(ry, _length(rx, 0.0))
        radius_x, radius_y = min(radius_x, w / 2), min(radius_y, h / 2)
        if radius_x <= 0 or radius_y <= 0:
            return [
                ("M", [(x, y)]),
                ("L", [(x + w, y)]),
                ("L", [(x + w, y + h)]),
                ("L", [(x, y + h)]),
                ("Z", []),
            ]
        return _rounded(x, y, w, h, radius_x, radius_y)
    if name in ("circle", "ellipse"):
        cx, cy = _length(element.get("cx"), 0.0), _length(element.get("cy"), 0.0)
        rx = _length(element.get("r" if name == "circle" else "rx"), 0.0)
        ry = rx if name == "circle" else _length(element.get("ry"), 0.0)
        return _ellipse(cx, cy, rx, ry) if rx > 0 and ry > 0 else []
    if name == "line":
        a = (_length(element.get("x1"), 0.0), _length(element.get("y1"), 0.0))
        b = (_length(element.get("x2"), 0.0), _length(element.get("y2"), 0.0))
        return [("M", [a]), ("L", [b])]
    points = [float(n) for n in _NUMBER.findall(element.get("points", ""))]
    pairs = list(zip(points[0::2], points[1::2], strict=False))
    if len(pairs) < 2:
        return []
    out: list[Segment] = [("M", [pairs[0]]), *(("L", [p]) for p in pairs[1:])]
    return [*out, ("Z", [])] if name == "polygon" else out


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> list[Segment]:
    k = _KAPPA
    return [
        ("M", [(cx + rx, cy)]),
        ("C", [(cx + rx, cy + ry * k), (cx + rx * k, cy + ry), (cx, cy + ry)]),
        ("C", [(cx - rx * k, cy + ry), (cx - rx, cy + ry * k), (cx - rx, cy)]),
        ("C", [(cx - rx, cy - ry * k), (cx - rx * k, cy - ry), (cx, cy - ry)]),
        ("C", [(cx + rx * k, cy - ry), (cx + rx, cy - ry * k), (cx + rx, cy)]),
        ("Z", []),
    ]


def _rounded(x: float, y: float, w: float, h: float, rx: float, ry: float) -> list[Segment]:
    k = _KAPPA
    return [
        ("M", [(x + rx, y)]),
        ("L", [(x + w - rx, y)]),
        ("C", [(x + w - rx + rx * k, y), (x + w, y + ry - ry * k), (x + w, y + ry)]),
        ("L", [(x + w, y + h - ry)]),
        ("C", [(x + w, y + h - ry + ry * k), (x + w - rx + rx * k, y + h), (x + w - rx, y + h)]),
        ("L", [(x + rx, y + h)]),
        ("C", [(x + rx - rx * k, y + h), (x, y + h - ry + ry * k), (x, y + h - ry)]),
        ("L", [(x, y + ry)]),
        ("C", [(x, y + ry - ry * k), (x + rx - rx * k, y), (x + rx, y)]),
        ("Z", []),
    ]


def _path_segments(data: str) -> list[Segment]:
    """An SVG ``d`` string as absolute ``M``/``L``/``C``/``Z`` segments; arcs become cubics."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", data)
    out: list[Segment] = []
    i = 0
    command = ""
    current = start = (0.0, 0.0)
    last_control: Pair | None = None
    last_kind = ""

    def number() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in "Zz":
                out.append(("Z", []))
                current = start
                last_kind = "Z"
                continue
        if not command:
            raise _Unsupported("path")
        relative = command.islower()
        kind = command.upper()
        ox, oy = current if relative else (0.0, 0.0)
        if kind == "M":
            current = (number() + ox, number() + oy)
            start = current
            out.append(("M", [current]))
            command = "l" if relative else "L"
        elif kind == "L":
            current = (number() + ox, number() + oy)
            out.append(("L", [current]))
        elif kind == "H":
            current = (number() + ox, current[1])
            out.append(("L", [current]))
        elif kind == "V":
            current = (current[0], number() + oy)
            out.append(("L", [current]))
        elif kind == "C":
            c1 = (number() + ox, number() + oy)
            c2 = (number() + ox, number() + oy)
            end = (number() + ox, number() + oy)
            out.append(("C", [c1, c2, end]))
            last_control, current = c2, end
        elif kind == "S":
            c1 = (
                (2 * current[0] - last_control[0], 2 * current[1] - last_control[1])
                if last_control is not None and last_kind in ("C", "S")
                else current
            )
            c2 = (number() + ox, number() + oy)
            end = (number() + ox, number() + oy)
            out.append(("C", [c1, c2, end]))
            last_control, current = c2, end
        elif kind in ("Q", "T"):
            if kind == "Q":
                control = (number() + ox, number() + oy)
            else:
                control = (
                    (2 * current[0] - last_control[0], 2 * current[1] - last_control[1])
                    if last_control is not None and last_kind in ("Q", "T")
                    else current
                )
            end = (number() + ox, number() + oy)
            out.append(("C", _quad_to_cubic(current, control, end)))
            last_control, current = control, end
        elif kind == "A":
            rx, ry, rotation = number(), number(), number()
            large, sweep = number() != 0, number() != 0
            end = (number() + ox, number() + oy)
            out.extend(_arc(current, rx, ry, rotation, large, sweep, end))
            current = end
        else:
            raise _Unsupported(command)
        last_kind = kind
        if kind not in ("C", "S", "Q", "T"):
            last_control = None
    return out


def _quad_to_cubic(p0: Pair, control: Pair, p1: Pair) -> list[Pair]:
    return [
        (p0[0] + 2 / 3 * (control[0] - p0[0]), p0[1] + 2 / 3 * (control[1] - p0[1])),
        (p1[0] + 2 / 3 * (control[0] - p1[0]), p1[1] + 2 / 3 * (control[1] - p1[1])),
        p1,
    ]


def _arc(
    p0: Pair, rx: float, ry: float, rotation: float, large: bool, sweep: bool, p1: Pair
) -> list[Segment]:
    """An SVG elliptical arc as cubic segments (the endpoint-to-centre conversion of the spec)."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [("L", [p1])]
    phi = math.radians(rotation % 360)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, numerator / denominator)) * (-1 if large == sweep else 1)
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2
    cy = sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        value = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return value

    theta = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    pieces = max(1, math.ceil(abs(delta) / (math.pi / 2) - 1e-9))
    step = delta / pieces
    k = 4 / 3 * math.tan(step / 4)
    segments: list[Segment] = []

    def at(t: float) -> Pair:
        return (
            cx + rx * math.cos(t) * cp - ry * math.sin(t) * sp,
            cy + rx * math.cos(t) * sp + ry * math.sin(t) * cp,
        )

    def derivative(t: float) -> Pair:
        return (
            -rx * math.sin(t) * cp - ry * math.cos(t) * sp,
            -rx * math.sin(t) * sp + ry * math.cos(t) * cp,
        )

    for piece in range(pieces):
        t0, t1 = theta + piece * step, theta + (piece + 1) * step
        a, b, da, db = at(t0), at(t1), derivative(t0), derivative(t1)
        segments.append(
            ("C", [(a[0] + k * da[0], a[1] + k * da[1]), (b[0] - k * db[0], b[1] - k * db[1]), b])
        )
    return segments


# --------------------------------------------------------------------------- helpers


def _shadow(marker: str) -> Shadow:
    """The shadow a canvas recording attached to a group: ``dx dy blur colour alpha``."""
    parts = marker.split()
    dx, dy, blur, alpha = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[4])
    colour = _colour(parts[3])
    if colour is None:
        raise _Unsupported("shadow colour")
    return Shadow(
        color=_with_alpha(colour, alpha),
        blur_emu=px_to_emu(blur),
        distance_emu=px_to_emu(math.hypot(dx, dy)),
        direction_deg=math.degrees(math.atan2(dy, dx)) % 360.0,
    )


def _colour(text: str | None) -> Rgba | None:
    """A CSS colour, including the ``#rgb`` and ``#rrggbb`` forms SVG and canvas use."""
    value = (text or "").strip()
    match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if match is None:
        return parse_color(value)
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return Rgba(r=int(digits[0:2], 16), g=int(digits[2:4], 16), b=int(digits[4:6], 16))


def _local(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _attr(element: Element, name: str) -> str | None:
    """A presentation attribute, from the attribute or an inline ``style`` declaration."""
    for declaration in (element.get("style") or "").split(";"):
        key, _, value = declaration.partition(":")
        if key.strip() == name and value.strip():
            return value.strip()
    return element.get(name)


def _hidden(element: Element) -> bool:
    return _attr(element, "display") == "none" or _attr(element, "visibility") in (
        "hidden",
        "collapse",
    )


def _number(value: str | None, default: float) -> float:
    match = _NUMBER.match((value or "").strip())
    return float(match.group(0)) if match else default


def _unit(value: str) -> float:
    """A gradient coordinate or offset: a fraction, or a percentage turned into one."""
    text = value.strip()
    number = _number(text, 0.0)
    return number / 100.0 if text.endswith("%") else number


def _with_alpha(color: Rgba, alpha: float) -> Rgba:
    return color.model_copy(update={"a": min(1.0, max(0.0, color.a * alpha))})
