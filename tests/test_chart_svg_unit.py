# pyright: basic, reportArgumentType=false
# python-pptx is only partly typed; ruff still applies.
"""The chart renderer: each modelled chart type draws, and the rest decline."""

from __future__ import annotations

import re
from io import BytesIO
from xml.etree.ElementTree import fromstring

import pytest
from pptx import Presentation as PptxPresentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from domoxml import Presentation
from domoxml.core.chart_svg import chart_to_svg, format_number
from domoxml.types import Representation

_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"


def _chart(plot: str, extra: str = "") -> bytes:
    return (
        f'<c:chartSpace xmlns:c="{_C}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<c:chart>{extra}<c:plotArea>{plot}</c:plotArea></c:chart></c:chartSpace>"
    ).encode()


def _series(index: int, values: list[float], *, name: str = "S") -> str:
    categories = "".join(f'<c:pt idx="{i}"><c:v>C{i}</c:v></c:pt>' for i in range(len(values)))
    points = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values))
    return (
        f'<c:ser><c:idx val="{index}"/><c:tx><c:v>{name}{index}</c:v></c:tx>'
        f"<c:cat><c:strLit>{categories}</c:strLit></c:cat>"
        f"<c:val><c:numLit>{points}</c:numLit></c:val></c:ser>"
    )


def _literal(tag: str, values: list[float]) -> str:
    points = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values))
    return f"<c:{tag}><c:numLit>{points}</c:numLit></c:{tag}>"


def _svg(plot: str, extra: str = "") -> str:
    svg = chart_to_svg(_chart(plot, extra), width_px=480, height_px=300)
    assert svg is not None
    fromstring(svg)  # every chart the tests draw must be well-formed SVG
    return svg


def test_clustered_columns_draw_one_rect_per_value_with_series_colours() -> None:
    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + _series(0, [1, 2, 3])
        + _series(1, [3, 2, 1])
        + "</c:barChart>"
    )

    assert svg.count("<rect") >= 6 and "#4472C4" in svg and "#ED7D31" in svg


def test_stacked_columns_stack_and_percent_axes_read_as_percent() -> None:
    stacked = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="stacked"/>'
        + _series(0, [10, 10])
        + _series(1, [10, 10])
        + "</c:barChart>"
    )
    percent = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="percentStacked"/>'
        + _series(0, [1, 3])
        + _series(1, [3, 1])
        + "</c:barChart>"
    )

    assert "20" in stacked and "%" in percent


def test_lines_areas_pies_doughnuts_scatter_and_radar_all_draw() -> None:
    shapes = {
        "line": (
            '<c:lineChart><c:grouping val="standard"/>' + _series(0, [1, 3, 2]) + "</c:lineChart>",
            "<path",
        ),
        "area": (
            '<c:areaChart><c:grouping val="standard"/>' + _series(0, [1, 3, 2]) + "</c:areaChart>",
            "Z",
        ),
        "pie": ("<c:pieChart>" + _series(0, [1, 2, 3]) + "</c:pieChart>", "A"),
        "doughnut": (
            "<c:doughnutChart>"
            + _series(0, [1, 2, 3])
            + '<c:holeSize val="60"/></c:doughnutChart>',
            "A",
        ),
        "radar": (
            '<c:radarChart><c:radarStyle val="marker"/>'
            + _series(0, [1, 3, 2])
            + "</c:radarChart>",
            "<polygon",
        ),
    }
    for kind, (plot, marker) in shapes.items():
        assert marker in _svg(plot), kind
    scatter = _svg(
        '<c:scatterChart><c:scatterStyle val="lineMarker"/><c:ser><c:idx val="0"/>'
        + _literal("xVal", [1, 2])
        + _literal("yVal", [5, 9])
        + "</c:ser></c:scatterChart>"
    )
    assert "<polygon" in scatter  # the automatic first marker is a diamond


def _rich(text: str) -> str:
    run = f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
    return f"<c:title><c:tx><c:rich>{run}</c:rich></c:tx></c:title>"


def test_title_legend_and_axis_titles_are_drawn() -> None:
    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + _series(0, [1, 2])
        + '</c:barChart><c:catAx><c:axPos val="b"/>'
        + _rich("Quarter")
        + "</c:catAx>",
        _rich("Revenue") + '<c:legend><c:legendPos val="b"/></c:legend>',
    )

    assert "Revenue" in svg and "Quarter" in svg and "S0" in svg


def test_unmodelled_charts_decline_rather_than_guess() -> None:
    assert (
        chart_to_svg(
            _chart("<c:surfaceChart><c:wireframe val='0'/></c:surfaceChart>"),
            width_px=480,
            height_px=300,
        )
        is None
    )
    assert chart_to_svg(b"<not xml", width_px=480, height_px=300) is None
    assert chart_to_svg(_chart(""), width_px=480, height_px=300) is None


