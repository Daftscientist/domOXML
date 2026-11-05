"""Draw a DrawingML chart part as a vector SVG, so a PPTX chart reaches HTML without pixels.

The chart part (``c:chartSpace``) is a semantic description: chart types, series, categories,
values, colours and axes. This reads the common subset (bar and column, line, area, pie,
doughnut, scatter, bubble, radar and stock, with clustered, stacked and percent grouping) and
lays it out itself. It is an approximation of PowerPoint's own layout, never a copy of its
pixels, and says so by returning ``None`` for anything it does not model (surface and extended
charts), which then stay a preserved source object.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from defusedxml import DefusedXmlException, ElementTree

from domoxml.core.colour_transform import apply_color_transforms

_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"c": _C, "a": _A}

# Office's default accent cycle, used when a series has no colour of its own.
_ACCENTS = ("4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47")
_DEFAULT_SCHEME = {
    "accent1": "4472C4",
    "accent2": "ED7D31",
    "accent3": "A5A5A5",
    "accent4": "FFC000",
    "accent5": "5B9BD5",
    "accent6": "70AD47",
    "tx1": "000000",
    "tx2": "44546A",
    "bg1": "FFFFFF",
    "bg2": "E7E6E6",
    "dk1": "000000",
    "dk2": "44546A",
    "lt1": "FFFFFF",
    "lt2": "E7E6E6",
}
_FONT = "Calibri, 'Segoe UI', Arial, sans-serif"
_TEXT = "#595959"
_GRID = "#D9D9D9"
_SUPPORTED = {
    "barChart": "bar",
    "bar3DChart": "bar",
    "lineChart": "line",
    "line3DChart": "line",
    "areaChart": "area",
    "area3DChart": "area",
    "pieChart": "pie",
    "pie3DChart": "pie",
    "doughnutChart": "doughnut",
    "scatterChart": "scatter",
    "radarChart": "radar",
    "bubbleChart": "bubble",
    "stockChart": "stock",
}


@dataclass
class Series:
    name: str
    categories: list[str]
    values: list[float | None]
    color: str
    xs: list[float] | None = None
    sizes: list[float | None] | None = None
    line: bool = True
    marker: bool = False
    show_values: bool = False
    label_pos: str = ""
    explicit_color: bool = False  # the series names its own fill, which every slice then takes
    gradient: tuple[tuple[float, str, float], ...] = ()  # (position, colour, opacity) stops
    gradient_angle: float = 0.0  # degrees clockwise from left-to-right
    alpha: float | None = None  # the solid fill's opacity, when it names one
    label_color: str = ""
    label_bold: bool = False
    label_px: float = 10.0
    format_code: str = "General"
    point_colors: dict[int, str] = field(default_factory=dict[int, str])
    smooth: bool = False  # a scatter or line series drawn as a curve
    line_px: float = 1.5  # measured against PowerPoint: an unstyled line is about 1 pt
    dash: str = ""  # an ``a:prstDash`` name
    marker_symbol: str = ""  # empty: the automatic symbol for the series' position
    marker_px: float = 6.7  # the automatic marker is 5 pt
    marker_color: str = ""
    position: int = 0  # the series' index among the chart's, for automatic markers


@dataclass
class Group:
    kind: str
    grouping: str
    horizontal: bool
    series: list[Series]
    gap_width: int = 150
    overlap: int = 0
    filled: bool = False
    hole: float = 0.5
    vary_colors: bool = True
    first_angle: int = 0
    bubble_scale: float = 1.0


def chart_to_svg(
    chart_xml: bytes, *, width_px: float, height_px: float, theme: Mapping[str, str] | None = None
) -> str | None:
    """The chart as a standalone SVG of the given size, or ``None`` if it is not modelled."""
    try:
        root = ElementTree.fromstring(chart_xml)
    except (ElementTree.ParseError, DefusedXmlException):
        return None
    chart = root.find("c:chart", _NS)
    plot = chart.find("c:plotArea", _NS) if chart is not None else None
    if chart is None or plot is None or width_px < 40 or height_px < 40:
        return None
    palette = {**_DEFAULT_SCHEME, **{k: v for k, v in (theme or {}).items() if _hex(v)}}
    # A chart names colours by role (tx2, bg1) that the colour map points at the theme's dark and
    # light slots, so a deck that gives only dk2 or lt1 still resolves them.
    for role, slot in (("tx1", "dk1"), ("tx2", "dk2"), ("bg1", "lt1"), ("bg2", "lt2")):
        if theme and _hex(theme.get(slot)) and not _hex(theme.get(role)):
            palette[role] = theme[slot]
    groups: list[Group] = []
    index = 0
    for element in plot:
        local = element.tag.rsplit("}", 1)[-1]
        if local.endswith("Chart") and local not in _SUPPORTED:
            return None
        if local in _SUPPORTED:
            group = _group(element, _SUPPORTED[local], palette, index)
            if group is None:
                return None
            groups.append(group)
            index += len(group.series)
    if not groups or not any(group.series for group in groups):
        return None
    kinds = {group.kind for group in groups}
    if kinds & {"pie", "doughnut", "radar", "scatter", "bubble", "stock"} and len(groups) > 1:
        return None
    title_node = chart.find("c:title", _NS)
    title = _title(title_node)
    if (
        title_node is not None
        and not title
        and _val(chart.find("c:autoTitleDeleted", _NS), "0") != "1"
    ):
        title = "Chart Title"  # a title element with no text is PowerPoint's placeholder title
    everything = [series for group in groups for series in group.series]
    if (
        chart.find("c:title", _NS) is None
        and _val(chart.find("c:autoTitleDeleted", _NS), "0") != "1"
        and len(everything) == 1
        and groups[0].kind in ("pie", "doughnut")
    ):
        title = everything[0].name  # PowerPoint titles a lone series after itself
    legend = chart.find("c:legend", _NS)
    legend_pos = None
    if legend is not None:
        legend_pos = _val(legend.find("c:legendPos", _NS), "r")
    canvas = _Canvas(width_px, height_px)
    canvas.accents = [_accent(palette, i) for i in range(6)]
    canvas.title = title
    canvas.title_layout = _manual_layout(title_node)
    canvas.title_color = _text_colour(title_node, palette)
    canvas.title_bold = _is_bold(title_node)
    canvas.legend_color = _text_colour(legend, palette) or "000000"
    canvas.background = _fill_hex(root.find("c:spPr", _NS), palette)
    canvas.background_alpha = _fill_alpha(root.find("c:spPr", _NS))
    canvas.rounded = _val(root.find("c:roundedCorners", _NS), "0") in ("1", "true")
    canvas.title_px = _font_px(title_node, 16.0 * 96 / 72 if title_node is not None else 16.0)
    canvas.legend_pos = legend_pos
    canvas.legend_layout = _manual_layout(legend)
    canvas.legend_px = _font_px(legend, 12.0)
    canvas.plot_layout = (
        _manual_layout(plot)
        if _val(plot.find("c:layout/c:manualLayout/c:layoutTarget", _NS), "inner") == "inner"
        else None
    )
    canvas.categories_reversed = (
        _val(plot.find("c:catAx/c:scaling/c:orientation", _NS), "minMax") == "maxMin"
    )
    canvas.grid = _has_gridlines(plot)
    if groups[0].kind in ("scatter", "bubble"):
        x_axis, y_axis = _scatter_axes(plot)
        canvas.grid, canvas.grid_x = _axis_gridlines(y_axis), _axis_gridlines(x_axis)
    grid_node = plot.find("c:valAx/c:majorGridlines/c:spPr", _NS)
    canvas.grid_color, line_width = _line_style(grid_node, palette)
    # Gridlines with no style of their own are PowerPoint's automatic ones: black hairlines.
    canvas.grid_color = canvas.grid_color or "000000"
    canvas.grid_px = line_width or 1.0
    axis_node = plot.find("c:valAx", _NS)
    axis_node = axis_node if axis_node is not None else plot.find("c:catAx", _NS)
    # The axis's own text properties, not those of an axis title nested in it.
    tick_text = axis_node.find("c:txPr", _NS) if axis_node is not None else None
    canvas.tick_px = _font_px(tick_text, 11.0)
    # Text with no properties of its own is black (the automatic colour), not the modern grey.
    canvas.tick_color = _text_colour(tick_text, palette) or "000000"
    category_node = plot.find("c:catAx", _NS)
    category_text = category_node.find("c:txPr", _NS) if category_node is not None else None
    canvas.category_px = _font_px(category_text, 11.0)
    canvas.category_color = _text_colour(category_text, palette) or "000000"
    canvas.axis_titles = _axis_titles(plot)
    first = groups[0]
    if first.kind in ("pie", "doughnut"):
        return canvas.pie(first)
    if first.kind == "radar":
        return canvas.radar(first)
    if first.kind in ("scatter", "bubble"):
        return canvas.scatter(first, _axis_format(plot))
    return canvas.cartesian(groups, _axis_format(plot), _value_axis_deleted(plot))


# --------------------------------------------------------------------------- parsing


def _group(element: Element, kind: str, palette: Mapping[str, str], start: int) -> Group | None:
    grouping = _val(element.find("c:grouping", _NS), "clustered")
    direction = _val(element.find("c:barDir", _NS), "col")
    scatter_style = _val(element.find("c:scatterStyle", _NS), "lineMarker")
    radar_style = _val(element.find("c:radarStyle", _NS), "standard")
    # A series with no ``c:smooth`` takes the chart's, then the schema default (smoothed).
    chart_smooth = _boolean(element.find("c:smooth", _NS), True)
    series: list[Series] = []
    for offset, ser in enumerate(element.findall("c:ser", _NS)):
        color = _series_color(ser, palette) or _accent(palette, start + offset)
        categories = _strings(ser.find("c:cat", _NS))
        sizes = _numbers(ser.find("c:bubbleSize", _NS)) if kind == "bubble" else None
        if kind in ("scatter", "bubble"):
            xs_raw = _numbers(ser.find("c:xVal", _NS))
            values = _numbers(ser.find("c:yVal", _NS))
            xs = [x if x is not None else float(i + 1) for i, x in enumerate(xs_raw)]
        else:
            values = _numbers(ser.find("c:val", _NS))
            xs = None
        if not categories:
            categories = [str(i + 1) for i in range(len(values))]
        spec = ser.find("c:spPr", _NS)
        line_off = spec is not None and spec.find("a:ln/a:noFill", _NS) is not None
        marker = ser.find("c:marker", _NS)
        marker_symbol = _val(marker.find("c:symbol", _NS), "") if marker is not None else ""
        labels = ser.find("c:dLbls", _NS)
        show = labels is not None and _val(labels.find("c:showVal", _NS), "0") == "1"
        fmt = ser.find("c:val/c:numRef/c:numCache/c:formatCode", _NS)
        series.append(
            Series(
                name=_series_name(ser) or f"Series {start + offset + 1}",
                categories=categories,
                values=values,
                xs=xs,
                sizes=sizes,
                color=color,
                explicit_color=ser.find("c:spPr/a:solidFill", _NS) is not None
                and _series_color(ser, palette) is not None,
                gradient=_gradient_stops(ser.find("c:spPr", _NS), palette),
                gradient_angle=_gradient_angle(ser.find("c:spPr", _NS)),
                alpha=_solid_alpha(ser.find("c:spPr", _NS)),
                # A scatter series with no ``c:smooth`` is smoothed (the schema default is true).
                smooth=kind in ("scatter", "line")
                and _boolean(ser.find("c:smooth", _NS), chart_smooth),
                line=not line_off and (kind != "scatter" or scatter_style != "marker"),
                marker=marker_symbol != "none"
                and (kind in ("scatter", "line") or marker_symbol != ""),
                line_px=_line_style(ser.find("c:spPr", _NS), palette)[1] or 1.5,
                dash=_val(ser.find("c:spPr/a:ln/a:prstDash", _NS), ""),
                marker_symbol=marker_symbol,
                marker_px=_marker_px(marker),
                marker_color=_fill_hex(marker.find("c:spPr", _NS), palette)
                if marker is not None
                else "",
                position=start + offset,
                show_values=show,
                label_pos=_val(labels.find("c:dLblPos", _NS), "") if labels is not None else "",
                label_color=_label_style(labels, palette)[0],
                label_bold=_label_style(labels, palette)[1],
                label_px=_font_px(labels.find("c:txPr", _NS) if labels is not None else None, 10.0),
                format_code=(fmt.text or "General") if fmt is not None else "General",
                point_colors={
                    int(_val(pt.find("c:idx", _NS), "0")): c
                    for pt in ser.findall("c:dPt", _NS)
                    if (c := _series_color(pt, palette)) is not None
                },
            )
        )
    hole = int(_val(element.find("c:holeSize", _NS), "50")) / 100
    return Group(
        kind=kind,
        grouping=grouping,
        horizontal=direction == "bar",
        series=series,
        gap_width=int(_val(element.find("c:gapWidth", _NS), "150")),
        overlap=int(_val(element.find("c:overlap", _NS), "0")),
        filled=radar_style == "filled",
        hole=min(0.9, max(0.1, hole)),
        vary_colors=_val(element.find("c:varyColors", _NS), "1") not in ("0", "false"),
        first_angle=int(_val(element.find("c:firstSliceAng", _NS), "0")) % 360,
        bubble_scale=int(_val(element.find("c:bubbleScale", _NS), "100")) / 100,
    )


_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")


def _hex(value: str | None) -> str | None:
    """``value`` if it is a six-digit hex colour, else ``None``: it goes into SVG attributes."""
    return value if value is not None and _HEX.match(value) else None


def _accent(palette: Mapping[str, str], index: int) -> str:
    """The deck theme's ``accent1``..``accent6`` cycle, as PowerPoint colours unstyled series."""
    return _hex(palette.get(f"accent{index % 6 + 1}")) or _ACCENTS[index % len(_ACCENTS)]


