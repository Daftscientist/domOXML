# pyright: basic, reportArgumentType=false
# python-pptx is only partly typed; ruff still applies.
"""The chart renderer: each modelled chart type draws, and the rest decline."""

from __future__ import annotations

from io import BytesIO

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
            "fill-opacity",
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
    assert "<circle" in scatter


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
        return f'<c:valAx><c:axId val="1"/>{grid}<c:delete val="0"/></c:valAx>'

    visible = "<c:majorGridlines><c:spPr><a:ln><a:solidFill/></a:ln></c:spPr></c:majorGridlines>"
    hidden = "<c:majorGridlines><c:spPr><a:ln><a:noFill/></a:ln></c:spPr></c:majorGridlines>"

    assert "#D9D9D9" in _svg(_BAR + axis(visible))
    assert "#D9D9D9" not in _svg(_BAR + axis(hidden))
    assert "#D9D9D9" not in _svg(_BAR + axis(""))


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