@pytest.mark.parametrize(
    ("value", "code", "text"),
    [
        (0.256, "0%", "26%"),
        (1234.5, "#,##0", "1,234"),
        (3.14159, "0.00", "3.14"),
        (7, "General", "7"),
    ],
)
def test_number_formats(value: float, code: str, text: str) -> None:
    assert format_number(value, code) == text


def _deck_with_charts() -> bytes:
    deck = PptxPresentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    data = CategoryChartData()
    data.categories = ["Q1", "Q2", "Q3"]
    data.add_series("East", (10, 14, 9))
    data.add_series("West", (7, 11, 13))
    slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(0.5), Inches(4), Inches(3), data
    )
    slide.shapes.add_chart(XL_CHART_TYPE.PIE, Inches(5), Inches(0.5), Inches(4), Inches(3), data)
    xy = XyChartData()
    series = xy.add_series("pts")
    for x, y in ((1, 2), (2, 5), (3, 3)):
        series.add_data_point(x, y)
    slide.shapes.add_chart(
        XL_CHART_TYPE.XY_SCATTER, Inches(0.5), Inches(4), Inches(4), Inches(3), xy
    )
    buffer = BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def test_pptx_charts_reach_html_as_vector_with_their_source_attached() -> None:
    html = Presentation.from_pptx(_deck_with_charts())

    charts = [item for item in html.coverage.items if "chart" in item.reason]
    assert len(charts) == 3
    assert all(item.representation is Representation.APPROXIMATED for item in charts)
    assert all(item.raster_area_emu2 == 0 for item in charts)
    svgs = [asset for asset in html.assets if asset.path.endswith(".svg")]
    assert len(svgs) == 3 and all(b"<svg" in asset.data for asset in svgs)
    assert html.slides[0].html.count("data-domoxml-preserved-payload") == 3


def test_tiny_values_and_flat_data_still_get_a_distinct_axis() -> None:
    tiny = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + _series(0, [1e-12, 2e-12])
        + "</c:barChart>"
    )
    flat = _svg(
        '<c:lineChart><c:grouping val="standard"/>' + _series(0, [5, 5, 5]) + "</c:lineChart>"
    )

    assert "<rect" in tiny and "<path" in flat


def test_stacked_lines_axis_covers_the_running_total() -> None:
    svg = _svg(
        '<c:lineChart><c:grouping val="stacked"/>'
        + _series(0, [10, 10])
        + _series(1, [10, 10])
        + "</c:lineChart>"
    )

    assert ">20<" in svg and 'y="-' not in svg


def test_horizontal_stacks_extend_negatives_leftwards_from_zero() -> None:
    svg = _svg(
        '<c:barChart><c:barDir val="bar"/><c:grouping val="stacked"/>'
        + _series(0, [10])
        + _series(1, [-5])
        + "</c:barChart>"
    )
    rects = [part for part in svg.split("<rect")[1:] if 'fill="#ED7D31"' in part]
    x_positive = float(svg.split('<rect x="')[1].split('"')[0])

    assert rects and float(rects[0].split('x="')[1].split('"')[0]) < x_positive


def test_every_doughnut_series_is_a_ring_and_colours_are_validated() -> None:
    two_rings = _svg(
        "<c:doughnutChart>" + _series(0, [1, 2]) + _series(1, [3, 1]) + "</c:doughnutChart>"
    )
    assert two_rings.count("<path") == 4

    hostile = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        '<c:ser><c:idx val="0"/><c:spPr><a:solidFill><a:srgbClr val="F00&quot; onload=&quot;x"/>'
        "</a:solidFill></c:spPr><c:val><c:numLit>"
        '<c:pt idx="0"><c:v>1</c:v></c:pt></c:numLit></c:val></c:ser></c:barChart>'
    )
    assert "onload" not in hostile and "#4472C4" in hostile


def test_entities_in_chart_xml_decline_instead_of_raising() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE c [<!ENTITY a "x">]>'
        b'<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">&a;'
        b"</c:chartSpace>"
    )

    assert chart_to_svg(bomb, width_px=480, height_px=300) is None


def test_a_series_colour_keeps_its_lightness_transform_and_resolves_roles_through_the_theme() -> (
    None
):
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    series = _series(0, [1, 2]).replace(
        "</c:ser>",
        f'<c:spPr><a:solidFill xmlns:a="{a}"><a:schemeClr val="tx2"><a:lumMod val="50000"/>'
        '<a:lumOff val="50000"/></a:schemeClr></a:solidFill></c:spPr></c:ser>',
    )
    svg = chart_to_svg(
        _chart(
            '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
            + series
            + "</c:barChart>"
        ),
        width_px=480,
        height_px=300,
        theme={"dk2": "08284F"},  # a deck that names its dark colour dk2, not tx2
    )

    assert svg is not None
    # dk2 at half lightness plus half: a light blue, not the plain navy and not Office's grey-blue.
    assert "#08284F" not in svg and "#44546A" not in svg and 'fill="#3' in svg