def _val(element: Element | None, default: str) -> str:
    return element.get("val", default) if element is not None else default


def _boolean(element: Element | None, default: bool) -> bool:
    """A ``CT_Boolean`` element: ``default`` when absent, and true when present without a value."""
    if element is None:
        return default
    return element.get("val", "1") not in ("0", "false")


def _series_name(ser: Element) -> str:
    tx = ser.find("c:tx", _NS)
    if tx is None:
        return ""
    cached = tx.find(".//c:v", _NS)
    return (cached.text or "") if cached is not None else ""


def _strings(node: Element | None) -> list[str]:
    if node is None:
        return []
    points = _points(node)
    count = max(points, default=-1) + 1
    return [points.get(i, "") for i in range(count)]


def _numbers(node: Element | None) -> list[float | None]:
    if node is None:
        return []
    points = _points(node)
    count = max(points, default=-1) + 1
    out: list[float | None] = []
    for i in range(count):
        try:
            value = float(points[i]) if i in points else None
        except ValueError:
            value = None
        out.append(value if value is None or math.isfinite(value) else None)
    return out


def _points(node: Element) -> dict[int, str]:
    points: dict[int, str] = {}
    for pt in node.iter(f"{{{_C}}}pt"):
        value = pt.find("c:v", _NS)
        if value is not None and value.text is not None:
            points[int(pt.get("idx", "0"))] = value.text
    return points


def _transformed(base: str, element: Element) -> str:
    """``base`` (six hex digits) with the colour's own ``lumMod``/``lumOff``/``tint`` applied."""
    red, green, blue, _alpha = apply_color_transforms(
        int(base[0:2], 16), int(base[2:4], 16), int(base[4:6], 16), 1.0, element
    )
    return f"{red:02X}{green:02X}{blue:02X}"


def _text_colour(node: Element | None, palette: Mapping[str, str]) -> str:
    """The colour of the first run properties under ``node`` (a title, a legend), or ``""``."""
    if node is None:
        return ""
    for tag in ("defRPr", "rPr"):
        for properties in node.iter(f"{{{_A}}}{tag}"):
            fill = properties.find("a:solidFill", _NS)
            if fill is not None:
                return _fill_hex(properties, palette)
    return ""


