"""Direct contracts for feature-specific rendered-HTML extraction handlers."""

from __future__ import annotations

from domoxml.core.ir.model import Rgba, SolidFill, TextBody, TextParagraph, TextRun
from domoxml.core.ir.slide_properties_extract import (
    extract_slide_properties,
    extract_transition,
)
from domoxml.core.ir.svg_extract import extract_custom_geometry
from domoxml.core.ir.table_extract import extract_table
from domoxml.core.render.browser import RenderedNode


def test_slide_properties_find_opted_in_root_and_resolve_background() -> None:
    body = RenderedNode(tag="body", x=0, y=0, width=100, height=100, index=0, parent=-1)
    root = RenderedNode(
        tag="section",
        x=0,
        y=0,
        width=100,
        height=100,
        index=1,
        parent=0,
        styles={
            "domoxmlTransition": "push",
            "domoxmlTransitionDuration": "300",
            "domoxmlTransitionDirection": "l",
        },
    )
    fill = SolidFill(color=Rgba(r=1, g=2, b=3))

    found, transition, background = extract_slide_properties(
        (body, root), lambda _node: (fill, None)
    )

    assert found is root
    assert transition is not None
    assert (transition.type, transition.duration_ms, transition.direction) == ("push", 300, "l")
    assert background is not None and background.fill == fill


def test_invalid_transition_values_fall_back_without_raising() -> None:
    transition = extract_transition(
        {
            "domoxmlTransition": "unknown",
            "domoxmlTransitionDuration": "not-a-number",
            "domoxmlTransitionDirection": "sideways",
        }
    )

    assert transition is not None
    assert (transition.type, transition.duration_ms, transition.direction) == ("fade", None, None)


def test_table_handler_builds_grid_through_resolver_contracts() -> None:
    table = RenderedNode(tag="table", x=0, y=0, width=200, height=50, index=0, parent=-1)
    row = RenderedNode(tag="tr", x=0, y=0, width=200, height=50, index=1, parent=0)
    cell = RenderedNode(
        tag="td",
        x=0,
        y=0,
        width=200,
        height=50,
        index=2,
        parent=1,
        styles={"domoxmlColSpan": "2", "domoxmlRowSpan": "1", "paddingLeft": "4px"},
    )

    extracted = extract_table(
        table,
        (table, row, cell),
        {0: [1], 1: [2]},
        fill_for=lambda _node: None,
        borders_for=lambda _styles: ((None, None, None, None), []),
        text_for=lambda _node: None,
    )

    assert extracted is not None
    assert extracted.col_widths_emu == (952_500, 952_500)
    assert extracted.rows[0].cells[0].col_span == 2
    assert extracted.rows[0].cells[0].margins[0] == 38_100


def test_table_handler_recovers_text_from_nested_reverse_html_body() -> None:
    table = RenderedNode(tag="table", x=0, y=0, width=100, height=20, index=0, parent=-1)
    row = RenderedNode(tag="tr", x=0, y=0, width=100, height=20, index=1, parent=0)
    cell = RenderedNode(tag="td", x=0, y=0, width=100, height=20, index=2, parent=1)
    text_container = RenderedNode(tag="div", x=0, y=0, width=100, height=20, index=3, parent=2)
    body = TextBody(
        paragraphs=(
            TextParagraph(runs=(TextRun(text="Nested cell", font_family="Arial", size_pt=12),)),
        )
    )

    extracted = extract_table(
        table,
        (table, row, cell, text_container),
        {0: [1], 1: [2], 2: [3]},
        fill_for=lambda _node: None,
        borders_for=lambda _styles: ((None, None, None, None), []),
        text_for=lambda node: body if node is text_container else None,
    )

    assert extracted is not None
    assert extracted.rows[0].cells[0].text == body


def test_table_handler_uses_row_fill_behind_transparent_cells() -> None:
    table = RenderedNode(tag="table", x=0, y=0, width=100, height=20, index=0, parent=-1)
    row = RenderedNode(tag="tr", x=0, y=0, width=100, height=20, index=1, parent=0)
    cell = RenderedNode(tag="th", x=0, y=0, width=100, height=20, index=2, parent=1)
    row_fill = SolidFill(color=Rgba(r=68, g=114, b=196))

    extracted = extract_table(
        table,
        (table, row, cell),
        {0: [1], 1: [2]},
        fill_for=lambda node: row_fill if node is row else None,
        borders_for=lambda _styles: ((None, None, None, None), []),
        text_for=lambda _node: None,
    )

    assert extracted is not None
    assert extracted.rows[0].cells[0].fill == row_fill


def test_table_handler_prefers_explicit_cell_fill_over_row_fill() -> None:
    table = RenderedNode(tag="table", x=0, y=0, width=100, height=20, index=0, parent=-1)
    row = RenderedNode(tag="tr", x=0, y=0, width=100, height=20, index=1, parent=0)
    cell = RenderedNode(tag="td", x=0, y=0, width=100, height=20, index=2, parent=1)
    row_fill = SolidFill(color=Rgba(r=1, g=2, b=3))
    cell_fill = SolidFill(color=Rgba(r=4, g=5, b=6))

    extracted = extract_table(
        table,
        (table, row, cell),
        {0: [1], 1: [2]},
        fill_for=lambda node: cell_fill if node is cell else row_fill,
        borders_for=lambda _styles: ((None, None, None, None), []),
        text_for=lambda _node: None,
    )

    assert extracted is not None
    assert extracted.rows[0].cells[0].fill == cell_fill


def test_svg_handler_returns_geometry_and_path_style_owner() -> None:
    svg = RenderedNode(
        tag="svg", x=0, y=0, width=100, height=50, src="0 0 100 50", index=0, parent=-1
    )
    path = RenderedNode(
        tag="path", x=0, y=0, width=100, height=50, src="M 0 0 L 100 50 Z", index=1, parent=0
    )

    extracted = extract_custom_geometry(svg, (svg, path), {0: [1]})

    assert extracted.geometry is not None
    assert extracted.style_node is path
    assert len(extracted.geometry.path) == 3
    assert extracted.warning is None