_BAR = (
    '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
    + _series(0, [1, 2, 3])
    + "</c:barChart>"
)


def test_gridlines_are_drawn_only_when_the_value_axis_has_visible_ones() -> None:
    def axis(grid: str) -> str:
        no_axis_line = "<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>"
        return f'<c:valAx><c:axId val="1"/>{grid}<c:delete val="0"/>{no_axis_line}</c:valAx>'

    visible = "<c:majorGridlines><c:spPr><a:ln><a:solidFill/></a:ln></c:spPr></c:majorGridlines>"
    hidden = "<c:majorGridlines><c:spPr><a:ln><a:noFill/></a:ln></c:spPr></c:majorGridlines>"

    # Unstyled gridlines are PowerPoint's automatic ones: black hairlines.
    assert 'stroke="#000000" stroke-width="1"' in _svg(_BAR + axis(visible))
    assert 'stroke="#000000" stroke-width="1"' not in _svg(_BAR + axis(hidden))
    assert 'stroke="#000000" stroke-width="1"' not in _svg(_BAR + axis(""))


def test_a_title_element_without_text_shows_powerpoints_placeholder_at_its_own_position() -> None:
    title = (
        '<c:title><c:layout><c:manualLayout><c:xMode val="edge"/><c:yMode val="edge"/>'
        '<c:x val="0.1"/><c:y val="0.05"/></c:manualLayout></c:layout>'
        '<c:overlay val="0"/></c:title>'
    )

    svg = _svg(_BAR, title)

    assert "Chart Title" in svg and 'x="48.0"' in svg  # 0.1 of the 480 px chart
    assert "Chart Title" not in _svg(_BAR, title + '<c:autoTitleDeleted val="1"/>')


def test_a_legend_with_a_manual_layout_sits_where_the_author_put_it() -> None:
    legend = (
        '<c:legend><c:legendPos val="b"/><c:layout><c:manualLayout><c:xMode val="edge"/>'
        '<c:yMode val="edge"/><c:x val="0.5"/><c:y val="0.1"/></c:manualLayout></c:layout>'
        "</c:legend>"
    )

    svg = _svg(_BAR, legend)

    assert 'x="240.0" y="30.0"' in svg  # 0.5 and 0.1 of the 480 x 300 chart


def test_tick_and_data_label_sizes_come_from_their_own_text_properties() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    big = f'<c:txPr><a:p xmlns:a="{a}"><a:pPr><a:defRPr sz="3000"/></a:pPr></a:p></c:txPr>'
    small = f'<c:txPr><a:p xmlns:a="{a}"><a:pPr><a:defRPr sz="825"/></a:pPr></a:p></c:txPr>'
    title = (
        f'<c:title><c:tx><c:rich><a:p xmlns:a="{a}"><a:pPr><a:defRPr sz="3000"/></a:pPr></a:p>'
        "</c:rich></c:tx></c:title>"
    )
    axis = f'<c:valAx><c:axId val="1"/>{title}{small}</c:valAx>'
    first = _series(0, [1, 2]).replace(
        "</c:ser>", f'<c:dLbls>{big}<c:showVal val="1"/></c:dLbls></c:ser>'
    )
    second = _series(1, [2, 1]).replace(
        "</c:ser>", f'<c:dLbls>{small}<c:showVal val="1"/></c:dLbls></c:ser>'
    )

    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + first
        + second
        + "</c:barChart>"
        + axis
    )

    assert 'font-size="11.0"' in svg  # 8.25 pt ticks, not the 30 pt axis title's size
    assert 'font-size="40.0"' in svg and 'font-size="11.0" ' in svg  # per series, not the first


def test_an_automatic_value_axis_leaves_five_percent_above_the_tallest_value() -> None:
    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + _series(0, [1.6, 2.2, 3.5, 5.8, 8])
        + "</c:barChart>"
    )

    # 8 plus 5% is 8.4, so the axis runs 0 to 9 in unit steps (as Excel and PowerPoint draw it).
    assert ">9</text>" in svg and ">0</text>" in svg and ">8</text>" in svg
    assert ">10</text>" not in svg