def _gradient_stops(
    properties: Element | None, palette: Mapping[str, str]
) -> tuple[tuple[float, str, float], ...]:
    """The ``a:gradFill`` stops of ``properties`` as ``(position, colour, opacity)``."""
    stops = properties.findall("a:gradFill/a:gsLst/a:gs", _NS) if properties is not None else []
    found: list[tuple[float, str, float]] = []
    for stop in stops:
        colour = _fill_hex_of(stop, palette)
        if not colour:
            return ()
        alpha = stop.find("*/a:alpha", _NS)
        try:
            opacity = int(alpha.get("val", "100000")) / 100_000 if alpha is not None else 1.0
            position = int(stop.get("pos", "0")) / 100_000
        except ValueError:
            return ()
        found.append((position, colour, max(0.0, min(1.0, opacity))))
    return tuple(found) if len(found) >= 2 else ()


def _gradient_angle(properties: Element | None) -> float:
    linear = properties.find("a:gradFill/a:lin", _NS) if properties is not None else None
    try:
        return int(linear.get("ang", "0")) / 60_000 if linear is not None else 0.0
    except ValueError:
        return 0.0


def _solid_alpha(properties: Element | None) -> float | None:
    """The opacity of a solid fill that names one, else ``None``."""
    alpha = properties.find("a:solidFill/*/a:alpha", _NS) if properties is not None else None
    try:
        return int(alpha.get("val", "100000")) / 100_000 if alpha is not None else None
    except ValueError:
        return None


def _fill_hex_of(holder: Element, palette: Mapping[str, str]) -> str:
    """The colour of the first ``srgbClr``/``schemeClr`` child of ``holder``, or ``""``."""
    rgb = holder.find("a:srgbClr", _NS)
    scheme = holder.find("a:schemeClr", _NS)
    if rgb is not None and _hex(rgb.get("val")):
        return _transformed(rgb.get("val", ""), rgb)
    if scheme is not None and _hex(palette.get(scheme.get("val", ""))):
        return _transformed(palette[scheme.get("val", "")], scheme)
    return ""


def _marker_px(marker: Element | None) -> float:
    """The marker's size in px (``c:size`` is in points, 2 to 72), 5 pt when it names none."""
    try:
        return int(_val(marker.find("c:size", _NS), "5") if marker is not None else "5") * 96 / 72
    except ValueError:
        return 5 * 96 / 72


_AUTO_MARKERS = ("diamond", "square", "triangle", "x", "star", "circle", "plus")
_DASHES = {
    "sysDash": (3, 1),
    "sysDot": (1, 1),
    "dash": (4, 3),
    "lgDash": (8, 3),
    "dashDot": (4, 3, 1, 3),
    "lgDashDot": (8, 3, 1, 3),
    "sysDashDot": (3, 1, 1, 1),
    "sysDashDotDot": (3, 1, 1, 1, 1, 1),
    "lgDashDotDot": (8, 3, 1, 3, 1, 3),
}


def _dash_attr(name: str, width: float) -> str:
    """An SVG ``stroke-dasharray`` for an ``a:prstDash`` name (lengths in line widths)."""
    lengths = _DASHES.get(name)
    if lengths is None:
        return ""
    return f' stroke-dasharray="{" ".join(f"{n * width:.1f}" for n in lengths)}"'


def _marker_svg(symbol: str, x: float, y: float, size: float, colour: str) -> str:
    """One chart marker of ``size`` px centred on ``(x, y)`` (PowerPoint's symbol names)."""
    r = size / 2
    fill = f'fill="#{colour}"'
    stroke = f'stroke="#{colour}" stroke-width="1.5" fill="none"'
    if symbol == "square":
        return (
            f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{size:.1f}" height="{size:.1f}" {fill}/>'
        )
    if symbol == "diamond":
        t = r * 1.2
        pts = f"{x:.1f},{y - t:.1f} {x + t:.1f},{y:.1f} {x:.1f},{y + t:.1f} {x - t:.1f},{y:.1f}"
        return f'<polygon points="{pts}" {fill}/>'
    if symbol == "triangle":
        pts = f"{x:.1f},{y - r:.1f} {x + r:.1f},{y + r:.1f} {x - r:.1f},{y + r:.1f}"
        return f'<polygon points="{pts}" {fill}/>'
    if symbol in ("x", "plus", "star"):
        lines: list[tuple[float, float, float, float]] = []
        if symbol in ("x", "star"):
            lines += [(x - r, y - r, x + r, y + r), (x - r, y + r, x + r, y - r)]
        if symbol in ("plus", "star"):
            lines += [(x - r, y, x + r, y), (x, y - r, x, y + r)]
        body = "".join(
            f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}"/>' for a, b, c, d in lines
        )
        return f"<g {stroke}>{body}</g>"
    if symbol == "dash":
        box = f'x="{x - r:.1f}" y="{y - r / 3:.1f}" width="{size:.1f}" height="{size / 1.5:.1f}"'
        return f"<rect {box} {fill}/>"
    if symbol == "dot":
        r /= 2
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" {fill}/>'


def _line_style(properties: Element | None, palette: Mapping[str, str]) -> tuple[str, float]:
    """The ``(colour, width in px)`` of an ``a:ln`` solid line in ``properties``."""
    line = properties.find("a:ln", _NS) if properties is not None else None
    if line is None:
        return "", 0.0
    fill = line.find("a:solidFill", _NS)
    colour = _fill_hex_of(fill, palette) if fill is not None else ""
    try:
        width = int(line.get("w", "")) / 9525
    except ValueError:
        width = 0.0
    return colour, width


def _fill_alpha(properties: Element | None) -> float:
    """The opacity of the solid fill in ``properties`` (``a:alpha``), 1 when it has none."""
    alpha = properties.find("a:solidFill/*/a:alpha", _NS) if properties is not None else None
    try:
        return (
            max(0.0, min(1.0, int(alpha.get("val", "100000")) / 100_000))
            if alpha is not None
            else 1.0
        )
    except ValueError:
        return 1.0


def _is_bold(node: Element | None) -> bool:
    if node is None:
        return False
    return any(
        properties.get("b") == "1"
        for tag in ("defRPr", "rPr")
        for properties in node.iter(f"{{{_A}}}{tag}")
    )


def _fill_hex(properties: Element | None, palette: Mapping[str, str]) -> str:
    """The solid colour of ``properties`` (an ``spPr`` or run properties), or ``""``."""
    fill = properties.find("a:solidFill", _NS) if properties is not None else None
    if fill is None:
        return ""
    rgb = fill.find("a:srgbClr", _NS)
    scheme = fill.find("a:schemeClr", _NS)
    if rgb is not None and _hex(rgb.get("val")):
        return _transformed(rgb.get("val", ""), rgb)
    if scheme is not None and _hex(palette.get(scheme.get("val", ""))):
        return _transformed(palette[scheme.get("val", "")], scheme)
    return ""


def _label_style(labels: Element | None, palette: Mapping[str, str]) -> tuple[str, bool]:
    """The ``(colour, bold)`` of a series' data labels, from their own ``txPr``."""
    properties = labels.find("c:txPr//a:defRPr", _NS) if labels is not None else None
    if properties is None:
        return "", False
    colour = ""
    fill = properties.find("a:solidFill", _NS)
    if fill is not None:
        rgb = fill.find("a:srgbClr", _NS)
        scheme = fill.find("a:schemeClr", _NS)
        if rgb is not None and _hex(rgb.get("val")):
            colour = _transformed(rgb.get("val", ""), rgb)
        elif scheme is not None and _hex(palette.get(scheme.get("val", ""))):
            colour = _transformed(palette[scheme.get("val", "")], scheme)
    return colour, properties.get("b") == "1"


def _series_color(ser: Element, palette: Mapping[str, str]) -> str | None:
    spec = ser.find("c:spPr", _NS)
    if spec is None:
        return None
    for path in ("a:solidFill", "a:ln/a:solidFill"):
        fill = spec.find(path, _NS)
        if fill is None:
            continue
        rgb = fill.find("a:srgbClr", _NS)
        if rgb is not None and _hex(rgb.get("val")):
            return _transformed(rgb.get("val", ""), rgb)
        scheme = fill.find("a:schemeClr", _NS)
        if scheme is not None and scheme.get("val") in palette:
            base = _hex(palette[scheme.get("val", "")])
            return _transformed(base, scheme) if base else None
    return None


