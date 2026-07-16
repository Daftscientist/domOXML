"""Unit tests for IR parsing + extraction (no browser)."""

from __future__ import annotations

from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import (
    AutoNumberBullet,
    CharBullet,
    LineSpacing,
    Rgba,
    SolidFill,
    TableNode,
)
from domoxml.core.ir.parse import (
    autonum_to_css_list_style,
    bu_char_to_css_list_style,
    css_list_style_to_autonum,
    css_list_style_to_bu_char,
    is_bold,
    parse_color,
    parse_length_px,
    parse_line_height,
    parse_margin_pt,
    parse_radius_px,
)
from domoxml.core.render.browser import RenderedNode, RenderedSlide
from domoxml.core.units import px_to_emu


def test_parse_color_rgb_and_rgba() -> None:
    assert parse_color("rgb(255, 0, 0)") == Rgba(r=255, g=0, b=0, a=1.0)
    assert parse_color("rgba(0, 128, 255, 0.5)") == Rgba(r=0, g=128, b=255, a=0.5)
    assert parse_color("transparent") is None
    assert parse_color(None) is None


def test_color_hex() -> None:
    color = parse_color("rgb(79, 70, 229)")
    assert color is not None and color.hex == "4F46E5"


def test_parse_length_takes_first_px() -> None:
    assert parse_length_px("8px") == 8.0
    assert parse_length_px("12px 4px 4px 12px") == 12.0
    assert parse_length_px("") == 0.0


def test_parse_radius_resolves_percentage_against_shorter_side() -> None:
    assert parse_radius_px("50%", shorter_side_px=200) == 100
    assert parse_radius_px("16px", shorter_side_px=200) == 16


def test_is_bold() -> None:
    assert is_bold("700")
    assert is_bold("bold")
    assert is_bold("bolder")
    assert not is_bold("400")
    assert not is_bold("normal")
    assert not is_bold(None)


def test_extract_builds_table_node_from_html_table() -> None:
    # Regression: a <table> subtree must become a native TableNode in slide.nodes, not fall
    # through to shape extraction. Build a 2-row, 2-col table (the header cell spans 2).
    table = RenderedNode(tag="table", x=0, y=0, width=400, height=200, index=0, parent=-1)
    tr1 = RenderedNode(tag="tr", x=0, y=0, width=400, height=100, index=1, parent=0)
    th1 = RenderedNode(
        tag="th",
        x=0,
        y=0,
        width=400,
        height=100,
        text="Header",
        index=2,
        parent=1,
        styles={"domoxmlColSpan": "2", "domoxmlRowSpan": "1"},
    )
    tr2 = RenderedNode(tag="tr", x=0, y=100, width=400, height=100, index=3, parent=0)
    td1 = RenderedNode(
        tag="td",
        x=0,
        y=100,
        width=200,
        height=100,
        text="A",
        index=4,
        parent=3,
        styles={"domoxmlColSpan": "1", "domoxmlRowSpan": "1"},
    )
    td2 = RenderedNode(
        tag="td",
        x=200,
        y=100,
        width=200,
        height=100,
        text="B",
        index=5,
        parent=3,
        styles={"domoxmlColSpan": "1", "domoxmlRowSpan": "1"},
    )
    rendered = RenderedSlide(
        png=b"x", width=1280, height=720, nodes=(table, tr1, th1, tr2, td1, td2)
    )
    ir = extract_slide(rendered).slide
    tables = [n for n in ir.nodes if isinstance(n, TableNode)]
    assert len(tables) == 1
    tbl = tables[0]
    assert len(tbl.rows) == 2
    assert tbl.rows[0].cells[0].col_span == 2  # header spans both columns
    assert tbl.rows[1].cells[0].text is not None
    # The table is not also emitted as shapes (subtree consumed).
    assert ir.shapes == ()