def test_a_narrow_horizontal_bar_chart_keeps_fewer_axis_labels_than_a_tall_column_chart() -> None:
    bars = (
        '<c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/>'
        + _series(0, [20000, 40000, 80000])
        + "</c:barChart>"
    )
    columns = bars.replace('barDir val="bar"', 'barDir val="col"')

    narrow = chart_to_svg(_chart(bars), width_px=260, height_px=600)
    tall = chart_to_svg(_chart(columns), width_px=260, height_px=600)

    assert narrow is not None and tall is not None
    # Along 260 px the horizontal value axis fits about four labels; a 600 px column axis ten.
    assert narrow.count("0</text>") < tall.count("0</text>")


def test_line_series_get_a_line_swatch_and_labels_below_when_the_chart_says_so() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    labels = (
        f'<c:dLbls><c:txPr><a:p xmlns:a="{a}"><a:pPr><a:defRPr sz="1000" b="1">'
        '<a:solidFill><a:srgbClr val="112233"/></a:solidFill></a:defRPr></a:pPr></a:p></c:txPr>'
        '<c:dLblPos val="b"/><c:showVal val="1"/></c:dLbls>'
    )
    series = _series(0, [3, 5]).replace("</c:ser>", labels + "</c:ser>")
    legend = '<c:legend><c:legendPos val="r"/></c:legend>'

    svg = _svg('<c:lineChart><c:grouping val="standard"/>' + series + "</c:lineChart>", legend)

    assert "<polygon" in svg and 'stroke-width="1.5"' in svg  # the line-and-marker legend key
    assert 'fill="#112233" font-weight="700"' in svg  # the label's own colour and weight


def test_a_legend_key_follows_the_series_type_even_when_two_series_share_a_colour() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    same = f'<c:spPr><a:solidFill xmlns:a="{a}"><a:srgbClr val="112233"/></a:solidFill></c:spPr>'
    bar = _series(0, [1, 2]).replace("</c:ser>", same + "</c:ser>")
    line = _series(1, [2, 1]).replace("</c:ser>", same + "</c:ser>")
    legend = '<c:legend><c:legendPos val="r"/></c:legend>'

    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + bar
        + '</c:barChart><c:lineChart><c:grouping val="standard"/>'
        + line
        + "</c:lineChart>",
        legend,
    )

    assert svg.count('width="10" height="10" fill="#112233"') == 1  # the bar's square key
    assert 'width="6.7" height="6.7"' in svg  # and the line's own key, with its square marker


def test_an_inside_label_on_a_negative_column_sits_inside_the_bar() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    labels = (
        f'<c:dLbls><c:txPr><a:p xmlns:a="{a}"><a:pPr><a:defRPr sz="1000"/></a:pPr></a:p></c:txPr>'
        '<c:dLblPos val="inEnd"/><c:showVal val="1"/></c:dLbls>'
    )
    series = _series(0, [4, -4]).replace("</c:ser>", labels + "</c:ser>")

    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>' + series + "</c:barChart>"
    )

    bars = [
        (float(y), float(h))
        for y, h in re.findall(
            r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)" fill="#4472C4"', svg
        )
    ]
    labels_y = [
        float(y)
        for y in re.findall(
            r'<text x="[\d.]+" y="([\d.]+)" text-anchor="middle"[^>]*>-?4</text>', svg
        )
    ]
    (top_pos, h_pos), (top_neg, h_neg) = bars[0], bars[1]
    assert top_pos <= labels_y[0] <= top_pos + h_pos  # the positive bar's label is inside it
    assert top_neg <= labels_y[1] <= top_neg + h_neg  # and so is the negative one's


def _pie(extra_group: str = "", series_extra: str = "") -> str:
    series = _series(0, [1, 1, 1, 1]).replace("</c:ser>", series_extra + "</c:ser>")
    return _svg("<c:pieChart>" + extra_group + series + "</c:pieChart>")


def test_a_pie_starts_at_its_first_slice_angle() -> None:
    def start(svg: str) -> tuple[float, float]:
        match = re.search(r'<path d="M[\d.]+ [\d.]+L([\d.]+) ([\d.]+)', svg)
        assert match is not None
        return float(match.group(1)), float(match.group(2))

    upright = start(_pie('<c:firstSliceAng val="0"/>'))
    turned = start(_pie('<c:firstSliceAng val="90"/>'))

    # Upright starts straight above the centre; a quarter turn clockwise starts to its right.
    assert turned[0] > upright[0] + 20
    assert turned[1] > upright[1] + 20


def test_pie_slices_share_one_colour_when_they_do_not_vary_or_the_series_names_a_fill() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    plain = _pie()
    flat = _pie('<c:varyColors val="0"/>')
    named = _pie(
        series_extra=f'<c:spPr><a:solidFill xmlns:a="{a}"><a:srgbClr val="C00000"/></a:solidFill>'
        "</c:spPr>"
    )

    assert len(set(re.findall(r'<path[^>]*fill="(#\w+)"', plain))) > 1
    assert len(set(re.findall(r'<path[^>]*fill="(#\w+)"', flat))) == 1
    assert set(re.findall(r'<path[^>]*fill="(#\w+)"', named)) == {"#C00000"}