def _manual_layout(node: Element | None) -> tuple[float, float, float, float] | None:
    """``(x, y, w, h)`` as fractions of the chart for an edge-mode ``c:manualLayout``, else None."""
    layout = node.find("c:layout/c:manualLayout", _NS) if node is not None else None
    if layout is None:
        return None

    def fraction(tag: str) -> float | None:
        try:
            return float(_val(layout.find(f"c:{tag}", _NS), ""))
        except ValueError:
            return None

    x, y = fraction("x"), fraction("y")
    if x is None or y is None:
        return None
    if _val(layout.find("c:xMode", _NS), "factor") != "edge":
        return None
    if _val(layout.find("c:yMode", _NS), "factor") != "edge":
        return None
    return x, y, fraction("w") or 0.0, fraction("h") or 0.0


def _font_px(node: Element | None, default: float) -> float:
    """The font size, in CSS pixels, of the first run properties under ``node``."""
    if node is not None:
        for tag in ("defRPr", "rPr"):
            for properties in node.iter(f"{{{_A}}}{tag}"):
                try:
                    return int(properties.get("sz", "")) / 100 * 96 / 72
                except ValueError:
                    continue
    return default


def _scatter_axes(plot: Element) -> tuple[Element | None, Element | None]:
    """The x and y value axes of a scatter or bubble chart, by ``c:axPos`` (else by order)."""
    axes = list(plot.iter(f"{{{_C}}}valAx"))
    horizontal = [a for a in axes if _val(a.find("c:axPos", _NS), "") in ("b", "t")]
    vertical = [a for a in axes if _val(a.find("c:axPos", _NS), "") in ("l", "r")]
    if len(axes) == 2 and not (horizontal and vertical):
        return axes[0], axes[1]
    return (horizontal[0] if horizontal else None), (vertical[0] if vertical else None)


def _axis_gridlines(axis: Element | None) -> bool:
    """Whether ``axis`` draws major gridlines (a ``majorGridlines`` that is not no-line)."""
    lines = axis.find("c:majorGridlines", _NS) if axis is not None else None
    if lines is None:
        return False
    outline = lines.find("c:spPr/a:ln", _NS)
    return not (outline is not None and outline.find("a:noFill", _NS) is not None)


def _smooth_path(points: list[tuple[float, float]]) -> str:
    """A Catmull-Rom spline through ``points`` as cubic Béziers (PowerPoint's smoothed line)."""
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for k in range(len(points) - 1):
        before, start = points[max(k - 1, 0)], points[k]
        end, after = points[k + 1], points[min(k + 2, len(points) - 1)]
        c1 = (start[0] + (end[0] - before[0]) / 6, start[1] + (end[1] - before[1]) / 6)
        c2 = (end[0] - (after[0] - start[0]) / 6, end[1] - (after[1] - start[1]) / 6)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {end[0]:.1f} {end[1]:.1f}"
    return d


def _has_gridlines(plot: Element) -> bool:
    """Whether the value axis draws major gridlines (a ``majorGridlines`` that is not no-line)."""
    for axis in plot.iter(f"{{{_C}}}valAx"):
        lines = axis.find("c:majorGridlines", _NS)
        if lines is None:
            continue
        outline = lines.find("c:spPr/a:ln", _NS)
        return not (outline is not None and outline.find("a:noFill", _NS) is not None)
    return False


def _title(node: Element | None) -> str:
    if node is None:
        return ""
    return "".join(t.text or "" for t in node.iter(f"{{{_A}}}t"))


def _axis_titles(plot: Element) -> dict[str, str]:
    titles: dict[str, str] = {}
    for axis in list(plot.findall("c:catAx", _NS)) + list(plot.findall("c:valAx", _NS)):
        text = _title(axis.find("c:title", _NS))
        position = _val(axis.find("c:axPos", _NS), "")
        if text:
            titles["x" if position in ("b", "t") else "y"] = text
    return titles


def _axis_format(plot: Element) -> str:
    for axis in plot.findall("c:valAx", _NS):
        fmt = axis.find("c:numFmt", _NS)
        if fmt is not None and fmt.get("formatCode"):
            return fmt.get("formatCode", "General")
    return "General"


def _value_axis_deleted(plot: Element) -> bool:
    axes = plot.findall("c:valAx", _NS)
    return bool(axes) and all(_val(a.find("c:delete", _NS), "0") == "1" for a in axes)


# --------------------------------------------------------------------------- number formats


def format_number(value: float, code: str) -> str:
    """A tick or label for ``value`` under a (simplified) Excel number format."""
    base = code.split(";")[0]
    percent = "%" in base
    scaled = value * 100 if percent else value
    decimals = len(base.split(".", 1)[1].rstrip("%").rstrip("0#")) if "." in base else 0
    if "." in base:
        decimals = len(re.sub(r"[^0#]", "", base.split(".", 1)[1]))
    if base in ("General", ""):
        text = f"{scaled:.6g}"
        if "e" in text:
            text = f"{scaled:,.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{scaled:,.{decimals}f}" if "," in base else f"{scaled:.{decimals}f}"
    prefix = re.match(r'^"?([^0#,.%"]*)"?', base)
    symbol = prefix.group(1) if prefix and prefix.group(1) not in ("General",) else ""
    return f"{symbol}{text}{'%' if percent else ''}"


def _axis_floor(low: float, high: float) -> float:
    """Where an automatic value axis starts: at zero unless the data sits in a narrow band.

    This is Excel's rule: a non-negative axis begins at zero when the data spans more than a
    sixth of its maximum, and is otherwise cropped to the data.
    """
    if low >= 0 and high > 0 and (high - low) / high > 1 / 6:
        return 0.0
    return low


def _nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    if high <= low:
        high = low + 1.0
    span = high - low
    raw = span / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    digits = max(0, 3 - math.floor(math.log10(step)))
    start = math.floor(low / step) * step
    ticks: list[float] = []
    index = 0
    while start + index * step <= high + step * 1e-9 and len(ticks) < 60:
        ticks.append(round(start + index * step, digits))
        index += 1
    if ticks[-1] < high:
        ticks.append(round(start + index * step, digits))
    if len(ticks) < 2 or ticks[-1] <= ticks[0]:
        return [low, low + 1.0]
    return ticks


# --------------------------------------------------------------------------- layout and drawing