def test_extract_recovers_normalized_html_identity_and_provenance() -> None:
    node = RenderedNode(
        tag="div",
        x=10,
        y=20,
        width=200,
        height=80,
        index=1,
        styles={
            "backgroundColor": "rgb(10, 20, 30)",
            "domoxmlNodeId": "hero-title",
            "domoxmlSourceFormat": "pptx",
            "domoxmlSourceId": "7",
            "domoxmlSourcePart": "ppt/slides/slide1.xml",
        },
    )

    [shape] = extract_slide(
        RenderedSlide(png=b"x", width=1280, height=720, nodes=(node,))
    ).slide.contents

    assert shape.node_id == "hero-title"
    assert shape.provenance is not None
    assert shape.provenance.source_format == "pptx"
    assert shape.provenance.source_id == "7"
    assert shape.provenance.source_part == "ppt/slides/slide1.xml"


def test_extract_decomposed_borders_keep_source_owner_and_roles() -> None:
    node = RenderedNode(
        tag="div",
        x=10,
        y=20,
        width=200,
        height=80,
        index=3,
        styles={
            "backgroundColor": "rgb(255, 255, 255)",
            "borderTopWidth": "2px",
            "borderTopStyle": "solid",
            "borderTopColor": "rgb(255, 0, 0)",
            "borderRightWidth": "3px",
            "borderRightStyle": "solid",
            "borderRightColor": "rgb(0, 255, 0)",
            "borderBottomWidth": "4px",
            "borderBottomStyle": "solid",
            "borderBottomColor": "rgb(0, 0, 255)",
            "borderLeftWidth": "5px",
            "borderLeftStyle": "solid",
            "borderLeftColor": "rgb(0, 0, 0)",
        },
    )

    contents = extract_slide(
        RenderedSlide(png=b"x", width=1280, height=720, nodes=(node,))
    ).slide.contents

    layers = [item for item in contents if item.provenance and item.provenance.role]
    assert {item.provenance.role for item in layers if item.provenance is not None} == {
        "border-top",
        "border-right",
        "border-bottom",
        "border-left",
    }
    assert all(
        item.provenance is not None and item.provenance.owner_node_id == "html-auto-3"
        for item in layers
    )
    assert contents[-1].node_id == "html-auto-3"


def test_extract_reserves_explicit_ids_before_allocating_automatic_ids() -> None:
    automatic = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=100,
        height=50,
        index=9,
        styles={"backgroundColor": "rgb(1, 2, 3)"},
    )
    explicit = RenderedNode(
        tag="div",
        x=120,
        y=0,
        width=100,
        height=50,
        index=10,
        styles={
            "backgroundColor": "rgb(4, 5, 6)",
            "domoxmlNodeId": "html-auto-9",
        },
    )

    contents = extract_slide(
        RenderedSlide(png=b"x", width=300, height=100, nodes=(automatic, explicit))
    ).slide.contents

    assert [node.node_id for node in contents] == ["html-auto-9-2", "html-auto-9"]


def test_extract_normalizes_logical_text_align() -> None:
    node = RenderedNode(
        tag="p", x=0, y=0, width=10, height=10, text="x", styles={"textAlign": "start"}
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=100, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    assert ir.shapes[0].text.paragraphs[0].align == "left"  # 'start' → 'left'


def test_extract_infers_center_alignment_from_row_flex() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=100,
        height=50,
        text="Centered",
        styles={
            "display": "flex",
            "flexDirection": "row",
            "justifyContent": "center",
            "alignItems": "center",
            "textAlign": "start",
        },
    )

    ir = extract_slide(RenderedSlide(png=b"x", width=100, height=50, nodes=(node,))).slide

    assert ir.shapes[0].text is not None
    assert ir.shapes[0].text.paragraphs[0].align == "center"
    assert ir.shapes[0].text.anchor == "middle"