def test_a_chart_spaces_own_fill_and_text_colours_are_drawn() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    title = (
        '<c:title><c:tx><c:rich><a:p xmlns:a="' + a + '"><a:r><a:rPr b="1"><a:solidFill>'
        '<a:srgbClr val="FFFFFF"/></a:solidFill></a:rPr><a:t>Dark</a:t></a:r></a:p></c:rich></c:tx>'
        "</c:title>"
    )
    chart = (
        f'<c:chartSpace xmlns:c="{_C}"><c:roundedCorners val="1"/>'
        f'<c:spPr><a:solidFill xmlns:a="{a}"><a:srgbClr val="202020"/></a:solidFill></c:spPr>'
        f"<c:chart>{title}<c:plotArea><c:pieChart>{_series(0, [1, 2])}</c:pieChart></c:plotArea>"
        "</c:chart></c:chartSpace>"
    ).encode()

    svg = chart_to_svg(chart, width_px=480, height_px=300)

    assert svg is not None
    assert 'rx="12" fill="#202020"' in svg  # the rounded dark background
    assert 'fill="#FFFFFF" font-weight="700"' in svg or 'fill="#FFFFFF"' in svg


def test_a_series_outline_colour_does_not_flatten_the_slices_and_a_background_keeps_its_alpha() -> (
    None
):
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    outline = _pie(
        series_extra=f'<c:spPr><a:ln xmlns:a="{a}"><a:solidFill><a:srgbClr val="FFFFFF"/>'
        "</a:solidFill></a:ln></c:spPr>"
    )
    chart = (
        f'<c:chartSpace xmlns:c="{_C}"><c:spPr><a:solidFill xmlns:a="{a}"><a:srgbClr val="202020">'
        '<a:alpha val="50000"/></a:srgbClr></a:solidFill></c:spPr>'
        f"<c:chart><c:plotArea><c:pieChart>{_series(0, [1, 2])}</c:pieChart></c:plotArea></c:chart>"
        "</c:chartSpace>"
    ).encode()

    background = chart_to_svg(chart, width_px=480, height_px=300)

    assert len(set(re.findall(r'<path[^>]*fill="(#\w+)"', outline))) > 1
    assert background is not None and 'fill="#202020" fill-opacity="0.5"' in background


def test_series_gradients_transparency_and_gridline_styling_are_drawn() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    fill = (
        f'<c:spPr><a:gradFill xmlns:a="{a}"><a:gsLst><a:gs pos="0"><a:srgbClr val="FF0000"/></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="0000FF"><a:alpha val="40000"/></a:srgbClr></a:gs>'
        '</a:gsLst><a:lin ang="5400000"/></a:gradFill></c:spPr>'
    )
    translucent = (
        f'<c:spPr><a:solidFill xmlns:a="{a}"><a:srgbClr val="00AA00"><a:alpha val="50000"/>'
        "</a:srgbClr></a:solidFill></c:spPr>"
    )
    grid = (
        f'<c:valAx><c:axId val="1"/><c:majorGridlines><c:spPr><a:ln xmlns:a="{a}" w="19050">'
        '<a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln></c:spPr></c:majorGridlines>'
        "</c:valAx>"
    )

    gradient_area = _svg(
        '<c:areaChart><c:grouping val="standard"/>'
        + _series(0, [1, 3, 2]).replace("</c:ser>", fill + "</c:ser>")
        + "</c:areaChart>"
        + grid
    )
    alpha_columns = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        + _series(0, [1, 3]).replace("</c:ser>", translucent + "</c:ser>")
        + "</c:barChart>"
    )

    assert '<linearGradient id="g0" x1="0.5" y1="0" x2="0.5" y2="1">' in gradient_area
    assert (
        'stop-color="#0000FF" stop-opacity="0.4"' in gradient_area and "url(#g0)" in gradient_area
    )
    assert 'stroke="#000000" stroke-width="2"' in gradient_area  # the chart's own gridlines
    assert 'fill="#00AA00" fill-opacity="0.5"' in alpha_columns


def test_a_column_with_its_own_point_colour_stays_well_formed_svg() -> None:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    point = (
        '<c:dPt><c:idx val="1"/><c:spPr><a:solidFill xmlns:a="' + a + '">'
        '<a:srgbClr val="FF0000"/></a:solidFill></c:spPr></c:dPt>'
    )
    series = _series(0, [1, 2, 3]).replace("</c:ser>", point + "</c:ser>")

    svg = _svg(
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>' + series + "</c:barChart>"
    )

    fromstring(svg)  # raises on malformed markup
    assert 'fill="#FF0000"/>' in svg