class _Canvas:
    def __init__(self, width: float, height: float) -> None:
        self.w, self.h = width, height
        self.title = ""
        self.accents: list[str] = list(_ACCENTS)
        self.legend_pos: str | None = None
        self.title_layout: tuple[float, float, float, float] | None = None
        self.title_px = 16.0
        self.title_color = ""
        self.title_bold = False
        self.legend_color = ""
        self.tick_color = "000000"
        self.background = ""
        self.background_alpha = 1.0
        self.rounded = False
        self.legend_layout: tuple[float, float, float, float] | None = None
        self.legend_px = 12.0
        self.plot_layout: tuple[float, float, float, float] | None = None
        self.grid = True
        self.grid_x = False
        self.categories_reversed = False  # the category axis runs maxMin (first at the top)
        self.grid_color = ""
        self.grid_px = 1.0
        self.defs: list[str] = []
        self.tick_px = 11.0
        self.category_px = 11.0  # the category axis's own label size and colour
        self.category_color = "000000"
        self.axis_titles: dict[str, str] = {}
        self.parts: list[str] = []

    # frame -------------------------------------------------------------------------------

    def _frame(self, names: list[tuple[str, str, bool]]) -> tuple[float, float, float, float]:
        """Draw title and legend; return the plot rectangle ``(x, y, w, h)`` that is left."""
        left, top, right, bottom = 12.0, 10.0, self.w - 12.0, self.h - 10.0
        if self.title and self.title_layout is not None:
            # Placed where the author put it, so it takes nothing from the plot's room.
            x, y = self.title_layout[0] * self.w, self.title_layout[1] * self.h
            self.parts.append(
                f'<text x="{x:.1f}" y="{y + self.title_px * 0.8:.1f}" '
                f'font-size="{self.title_px:.1f}" fill="{self._title_fill("#000000")}"'
                f"{self._title_weight('')}>{escape(self.title)}</text>"
            )
        elif self.title:
            self.parts.append(
                f'<text x="{self.w / 2:.1f}" y="{top + 14:.1f}" text-anchor="middle" '
                f'font-size="16" fill="{self._title_fill("#404040")}" font-weight="700">'
                f"{escape(self.title)}</text>"
            )
            top += 28
        if self.legend_pos and names and self.legend_layout is not None:
            self._placed_legend(names)
        elif self.legend_pos and names:
            top, right, bottom, left = self._legend(names, top, right, bottom, left)
        return left, top, max(10.0, right - left), max(10.0, bottom - top)

    def _legend(
        self,
        names: list[tuple[str, str, bool]],
        top: float,
        right: float,
        bottom: float,
        left: float,
    ) -> tuple[float, float, float, float]:
        position = self.legend_pos or "r"
        size = 12
        entry_widths = [min(200.0, 30 + len(label) * 6.8) for label, _, _ in names]
        if position in ("r", "l"):
            width = max(entry_widths) + 8
            x = right - width if position == "r" else left
            y = top + 8
            for (label, color, line), _w in zip(names, entry_widths, strict=True):
                self._swatch(x, y, label, color, size, line)
                y += 20
            if position == "r":
                right -= width + 8
            else:
                left += width + 8
        else:
            total = sum(entry_widths)
            x = max(left, (left + right - total) / 2)
            y = bottom - 16 if position == "b" else top + 4
            for (label, color, line), width in zip(names, entry_widths, strict=True):
                self._swatch(x, y, label, color, size, line)
                x += width
            if position == "b":
                bottom -= 26
            else:
                top += 26
        return top, right, bottom, left

    def _placed_legend(self, names: list[tuple[str, str, bool]]) -> None:
        """A legend row where the author put it (``c:legend`` manual layout)."""
        assert self.legend_layout is not None
        x, y = self.legend_layout[0] * self.w, self.legend_layout[1] * self.h
        size = round(self.legend_px)
        for label, color, line in names:
            self._swatch(x, y, label, color, size, line)
            if self.legend_pos in ("r", "l"):
                y += self.legend_px * 1.6  # a side legend stacks its entries
            else:
                x += min(200.0, 24 + len(label) * self.legend_px * 0.58)

    @staticmethod
    def _line_path(series: Series, points: list[tuple[float, float]]) -> str:
        """A series' line through ``points``, smoothed, dashed and sized as the series says."""
        path = (
            _smooth_path(points)
            if series.smooth
            else " ".join(
                f"{'M' if k == 0 else 'L'}{x:.1f} {y:.1f}" for k, (x, y) in enumerate(points)
            )
        )
        return (
            f'<path d="{path}" fill="none" stroke="#{series.color}" '
            f'stroke-width="{series.line_px:g}"{_dash_attr(series.dash, series.line_px)} '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )

    def _marker(self, series: Series, x: float, y: float) -> str:
        symbol = series.marker_symbol or _AUTO_MARKERS[series.position % len(_AUTO_MARKERS)]
        return _marker_svg(symbol, x, y, series.marker_px, series.marker_color or series.color)

    def _swatch(
        self, x: float, y: float, label: str, color: str, size: int, line: bool = False
    ) -> None:
        if line:
            # A line series is keyed by a short line with its marker, as PowerPoint draws it.
            mark = (
                f'<line x1="{x - 2:.1f}" y1="{y + 5:.1f}" x2="{x + 12:.1f}" y2="{y + 5:.1f}" '
                f'stroke="#{color}" stroke-width="2"/>'
                f'<circle cx="{x + 5:.1f}" cy="{y + 5:.1f}" r="2.6" fill="#{color}"/>'
            )
        else:
            mark = f'<rect x="{x:.1f}" y="{y:.1f}" width="10" height="10" fill="#{color}"/>'
        self.parts.append(
            f"{mark}"
            f'<text x="{x + 15:.1f}" y="{y + 9.5:.1f}" font-size="{size}" '
            f'fill="{"#" + self.legend_color if self.legend_color else _TEXT}">'
            f"{escape(label)}</text>"
        )

    def _title_fill(self, default: str) -> str:
        return f"#{self.title_color}" if self.title_color else default

    def _title_weight(self, default: str) -> str:
        return ' font-weight="700"' if self.title_bold else default

    def _wrap(self) -> str:
        # The chart's own background (``chartSpace`` fill) sits behind everything else.
        back = (
            f'<rect width="{self.w:g}" height="{self.h:g}" rx="{12 if self.rounded else 0}" '
            f'fill="#{self.background}" fill-opacity="{self.background_alpha:g}"/>'
            if self.background
            else ""
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w:g}" height="{self.h:g}" '
            f'viewBox="0 0 {self.w:g} {self.h:g}" font-family="{_FONT}">'
            f"{'<defs>' + ''.join(self.defs) + '</defs>' if self.defs else ''}"
            f"{back}{''.join(self.parts)}</svg>"
        )

    # cartesian ---------------------------------------------------------------------------

    def cartesian(self, groups: list[Group], axis_format: str, value_axis_hidden: bool) -> str:
        names = [(s.name, s.color, g.kind == "line" and s.line) for g in groups for s in g.series]
        horizontal = groups[0].horizontal and groups[0].kind == "bar"
        x0, y0, pw, ph = self._frame(names)
        categories: list[str] = []
        for group in groups:
            for series in group.series:
                if len(series.categories) > len(categories):
                    categories = series.categories
        count = max(
            len(categories), max((len(s.values) for g in groups for s in g.series), default=0)
        )
        if count == 0:
            return self._wrap()
        low, high = self._extent(groups)
        percent = any(g.grouping == "percentStacked" for g in groups)
        # Excel leaves 5% above the tallest value and spaces its gridlines about 27 px apart (a
        # horizontal value axis runs along the width and needs room for its labels: about 70 px).
        if horizontal:
            room, spacing = (
                self.plot_layout[2] * self.w if self.plot_layout is not None else pw,
                50.0,
            )
        else:
            x_title = self.axis_titles.get("x", "")
            room, spacing = (
                self.plot_layout[3] * self.h
                if self.plot_layout is not None
                else max(10.0, ph - (24 + (16 if x_title else 0))),
                27.0,
            )
        padded = high if percent or high <= 0 else high + 0.05 * (high - low)
        ticks = _nice_ticks(low, padded, max(4, min(10, int(room / spacing))))
        low, high = ticks[0], ticks[-1]
        code = "0%" if percent else axis_format
        gutter = (
            0 if value_axis_hidden else 8 + max(len(format_number(t, code)) for t in ticks) * 6.5
        )
        x_label = self.axis_titles.get("x" if not horizontal else "y", "")
        y_label = self.axis_titles.get("y" if not horizontal else "x", "")
        left = x0 + gutter + (16 if y_label else 0)
        bottom_gutter = 24 + (16 if x_label else 0)
        plot_w, plot_h = (
            max(10.0, pw - gutter - (16 if y_label else 0)),
            max(10.0, ph - bottom_gutter),
        )
        top = y0
        if self.plot_layout is not None and self.plot_layout[2] > 0 and self.plot_layout[3] > 0:
            # The author fixed the inner plot rectangle (the axes' own area).
            left, top = self.plot_layout[0] * self.w, self.plot_layout[1] * self.h
            plot_w, plot_h = self.plot_layout[2] * self.w, self.plot_layout[3] * self.h
        if horizontal:
            return self._horizontal(
                groups,
                categories,
                count,
                ticks,
                code,
                (left, top, plot_w, plot_h),
                x_label,
                y_label,
            )

        def y_of(value: float) -> float:
            return top + plot_h - (value - low) / (high - low) * plot_h

        for tick in ticks:
            y = y_of(tick)
            if self.grid:
                self.parts.append(
                    f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{left + plot_w:.1f}" y2="{y:.1f}" '
                    f'stroke="{"#" + self.grid_color if self.grid_color else _GRID}" '
                    f'stroke-width="{self.grid_px:g}"/>'
                )
            if not value_axis_hidden:
                self.parts.append(
                    f'<text x="{left - 6:.1f}" y="{y + self.tick_px * 0.36:.1f}" '
                    f'text-anchor="end" font-size="{self.tick_px:.1f}" '
                    f'fill="#{self.tick_color}">{escape(format_number(tick, code))}</text>'
                )
        slot = plot_w / count
        bar_groups = [g for g in groups if g.kind == "bar"]
        clustered = [s for g in bar_groups if g.grouping == "clustered" for s in g.series]
        for group in groups:
            self._draw_group(group, slot, left, y_of, low, high, clustered, count)
        axis_y = y_of(max(low, min(0.0, high)))
        self.parts.append(
            f'<line x1="{left:.1f}" y1="{axis_y:.1f}" x2="{left + plot_w:.1f}" y2="{axis_y:.1f}" '
            f'stroke="#BFBFBF" stroke-width="1"/>'
        )
        step = max(1, math.ceil(count * 40 / plot_w)) if plot_w else 1
        for i in range(0, count, step):
            label = categories[i] if i < len(categories) else str(i + 1)
            self.parts.append(
                f'<text x="{left + slot * (i + 0.5):.1f}" '
                f'y="{top + plot_h + 6 + self.category_px:.1f}" '
                f'text-anchor="middle" font-size="{self.category_px:.1f}" '
                f'fill="#{self.category_color}">'
                f"{escape(label)}</text>"
            )
        self._axis_titles(left, top, plot_w, plot_h, x_label, y_label)
        return self._wrap()

    def _extent(self, groups: list[Group]) -> tuple[float, float]:
        low = high = 0.0
        for group in groups:
            if group.kind in ("bar", "area", "line") and group.grouping in (
                "stacked",
                "percentStacked",
            ):
                if group.grouping == "percentStacked":
                    low, high = min(low, 0.0), max(high, 1.0)
                    continue
                count = max((len(s.values) for s in group.series), default=0)
                for i in range(count):
                    column = [_at(s.values, i) or 0.0 for s in group.series]
                    positive = sum(v for v in column if v > 0)
                    negative = sum(v for v in column if v < 0)
                    low, high = min(low, negative), max(high, positive)
            else:
                for s in group.series:
                    present = [v for v in s.values if v is not None]
                    if present:
                        low, high = min(low, min(present)), max(high, max(present))
        return low, high

    def _draw_group(
        self,
        group: Group,
        slot: float,
        left: float,
        y_of: Callable[[float], float],
        low: float,
        high: float,
        clustered: list[Series],
        count: int,
    ) -> None:
        stacked = group.grouping in ("stacked", "percentStacked")
        percent = group.grouping == "percentStacked"
        totals = [
            sum(abs(_at(s.values, i) or 0.0) for s in group.series) or 1.0 for i in range(count)
        ]
        running_positive = [0.0] * count
        running_negative = [0.0] * count
        gap = group.gap_width / 100
        if group.kind == "stock":
            self._stock(group, slot, left, y_of, count)
            return
        if group.kind == "bar":
            per = max(1, len(clustered)) if not stacked else 1
            bar_w = slot / (per + gap)
            overlap = group.overlap / 100
            for s_index, series in enumerate(group.series):
                for i in range(count):
                    value = _at(series.values, i)
                    if value is None:
                        continue
                    amount = value / totals[i] if percent else value
                    if stacked:
                        base = running_positive[i] if amount >= 0 else running_negative[i]
                        start, end = base, base + amount
                        if amount >= 0:
                            running_positive[i] = end
                        else:
                            running_negative[i] = end
                        x = left + slot * i + (slot - bar_w) / 2
                    else:
                        slot_index = next(
                            (k for k, s in enumerate(clustered) if s is series), s_index
                        )
                        x = left + slot * i + (slot - bar_w * per + bar_w * overlap * (per - 1)) / 2
                        x += slot_index * bar_w * (1 - overlap)
                        start, end = 0.0, amount
                    y1, y2 = y_of(max(start, end)), y_of(min(start, end))
                    own = series.point_colors.get(i)
                    paint, opacity = (f"#{own}", "") if own else self._paint(series)
                    self.parts.append(
                        f'<rect x="{x:.1f}" y="{y1:.1f}" width="{bar_w:.1f}" '
                        f'height="{max(0.0, y2 - y1):.1f}" fill="{paint}"{opacity}/>'
                    )
                    if series.show_values:
                        height = max(0.0, y2 - y1)
                        size = series.label_px
                        negative = amount < 0
                        # Positions run from the bar's far end ("end") back to the zero line
                        # ("base"); a negative bar hangs down, so its ends swap.
                        end_y, base_y = (y2, y1) if negative else (y1, y2)
                        step = -1 if negative else 1
                        at = {
                            "inEnd": end_y + step * (size + 3) if not negative else end_y - 4,
                            "ctr": y1 + height / 2 + size * 0.35,
                            "inBase": base_y - 4 if not negative else base_y + size + 3,
                        }.get(series.label_pos, end_y + (size + 3 if negative else -4))
                        self._label(x + bar_w / 2, at, amount, series.format_code, percent, series)
            return
        for series in group.series:
            points = [
                (left + slot * (i + 0.5), y_of(_cumulative(group, series, i, count)))
                for i in range(count)
                if _at(series.values, i) is not None
            ]
            if group.kind == "area":
                self._area(group, series, left, slot, y_of, count, running_positive)
            elif len(points) > 1 and series.line:
                self.parts.append(self._line_path(series, points))
            if series.marker:
                for x, y in points:
                    self.parts.append(self._marker(series, x, y))
            if series.show_values:
                for i, (x, y) in enumerate(points):
                    self._label(
                        x,
                        y,
                        _at(series.values, i) or 0.0,
                        series.format_code,
                        False,
                        series,
                        line_point=True,
                    )

    def _stock(
        self,
        group: Group,
        slot: float,
        left: float,
        y_of: Callable[[float], float],
        count: int,
    ) -> None:
        """High-low (and open-close) candles: series order is open, high, low, close."""
        series = group.series
        has_open = len(series) >= 4
        high, low = (series[1], series[2]) if has_open else (series[0], series[1])
        close = series[3] if has_open else series[-1]
        for i in range(count):
            x = left + slot * (i + 0.5)
            h, lo = _at(high.values, i), _at(low.values, i)
            if h is None or lo is None:
                continue
            self.parts.append(
                f'<line x1="{x:.1f}" y1="{y_of(h):.1f}" x2="{x:.1f}" y2="{y_of(lo):.1f}" '
                'stroke="#404040" stroke-width="1.5"/>'
            )
            c = _at(close.values, i)
            o = _at(series[0].values, i) if has_open else None
            if o is not None and c is not None:
                top, bottom = y_of(max(o, c)), y_of(min(o, c))
                fill = "#FFFFFF" if c >= o else "#404040"
                self.parts.append(
                    f'<rect x="{x - slot * 0.2:.1f}" y="{top:.1f}" width="{slot * 0.4:.1f}" '
                    f'height="{max(1.0, bottom - top):.1f}" fill="{fill}" stroke="#404040"/>'
                )
            elif c is not None:
                self.parts.append(
                    f'<line x1="{x:.1f}" y1="{y_of(c):.1f}" x2="{x + slot * 0.25:.1f}" '
                    f'y2="{y_of(c):.1f}" stroke="#404040" stroke-width="1.5"/>'
                )

    def _area(
        self,
        group: Group,
        series: Series,
        left: float,
        slot: float,
        y_of: Callable[[float], float],
        count: int,
        running: list[float],
    ) -> None:
        top_points: list[tuple[float, float]] = []
        bottom_points: list[tuple[float, float]] = []
        stacked = group.grouping in ("stacked", "percentStacked")
        totals = [
            sum(abs(_at(s.values, i) or 0.0) for s in group.series) or 1.0 for i in range(count)
        ]
        for i in range(count):
            value = _at(series.values, i) or 0.0
            if group.grouping == "percentStacked":
                value /= totals[i]
            base = running[i] if stacked else 0.0
            x = left + slot * (i + 0.5)
            top_points.append((x, y_of(base + value)))
            bottom_points.append((x, y_of(base)))
            if stacked:
                running[i] = base + value
        outline = top_points + bottom_points[::-1]
        d = " ".join(f"{'M' if k == 0 else 'L'}{x:.1f} {y:.1f}" for k, (x, y) in enumerate(outline))
        paint, opacity = self._paint(series)
        self.parts.append(f'<path d="{d} Z" fill="{paint}"{opacity} stroke="#{series.color}"/>')

    def _paint(self, series: Series) -> tuple[str, str]:
        """A series' fill as an SVG paint and its ``fill-opacity`` attribute (maybe empty)."""
        if series.gradient:
            name = f"g{len(self.defs)}"
            angle = math.radians(series.gradient_angle)
            dx, dy = math.cos(angle) / 2, math.sin(angle) / 2
            stops = "".join(
                f'<stop offset="{position:g}" stop-color="#{colour}" stop-opacity="{opacity:g}"/>'
                for position, colour, opacity in series.gradient
            )
            self.defs.append(
                f'<linearGradient id="{name}" x1="{0.5 - dx:g}" y1="{0.5 - dy:g}" '
                f'x2="{0.5 + dx:g}" y2="{0.5 + dy:g}">{stops}</linearGradient>'
            )
            return f"url(#{name})", ""
        alpha = series.alpha
        return f"#{series.color}", f' fill-opacity="{alpha:g}"' if alpha is not None else ""

    def _label(
        self,
        x: float,
        y: float,
        value: float,
        code: str,
        percent: bool,
        series: Series,
        *,
        line_point: bool = False,
    ) -> None:
        text = format_number(value, "0%" if percent else code)
        anchor = "middle"
        if line_point:
            # ``y`` is the data point; the label sits where ``dLblPos`` says (above by default).
            size = series.label_px
            if series.label_pos == "b":
                y += size + 4
            elif series.label_pos == "r":
                x, y, anchor = x + 8, y + size * 0.35, "start"
            elif series.label_pos == "l":
                x, y, anchor = x - 8, y + size * 0.35, "end"
            elif series.label_pos == "ctr":
                y += size * 0.35
            else:
                y -= 8
        fill = f"#{series.label_color}" if series.label_color else _TEXT
        weight = ' font-weight="700"' if series.label_bold else ""
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{series.label_px:.1f}" fill="{fill}"{weight}>{escape(text)}</text>'
        )

    def _axis_titles(
        self, left: float, top: float, pw: float, ph: float, x_label: str, y_label: str
    ) -> None:
        if x_label:
            self.parts.append(
                f'<text x="{left + pw / 2:.1f}" y="{top + ph + 38:.1f}" text-anchor="middle" '
                f'font-size="12" fill="{_TEXT}">{escape(x_label)}</text>'
            )
        if y_label:
            self.parts.append(
                f'<text transform="translate(12 {top + ph / 2:.1f}) rotate(-90)" '
                f'text-anchor="middle" font-size="12" fill="{_TEXT}">{escape(y_label)}</text>'
            )

    def _horizontal(
        self,
        groups: list[Group],
        categories: list[str],
        count: int,
        ticks: list[float],
        code: str,
        rect: tuple[float, float, float, float],
        x_label: str,
        y_label: str,
    ) -> str:
        left, top, plot_w, plot_h = rect
        low, high = ticks[0], ticks[-1]
        slot = plot_h / count
        group = groups[0]
        stacked = group.grouping in ("stacked", "percentStacked")
        percent = group.grouping == "percentStacked"
        per = 1 if stacked else max(1, len(group.series))
        thickness = slot / (per + group.gap_width / 100)
        for tick in ticks:
            x = left + (tick - low) / (high - low) * plot_w
            if self.grid:
                self.parts.append(
                    f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{top + plot_h:.1f}" '
                    f'stroke="#{self.grid_color or "000000"}" stroke-width="{self.grid_px:g}"/>'
                )
            self.parts.append(
                f'<text x="{x:.1f}" y="{top + plot_h + 16:.1f}" text-anchor="middle" '
                f'font-size="{self.tick_px:.1f}" fill="#{self.tick_color}">'
                f"{escape(format_number(tick, code))}</text>"
            )
        running_positive = [0.0] * count
        running_negative = [0.0] * count
        # A horizontal bar chart runs its first category (and series) along the bottom, unless
        # the category axis is reversed.
        flip = not self.categories_reversed

        def row(i: int) -> int:
            return count - 1 - i if flip else i

        for s_index, series in enumerate(group.series):
            for i in range(count):
                value = _at(series.values, i)
                if value is None:
                    continue
                total = sum(abs(_at(s.values, i) or 0.0) for s in group.series) or 1.0
                amount = value / total if percent else value
                running = running_positive if amount >= 0 else running_negative
                start = running[i] if stacked else 0.0
                end = start + amount
                if stacked:
                    running[i] = end
                y = (
                    top
                    + slot * row(i)
                    + (slot - thickness * per) / 2
                    + (0 if stacked else (per - 1 - s_index if flip else s_index) * thickness)
                )
                x1 = left + (min(start, end) - low) / (high - low) * plot_w
                x2 = left + (max(start, end) - low) / (high - low) * plot_w
                self.parts.append(
                    f'<rect x="{x1:.1f}" y="{y:.1f}" width="{max(0.0, x2 - x1):.1f}" '
                    f'height="{thickness:.1f}" fill="#{series.point_colors.get(i, series.color)}"/>'
                )
        for i in range(count):
            label = categories[i] if i < len(categories) else str(i + 1)
            self.parts.append(
                f'<text x="{left - 6:.1f}" y="{top + slot * (row(i) + 0.5) + 4:.1f}" '
                f'text-anchor="end" font-size="{self.category_px:.1f}" '
                f'fill="#{self.category_color}">{escape(label)}</text>'
            )
        self._axis_titles(left, top, plot_w, plot_h, x_label, y_label)
        return self._wrap()

    # scatter -----------------------------------------------------------------------------

    def scatter(self, group: Group, axis_format: str) -> str:
        names = [(s.name, s.color, False) for s in group.series]
        x0, y0, pw, ph = self._frame(names)
        xs = [x for s in group.series for x in (s.xs or [])]
        ys = [v for s in group.series for v in s.values if v is not None]
        if not xs or not ys:
            return self._wrap()
        # Excel leaves 5% above the data on both axes and a gridline about every 27 px (every 70 px
        # along the width); a bubble chart also leaves room for its biggest bubble at the edges.
        x_low = _axis_floor(min(xs), max(xs))
        x_high = max(xs) + (0.1 if group.kind == "bubble" else 0.05) * (max(xs) - x_low)
        y_low, y_high = min(0.0, min(ys)), max(ys)
        gutter = (
            8
            + max(len(format_number(t, axis_format)) for t in (y_low, y_high)) * self.tick_px * 0.6
            + self.tick_px * 0.6
        )
        left, top = x0 + gutter, y0
        plot_w, plot_h = max(10.0, pw - gutter), max(10.0, ph - 24)
        x_ticks = _nice_ticks(x_low, x_high, max(4, min(10, int(plot_w / 70))))
        y_ticks = _nice_ticks(
            y_low, y_high + 0.05 * (y_high - y_low), max(4, min(10, math.ceil(plot_h / 27)))
        )

        def px(value: float) -> float:
            return left + (value - x_ticks[0]) / (x_ticks[-1] - x_ticks[0]) * plot_w

        def py(value: float) -> float:
            return top + plot_h - (value - y_ticks[0]) / (y_ticks[-1] - y_ticks[0]) * plot_h

        grid = f"#{self.grid_color or '000000'}"
        for tick in y_ticks:
            if self.grid:
                self.parts.append(
                    f'<line x1="{left:.1f}" y1="{py(tick):.1f}" x2="{left + plot_w:.1f}" '
                    f'y2="{py(tick):.1f}" stroke="{grid}" stroke-width="{self.grid_px:g}"/>'
                )
            self.parts.append(
                f'<text x="{left - 6:.1f}" y="{py(tick) + 4:.1f}" text-anchor="end" '
                f'font-size="{self.tick_px:.1f}" fill="#{self.tick_color}">'
                f"{escape(format_number(tick, axis_format))}</text>"
            )
        for tick in x_ticks:
            if self.grid_x:
                self.parts.append(
                    f'<line x1="{px(tick):.1f}" y1="{top:.1f}" x2="{px(tick):.1f}" '
                    f'y2="{top + plot_h:.1f}" stroke="{grid}" stroke-width="{self.grid_px:g}"/>'
                )
            self.parts.append(
                f'<text x="{px(tick):.1f}" y="{top + plot_h + 16:.1f}" text-anchor="middle" '
                f'font-size="{self.tick_px:.1f}" fill="#{self.tick_color}">'
                f"{escape(format_number(tick, 'General'))}</text>"
            )
        for series in group.series:
            points = [
                (px(x), py(v))
                for x, v in zip(series.xs or [], series.values, strict=False)
                if v is not None
            ]
            if group.kind != "bubble" and series.line and len(points) > 1:
                self.parts.append(self._line_path(series, points))
            if group.kind == "bubble":
                peak = max((v for v in (series.sizes or []) if v), default=1.0)
                for (x, y), size in zip(points, series.sizes or [], strict=False):
                    # The biggest bubble is a quarter of the plot's short side across, at 100%.
                    radius = (
                        min(plot_w, plot_h)
                        / 8
                        * group.bubble_scale
                        * math.sqrt(max(size or 0.0, 0.0) / peak)
                    )
                    paint, opacity = self._paint(series)
                    self.parts.append(
                        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                        f'fill="{paint}"{opacity}/>'
                    )
            elif series.marker:
                for x, y in points:
                    self.parts.append(self._marker(series, x, y))
        self._axis_titles(
            left, top, plot_w, plot_h, self.axis_titles.get("x", ""), self.axis_titles.get("y", "")
        )
        return self._wrap()

    # circular ----------------------------------------------------------------------------

    def pie(self, group: Group) -> str:
        first = group.series[0]
        names = [
            (
                first.categories[i] if i < len(first.categories) else str(i + 1),
                first.point_colors.get(i, self._slice_colour(group, first, i)),
                False,
            )
            for i in range(len(first.values))
        ]
        x0, y0, pw, ph = self._frame(names)
        radius = max(10.0, min(pw, ph) / 2 - 6)
        cx, cy = x0 + pw / 2, y0 + ph / 2
        rings = group.series if group.kind == "doughnut" else group.series[:1]
        hole = radius * group.hole if group.kind == "doughnut" else 0.0
        band = (radius - hole) / len(rings)
        # The first series is the innermost ring, as in PowerPoint.
        for ring, series in enumerate(rings):
            inner = hole + band * ring
            outer = hole + band * (ring + 1) if group.kind == "doughnut" else radius
            self._ring(series, cx, cy, outer, inner if group.kind == "doughnut" else 0.0, group)
        return self._wrap()

    def _slice_colour(self, group: Group, series: Series, index: int) -> str:
        """The next accent, or the series' own colour when the slices do not vary."""
        if group.vary_colors and not series.explicit_color:
            return self.accents[index % len(self.accents)]
        return series.color

    def _ring(
        self, series: Series, cx: float, cy: float, outer: float, inner: float, group: Group
    ) -> None:
        values = [max(0.0, v or 0.0) for v in series.values]
        total = sum(values)
        if total <= 0:
            return
        angle = -math.pi / 2 + math.radians(group.first_angle)
        for i, value in enumerate(values):
            sweep = value / total * 2 * math.pi
            if sweep <= 0:
                continue
            color = series.point_colors.get(i, self._slice_colour(group, series, i))
            self.parts.append(_slice(cx, cy, outer, inner, angle, angle + sweep, color))
            if series.show_values:
                mid = angle + sweep / 2
                r = (outer + inner) / 2 if inner else outer * 0.65
                self.parts.append(
                    f'<text x="{cx + r * math.cos(mid):.1f}" y="{cy + r * math.sin(mid) + 4:.1f}" '
                    f'text-anchor="middle" font-size="11" fill="#FFFFFF">'
                    f"{escape(format_number(value, series.format_code))}</text>"
                )
            angle += sweep

    def radar(self, group: Group) -> str:
        names = [(s.name, s.color, False) for s in group.series]
        x0, y0, pw, ph = self._frame(names)
        count = max((len(s.values) for s in group.series), default=0)
        peak = max((v for s in group.series for v in s.values if v is not None), default=1.0)
        ticks = _nice_ticks(0.0, peak, 4)
        peak = ticks[-1]
        radius = max(10.0, min(pw, ph) / 2 - 22)
        cx, cy = x0 + pw / 2, y0 + ph / 2
        if count < 3:
            return self._wrap()

        def point(i: int, value: float) -> tuple[float, float]:
            theta = -math.pi / 2 + 2 * math.pi * i / count
            r = radius * value / peak
            return cx + r * math.cos(theta), cy + r * math.sin(theta)

        for tick in ticks[1:]:
            ring = " ".join(
                f"{point(i, tick)[0]:.1f},{point(i, tick)[1]:.1f}" for i in range(count)
            )
            self.parts.append(f'<polygon points="{ring}" fill="none" stroke="{_GRID}"/>')
        categories = group.series[0].categories
        for i in range(count):
            x, y = point(i, peak)
            self.parts.append(
                f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{_GRID}"/>'
            )
            lx, ly = point(i, peak * 1.12)
            label = categories[i] if i < len(categories) else str(i + 1)
            self.parts.append(
                f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle" font-size="11" '
                f'fill="{_TEXT}">{escape(label)}</text>'
            )
        for series in group.series:
            corners = [point(i, _at(series.values, i) or 0.0) for i in range(count)]
            ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)
            fill = f'fill="#{series.color}" fill-opacity="0.3"' if group.filled else 'fill="none"'
            self.parts.append(
                f'<polygon points="{ring}" {fill} stroke="#{series.color}" stroke-width="2"/>'
            )
        return self._wrap()