def test_explicit_text_align_overrides_flex_positioning() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=100,
        height=50,
        text="Left",
        styles={"display": "flex", "justifyContent": "center", "textAlign": "left"},
    )

    ir = extract_slide(RenderedSlide(png=b"x", width=100, height=50, nodes=(node,))).slide

    assert ir.shapes[0].text is not None
    assert ir.shapes[0].text.paragraphs[0].align == "left"


def test_extract_maps_box_fill_and_text() -> None:
    node = RenderedNode(
        tag="div",
        x=96,  # 1in -> 914400 EMU
        y=0,
        width=192,  # 2in
        height=96,
        text="Hello",
        styles={
            "backgroundColor": "rgb(79, 70, 229)",
            "color": "rgb(255, 255, 255)",
            "fontSize": "24px",
            "fontWeight": "700",
            "fontFamily": "'Inter', sans-serif",
            "borderRadius": "8px",
            "textAlign": "center",
            "opacity": "1",
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=1280, height=720, nodes=(node,))).slide

    assert ir.width == 12_192_000  # 1280px -> EMU
    shape = ir.shapes[0]
    assert shape.box.x == 914_400 and shape.box.width == 1_828_800
    assert isinstance(shape.fill, SolidFill) and shape.fill.color.hex == "4F46E5"
    assert shape.corner_radius_emu == 76_200  # 8px
    assert shape.text is not None
    paragraph = shape.text.paragraphs[0]
    [run] = paragraph.runs
    assert run.text == "Hello"
    assert run.size_pt == 18.0  # 24px -> 18pt
    assert run.bold is True
    assert run.font_family == "Inter"
    assert paragraph.align == "center"


def test_transparent_background_is_no_fill() -> None:
    node = RenderedNode(
        tag="span", x=0, y=0, width=10, height=10, styles={"backgroundColor": "rgba(0, 0, 0, 0)"}
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=100, height=100, nodes=(node,))).slide
    assert ir.shapes[0].fill is None


# --------------------------------------------------------------------------- parse_line_height


def test_parse_line_height_normal_returns_none() -> None:
    assert parse_line_height("normal") is None
    assert parse_line_height(None) is None
    assert parse_line_height("") is None


def test_parse_line_height_unitless_factor() -> None:
    ls = parse_line_height("1.6")
    assert ls is not None
    assert ls.percent == 1.6
    assert ls.points is None


def test_parse_line_height_percent() -> None:
    ls = parse_line_height("150%")
    assert ls is not None
    assert ls.percent == 1.5


def test_parse_line_height_px() -> None:
    # 24px = 24 * 72/96 = 18 pt
    ls = parse_line_height("24px")
    assert ls is not None
    assert ls.points is not None
    assert abs(ls.points - 18.0) < 0.01


# --------------------------------------------------------------------------- parse_margin_pt


def test_parse_margin_pt_from_px() -> None:
    # 24px = 18pt
    assert abs(parse_margin_pt("24px") - 18.0) < 0.01


def test_parse_margin_pt_zero_returns_zero() -> None:
    assert parse_margin_pt("0px") == 0.0
    assert parse_margin_pt("") == 0.0


# --------------------------------------------------------------------------- list style mappings


def test_css_list_style_to_bu_char_disc() -> None:
    assert css_list_style_to_bu_char("disc") == "•"
    assert css_list_style_to_bu_char("circle") == "○"
    assert css_list_style_to_bu_char("square") == "▪"
    assert css_list_style_to_bu_char("unknown") == "•"  # default


def test_css_list_style_to_autonum_ordered() -> None:
    assert css_list_style_to_autonum("decimal") == "arabicPeriod"
    assert css_list_style_to_autonum("lower-alpha") == "alphaLcPeriod"
    assert css_list_style_to_autonum("upper-roman") == "romanUcPeriod"
    assert css_list_style_to_autonum("disc") is None  # unordered → no autonum


def test_bu_char_to_css_list_style_round_trip() -> None:
    assert bu_char_to_css_list_style("•") == "disc"
    assert bu_char_to_css_list_style("○") == "circle"
    assert bu_char_to_css_list_style("▪") == "square"
    assert bu_char_to_css_list_style("X") == "X"  # unknown char → itself