def _scatter(kind: str, *, smooth: str = "", scale: int | None = None, x_grid: bool = True) -> str:
    sizes = _literal("bubbleSize", [4, 16]) if kind == "bubbleChart" else ""
    scale_xml = f'<c:bubbleScale val="{scale}"/>' if scale is not None else ""
    grid = "<c:majorGridlines/>" if x_grid else ""
    return _svg(
        f'<c:{kind}><c:scatterStyle val="lineMarker"/><c:ser><c:idx val="0"/>'
        + _literal("xVal", [1, 10])
        + _literal("yVal", [10, 65])
        + sizes
        + smooth
        + f"</c:ser>{scale_xml}</c:{kind}>"
        + f'<c:valAx><c:axId val="1"/>{grid}</c:valAx>'
        + '<c:valAx><c:axId val="2"/><c:majorGridlines/></c:valAx>'
    )


def test_scatter_axes_leave_headroom_and_draw_vertical_gridlines() -> None:
    svg = _scatter("scatterChart")
    labels = re.findall(r">(\d+)</text>", svg)

    assert "12" in labels and "70" in labels  # 10 and 65 round up past the data
    assert len(re.findall(r'<line x1="([\d.]+)"[^>]* x2="\1"', svg)) >= 5  # vertical gridlines
    assert _scatter("scatterChart", x_grid=False).count("<line") < svg.count("<line")


def test_scatter_lines_are_smoothed_unless_the_series_says_otherwise() -> None:
    assert " C" in _scatter("scatterChart")
    assert " C" not in _scatter("scatterChart", smooth='<c:smooth val="0"/>')


def test_bubbles_are_opaque_and_follow_the_bubble_scale() -> None:
    def biggest(svg: str) -> float:
        return max(float(r) for r in re.findall(r'<circle[^>]* r="([\d.]+)"', svg))

    small, large = _scatter("bubbleChart", scale=50), _scatter("bubbleChart", scale=100)

    assert "fill-opacity" not in large
    assert abs(biggest(large) / biggest(small) - 2) < 0.05


def _two_series_scatter(second_smooth: str, axes: str) -> str:
    def ser(index: int, smooth: str) -> str:
        return (
            f'<c:ser><c:idx val="{index}"/>'
            + _literal("xVal", [1, 2, 3])
            + _literal("yVal", [1, 5, 2])
            + smooth
            + "</c:ser>"
        )

    return _svg(
        '<c:scatterChart><c:scatterStyle val="lineMarker"/>'
        + ser(0, '<c:smooth val="1"/>')
        + ser(1, second_smooth)
        + "</c:scatterChart>"
        + axes
    )


def test_each_scatter_series_keeps_its_own_smoothing() -> None:
    svg = _two_series_scatter('<c:smooth val="0"/>', "")

    assert len(re.findall(r'<path d="M[^"]* C', svg)) == 1  # one curve, one polyline
    assert len(re.findall(r'<path d="M[^"]*" fill="none"', svg)) == 2


def test_scatter_gridlines_follow_the_axis_position_and_no_line_style() -> None:
    grid = "<c:majorGridlines/>"
    hidden = "<c:majorGridlines><c:spPr><a:ln><a:noFill/></a:ln></c:spPr></c:majorGridlines>"

    def lines(y_grid: str, x_grid: str) -> str:  # the vertical axis listed first
        return (
            f'<c:valAx><c:axId val="2"/><c:axPos val="l"/>{y_grid}</c:valAx>'
            f'<c:valAx><c:axId val="1"/><c:axPos val="b"/>{x_grid}</c:valAx>'
        )

    def vertical(svg: str) -> int:
        return len(re.findall(r'<line x1="([\d.]+)"[^>]* x2="\1"', svg))

    only_y = _two_series_scatter("", lines(grid, ""))
    only_x = _two_series_scatter("", lines("", grid))
    x_hidden = _two_series_scatter("", lines(grid, hidden))

    assert vertical(only_y) == 0 and vertical(only_x) > 0 and vertical(x_hidden) == 0
    assert "<line" in only_y and "<line" not in only_x.replace("<line", "", vertical(only_x))


def _bars(orientation: str) -> str:
    return _svg(
        '<c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/>'
        + _series(0, [1, 2, 3])
        + _series(1, [3, 2, 1])
        + "</c:barChart>"
        + f'<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="{orientation}"/></c:scaling>'
        + "</c:catAx>"
    )


