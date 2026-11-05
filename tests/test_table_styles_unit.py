"""PowerPoint's built-in table styles resolve to fills, text colours and borders per cell."""

from __future__ import annotations

import pytest

from domoxml.slides.table_styles import is_builtin, resolve_cell_style

_THEME = {
    "dk1": "000000",
    "lt1": "FFFFFF",
    "dk2": "08284F",
    "lt2": "F9FCFF",
    "accent1": "175CD4",
    "accent2": "0B3668",
}
_FLAGS = {"firstRow": True, "bandRow": True}
_MEDIUM2_NEUTRAL = "{073A0DAA-6AF3-43AB-8588-CEC1D06C72B9}"
_MEDIUM2_ACCENT1 = "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"
_DARK1_NEUTRAL = "{E8034E78-7F5D-4C2E-B375-FC64B27BC917}"


def _cell(style: str, row: int, column: int = 1, flags: dict[str, bool] | None = None):  # type: ignore[no-untyped-def]
    return resolve_cell_style(
        style,
        row=row,
        column=column,
        rows=5,
        columns=4,
        flags=_FLAGS if flags is None else flags,
        colors=_THEME,
    )


def test_an_unknown_style_id_is_not_a_built_in() -> None:
    assert not is_builtin("{00000000-0000-0000-0000-000000000000}")
    assert (
        resolve_cell_style(
            "{00000000-0000-0000-0000-000000000000}",
            row=0,
            column=0,
            rows=2,
            columns=2,
            flags={},
            colors=_THEME,
        )
        is None
    )


def test_medium_style_2_neutral_draws_the_measured_greys_black_header_and_white_grout() -> None:
    header, band, plain = (
        _cell(_MEDIUM2_NEUTRAL, 0),
        _cell(_MEDIUM2_NEUTRAL, 1),
        _cell(_MEDIUM2_NEUTRAL, 2),
    )

    assert header is not None and band is not None and plain is not None
    assert header.fill is not None and header.fill.hex == "000000" and header.bold
    assert header.text is not None and header.text.hex == "FFFFFF"
    assert band.fill is not None and band.fill.hex == "CBCBCB"  # real PowerPoint's band
    assert plain.fill is not None and plain.fill.hex == "E7E7E7"  # and its body
    assert band.borders is not None and band.borders.top is not None
    assert band.borders.top.color.hex == "FFFFFF"


def test_the_default_accent_style_uses_the_themes_first_accent_for_its_header() -> None:
    header = _cell(_MEDIUM2_ACCENT1, 0)

    assert header is not None and header.fill is not None and header.fill.hex == "175CD4"


def test_dark_style_1_draws_white_text_on_its_pale_body() -> None:
    body = _cell(_DARK1_NEUTRAL, 2)

    assert body is not None and body.text is not None and body.text.hex == "FFFFFF"


@pytest.mark.parametrize(
    ("flags", "row", "bold"),
    [({"firstRow": True}, 0, True), ({"firstRow": True}, 1, False), ({}, 0, False)],
)
def test_only_the_cells_in_an_enabled_region_are_bold(
    flags: dict[str, bool], row: int, bold: bool
) -> None:
    cell = _cell(_MEDIUM2_NEUTRAL, row, flags=flags)

    assert cell is not None and cell.bold is bold


def test_banding_alternates_body_rows_and_the_last_row_region_needs_its_flag() -> None:
    first, second = _cell(_MEDIUM2_NEUTRAL, 1), _cell(_MEDIUM2_NEUTRAL, 2)
    total_off = _cell(_MEDIUM2_NEUTRAL, 4)
    total_on = _cell(_MEDIUM2_NEUTRAL, 4, flags={**_FLAGS, "lastRow": True})

    assert first is not None and second is not None and first.fill != second.fill
    assert total_off is not None and total_off.bold is False
    assert total_on is not None and total_on.bold and total_on.fill is not None
    assert total_on.fill.hex == "000000"


def test_a_regions_own_boundary_line_applies_wherever_the_region_sits() -> None:
    header = _cell(_DARK1_NEUTRAL, 0)  # Dark Style 1 draws a white line under the header
    total = _cell(_DARK1_NEUTRAL, 4, flags={**_FLAGS, "lastRow": True})

    assert header is not None and header.borders is not None and header.borders.bottom is not None
    assert header.borders.bottom.color.hex == "FFFFFF"
    assert total is not None and total.borders is not None and total.borders.top is not None
    assert total.borders.top.color.hex == "FFFFFF"


def test_a_cell_merged_into_its_neighbour_does_not_shift_the_columns_after_it() -> None:
    import io
    import zipfile

    from domoxml.core.ir.model import (
        Box,
        SlideIR,
        SolidFill,
        TableCell,
        TableNode,
        TableRow,
    )
    from domoxml.slides.pptx import build_pptx
    from domoxml.slides.read import read_pptx_result

    px = 9525
    table = TableNode(
        box=Box(x=0, y=0, width=400 * px, height=100 * px),
        col_widths_emu=(100 * px,) * 4,
        rows=(
            TableRow(height_emu=50 * px, cells=(TableCell(col_span=2), TableCell(), TableCell())),
            TableRow(height_emu=50 * px, cells=(TableCell(),) * 4),
        ),
        style_id=_MEDIUM2_NEUTRAL,
        last_col=True,
    )
    source = build_pptx([SlideIR(width=1280 * px, height=720 * px, contents=(table,))], faces=[])
    # The writer says "no fill" for a cell without one, which would hide the style: drop it.
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = data.replace(b"<a:noFill/>", b"")
            zout.writestr(item, data)

    [back] = read_pptx_result(patched.getvalue()).slides[0].contents

    assert isinstance(back, TableNode)
    last = back.rows[0].cells[-1]
    assert (
        isinstance(last.fill, SolidFill) and last.fill.color.hex == "000000"
    )  # last-column region


def test_medium_style_2_draws_its_header_and_total_row_lines_at_three_points() -> None:
    header = _cell(_MEDIUM2_NEUTRAL, 0)
    total = _cell(_MEDIUM2_NEUTRAL, 4, flags={**_FLAGS, "lastRow": True})

    assert header is not None and header.borders is not None and header.borders.bottom is not None
    assert header.borders.bottom.width_emu == 38_100
    assert total is not None and total.borders is not None and total.borders.top is not None
    assert total.borders.top.width_emu == 38_100


def test_a_merged_cell_that_reaches_the_last_column_or_row_is_in_those_regions() -> None:
    wide = resolve_cell_style(
        _MEDIUM2_NEUTRAL,
        row=1,
        column=2,
        rows=5,
        columns=4,
        flags={"lastCol": True},
        colors=_THEME,
        column_span=2,
    )
    short = resolve_cell_style(
        _MEDIUM2_NEUTRAL,
        row=3,
        column=1,
        rows=5,
        columns=4,
        flags={"lastRow": True},
        colors=_THEME,
        row_span=2,
    )

    assert wide is not None and wide.bold  # spans columns 2 and 3 of 4
    assert short is not None and short.bold  # spans rows 3 and 4 of 5


def test_themed_style_2_bands_are_a_light_tint_of_the_accent_not_opaque_white() -> None:
    themed2_accent1 = "{D113A9D2-9D6B-4929-AA2D-F23B5EE8CBE7}"
    band = _cell(themed2_accent1, 1)

    assert band is not None and band.fill is not None
    assert band.fill.hex != "FFFFFF" and band.fill.b > band.fill.r  # a pale blue