def test_autonum_to_css_list_style_round_trip() -> None:
    assert autonum_to_css_list_style("arabicPeriod") == "decimal"
    assert autonum_to_css_list_style("alphaLcPeriod") == "lower-alpha"
    assert autonum_to_css_list_style("romanLcPeriod") == "lower-roman"
    assert autonum_to_css_list_style("unknown") == "decimal"  # default


# --------------------------------------------------------------------------- extract li bullets


def test_extract_li_char_bullet() -> None:
    """An <li> node in a ul gets a CharBullet with the correct char."""
    node = RenderedNode(
        tag="li",
        x=0,
        y=0,
        width=100,
        height=20,
        text="item",
        styles={
            "color": "rgb(0,0,0)",
            "fontSize": "12px",
            "fontFamily": "sans-serif",
            "domoxmlListDepth": "1",
            "domoxmlListType": "disc",
            "listStyleType": "disc",
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=200, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    para = ir.shapes[0].text.paragraphs[0]
    assert para.level == 0
    assert isinstance(para.bullet, CharBullet)
    assert para.bullet.char == "•"
    assert para.left_margin_pt == 13.5
    assert para.indent_pt == -12.75
    assert ir.shapes[0].box.x == -px_to_emu(18)


def test_extract_li_autonum_bullet() -> None:
    """An <li> node in an ol gets an AutoNumberBullet."""
    node = RenderedNode(
        tag="li",
        x=0,
        y=0,
        width=100,
        height=20,
        text="item",
        styles={
            "color": "rgb(0,0,0)",
            "fontSize": "12px",
            "fontFamily": "sans-serif",
            "domoxmlListDepth": "1",
            "domoxmlListType": "decimal",
            "domoxmlListOrdinal": "3",
            "listStyleType": "decimal",
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=200, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    para = ir.shapes[0].text.paragraphs[0]
    assert isinstance(para.bullet, AutoNumberBullet)
    assert para.bullet.scheme == "arabicPeriod"
    assert para.bullet.start_at == 3


def test_extract_li_nested_level() -> None:
    """Nested <li> at depth 2 gets level=1."""
    node = RenderedNode(
        tag="li",
        x=0,
        y=0,
        width=100,
        height=20,
        text="nested",
        styles={
            "color": "rgb(0,0,0)",
            "fontSize": "12px",
            "fontFamily": "sans-serif",
            "domoxmlListDepth": "2",
            "domoxmlListType": "disc",
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=200, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    assert ir.shapes[0].text.paragraphs[0].level == 1


def test_extract_paragraph_spacing() -> None:
    """margin-top/bottom → space_before_pt/space_after_pt."""
    node = RenderedNode(
        tag="p",
        x=0,
        y=0,
        width=100,
        height=20,
        text="text",
        styles={
            "color": "rgb(0,0,0)",
            "fontSize": "12px",
            "fontFamily": "sans-serif",
            "marginTop": "12px",  # 9pt
            "marginBottom": "24px",  # 18pt
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=200, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    para = ir.shapes[0].text.paragraphs[0]
    assert para.space_before_pt is not None and abs(para.space_before_pt - 9.0) < 0.1
    assert para.space_after_pt is not None and abs(para.space_after_pt - 18.0) < 0.1


def test_extract_line_height_unitless() -> None:
    """line-height:1.6 (non-normal) → LineSpacing(percent=1.6)."""
    node = RenderedNode(
        tag="p",
        x=0,
        y=0,
        width=100,
        height=20,
        text="text",
        styles={
            "color": "rgb(0,0,0)",
            "fontSize": "12px",
            "fontFamily": "sans-serif",
            "lineHeight": "1.6",
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=200, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    ls = ir.shapes[0].text.paragraphs[0].line_spacing
    assert ls is not None
    assert isinstance(ls, LineSpacing) and ls.percent == 1.6