def _slice(
    cx: float, cy: float, outer: float, inner: float, start: float, end: float, color: str
) -> str:
    large = 1 if end - start > math.pi else 0
    x1, y1 = cx + outer * math.cos(start), cy + outer * math.sin(start)
    x2, y2 = cx + outer * math.cos(end), cy + outer * math.sin(end)
    if end - start >= 2 * math.pi - 1e-6:
        x2, y2 = x2 - 0.01, y2
    if inner > 0:
        x3, y3 = cx + inner * math.cos(end), cy + inner * math.sin(end)
        x4, y4 = cx + inner * math.cos(start), cy + inner * math.sin(start)
        d = (
            f"M{x1:.2f} {y1:.2f}A{outer:.2f} {outer:.2f} 0 {large} 1 {x2:.2f} {y2:.2f}"
            f"L{x3:.2f} {y3:.2f}A{inner:.2f} {inner:.2f} 0 {large} 0 {x4:.2f} {y4:.2f}Z"
        )
    else:
        d = (
            f"M{cx:.2f} {cy:.2f}L{x1:.2f} {y1:.2f}"
            f"A{outer:.2f} {outer:.2f} 0 {large} 1 {x2:.2f} {y2:.2f}Z"
        )
    return f'<path d="{d}" fill="#{color}" stroke="#FFFFFF" stroke-width="1"/>'


def _at(values: list[float | None], index: int) -> float | None:
    return values[index] if index < len(values) else None


def _cumulative(group: Group, series: Series, index: int, count: int) -> float:
    """The plotted height of a line point: stacked lines add up the series below them."""
    value = _at(series.values, index) or 0.0
    if group.grouping not in ("stacked", "percentStacked"):
        return value
    total = 0.0
    for other in group.series:
        total += _at(other.values, index) or 0.0
        if other is series:
            break
    if group.grouping == "percentStacked":
        everything = sum(abs(_at(s.values, index) or 0.0) for s in group.series) or 1.0
        return total / everything
    return total