def _label_order(svg: str) -> list[str]:
    texts = [
        (float(y), t) for y, t in re.findall(r'<text[^>]* y="([\d.]+)"[^>]*>(C\d)</text>', svg)
    ]
    return [t for _, t in sorted(texts)]


def test_horizontal_bars_run_the_first_category_along_the_bottom() -> None:
    assert _label_order(_bars("minMax")) == ["C2", "C1", "C0"]
    assert _label_order(_bars("maxMin")) == ["C0", "C1", "C2"]


def test_horizontal_bar_series_stack_upwards_within_a_cluster() -> None:
    def first_cluster(svg: str) -> list[str]:
        rects = re.findall(r'<rect x="[\d.]+" y="([\d.]+)"[^>]*fill="(#\w+)"', svg)
        return [colour for _, colour in sorted((float(y), c) for y, c in rects)][:2]

    upwards, downwards = first_cluster(_bars("minMax")), first_cluster(_bars("maxMin"))

    assert upwards[0] != upwards[1] and upwards == downwards[::-1]


def test_category_labels_take_the_category_axis_text_style_not_the_value_axis() -> None:
    def axes(value_size: int) -> str:
        return (
            '<c:catAx><c:axId val="1"/><c:txPr><a:p><a:pPr><a:defRPr sz="900"/></a:pPr></a:p>'
            "</c:txPr></c:catAx>"
            f'<c:valAx><c:axId val="2"/><c:txPr><a:p><a:pPr><a:defRPr sz="{value_size}"/>'
            "</a:pPr></a:p></c:txPr></c:valAx>"
        )

    svg = _svg(
        '<c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/>'
        + _series(0, [1, 2])
        + "</c:barChart>"
        + axes(1800)
    )

    assert float(next(v for v in re.findall(r'font-size="([\d.]+)"[^>]*>C0</text>', svg))) == 12.0
    assert float(next(v for v in re.findall(r'font-size="([\d.]+)"[^>]*>1</text>', svg))) == 24.0


def _line(series_extra: str, *, count: int = 3) -> str:
    return _svg(
        '<c:lineChart><c:grouping val="standard"/>'
        + _series(0, [1, 3, 2][:count]).replace("</c:ser>", series_extra + "</c:ser>")
        + "</c:lineChart>"
    )


def test_line_series_are_smoothed_unless_smooth_is_off() -> None:
    assert " C" in _line("")
    assert " C" in _line('<c:smooth val="1"/>')
    assert " C" not in _line('<c:smooth val="0"/>')


def test_line_markers_follow_symbol_size_and_colour() -> None:
    marker = (
        '<c:marker><c:symbol val="square"/><c:size val="12"/>'
        '<c:spPr><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></c:spPr></c:marker>'
    )
    svg = _line(marker)

    assert svg.count("<rect x") >= 3 and 'fill="#FF0000"' in svg
    assert 'width="16.0"' in svg  # 12 pt
    assert "<circle" not in _line('<c:marker><c:symbol val="none"/></c:marker>')
    assert "<polygon" in _line("")  # automatic markers start with a diamond


def test_line_width_and_dash_come_from_the_series_outline() -> None:
    styled = _line('<c:spPr><a:ln w="38100"><a:prstDash val="sysDash"/></a:ln></c:spPr>')
    plain = _line("")

    assert 'stroke-width="4"' in styled and 'stroke-dasharray="12.0 4.0"' in styled
    assert "stroke-dasharray" not in plain and 'stroke-width="1.5"' in plain


def test_a_line_chart_level_smooth_off_straightens_series_that_do_not_say() -> None:
    def chart(chart_level: str, series_level: str) -> str:
        return _svg(
            '<c:lineChart><c:grouping val="standard"/>'
            + _series(0, [1, 3, 2]).replace("</c:ser>", series_level + "</c:ser>")
            + chart_level
            + "</c:lineChart>"
        )

    assert " C" not in chart('<c:smooth val="0"/>', "")
    assert " C" in chart('<c:smooth val="0"/>', '<c:smooth val="1"/>')  # the series wins


def test_a_bare_smooth_element_means_smooth_and_scatter_lines_take_series_style() -> None:
    bare = _svg(
        '<c:lineChart><c:grouping val="standard"/><c:smooth val="0"/>'
        + _series(0, [1, 3, 2]).replace("</c:ser>", "<c:smooth/></c:ser>")
        + "</c:lineChart>"
    )
    scatter = _svg(
        '<c:scatterChart><c:scatterStyle val="lineMarker"/><c:ser><c:idx val="0"/>'
        '<c:spPr><a:ln w="38100"><a:prstDash val="dash"/></a:ln></c:spPr>'
        '<c:marker><c:symbol val="none"/></c:marker>'
        + _literal("xVal", [1, 2, 3])
        + _literal("yVal", [5, 9, 4])
        + "</c:ser></c:scatterChart>"
    )

    assert " C" in bare
    assert 'stroke-width="4"' in scatter and "stroke-dasharray" in scatter
    assert "<polygon" not in scatter and "<circle" not in scatter  # symbol none draws no marker


def test_axes_draw_a_black_line_with_outward_tick_marks_unless_styled_away() -> None:
    def chart(cat: str, val: str) -> str:
        return _svg(
            _BAR
            + f'<c:catAx><c:axId val="1"/>{cat}</c:catAx>'
            + f'<c:valAx><c:axId val="2"/>{val}</c:valAx>'
        )

    def lines(svg: str) -> list[tuple[float, float, float, float]]:
        return [
            (float(a), float(b), float(c), float(d))
            for a, b, c, d in re.findall(
                r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" stroke="#000000"',
                svg,
            )
        ]

    out = '<c:majorTickMark val="out"/>'
    drawn = lines(chart(out, out))
    plain = lines(chart('<c:majorTickMark val="none"/>', '<c:majorTickMark val="none"/>'))
    gone = lines(chart("<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>", '<c:delete val="1"/>'))

    assert len(plain) == 2  # a category axis line and a value axis line, no ticks
    assert len(drawn) > len(plain) + 3  # tick marks between the 3 categories and on the values
    assert not gone
    short_verticals = [ln for ln in drawn if ln[0] == ln[2] and ln[3] - ln[1] <= 5]
    assert len(short_verticals) == 4 and all(ln[3] - ln[1] == 4.0 for ln in short_verticals)  # down


def test_a_horizontal_category_axis_sits_at_zero_when_values_are_negative() -> None:
    svg = _svg(
        '<c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/>'
        + _series(0, [-2, 3])
        + "</c:barChart>"
        + '<c:catAx><c:axId val="1"/><c:delete val="0"/><c:majorTickMark val="none"/></c:catAx>'
    )
    axis = re.search(r'<line x1="([\d.]+)" y1="[\d.]+" x2="\1" y2="[\d.]+" stroke="#000000"', svg)
    bars = [float(x) for x in re.findall(r'<rect x="([\d.]+)"', svg)]

    assert axis is not None
    assert abs(float(axis.group(1)) - max(bars)) < 1.0 or any(
        abs(float(axis.group(1)) - b) < 1.0 for b in bars
    )  # on a bar's origin, not at the minimum of the scale
    assert float(axis.group(1)) > min(bars) + 5


def _value_labels(grouping: str, height_px: float) -> list[str]:
    svg = chart_to_svg(
        _chart(
            '<c:barChart><c:barDir val="col"/><c:grouping val="'
            + grouping
            + '"/>'
            + _series(0, [120, 135, 148, 162])
            + "</c:barChart>"
        ),
        width_px=480,
        height_px=height_px,
    )
    assert svg is not None
    return re.findall(r'text-anchor="end"[^>]*>([\d%]+)</text>', svg)


def test_value_axis_steps_follow_the_label_height_and_are_coarser_for_percent() -> None:
    assert _value_labels("clustered", 220) == [str(v) for v in range(0, 181, 20)]
    assert _value_labels("percentStacked", 300) == [f"{v}%" for v in range(0, 101, 20)]


def test_a_deleted_horizontal_value_axis_draws_no_tick_labels() -> None:
    def labels(delete: str) -> list[str]:
        svg = _svg(
            '<c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/>'
            + _series(0, [1, 2, 3])
            + "</c:barChart>"
            + f'<c:valAx><c:axId val="2"/><c:delete val="{delete}"/></c:valAx>'
        )
        return re.findall(r'text-anchor="middle"[^>]*>(\d+)</text>', svg)

    assert labels("0") and not labels("1")


def test_a_line_legend_key_shows_the_series_marker_and_dash_and_hollow_markers_are_outlines() -> (
    None
):
    marker = (
        '<c:marker><c:symbol val="circle"/><c:size val="9"/><c:spPr><a:noFill/></c:spPr></c:marker>'
    )
    outline = '<c:spPr><a:ln w="28575"><a:prstDash val="dash"/></a:ln></c:spPr>'
    series = _series(0, [3, 5]).replace("</c:ser>", outline + marker + "</c:ser>")
    legend = '<c:legend><c:legendPos val="r"/></c:legend>'

    svg = _svg('<c:lineChart><c:grouping val="standard"/>' + series + "</c:lineChart>", legend)

    assert svg.count('fill="none" stroke="#4472C4" stroke-width="1.5"') >= 3  # 2 points + the key
    assert svg.count("stroke-dasharray") >= 2  # the plotted line and the legend's short line
