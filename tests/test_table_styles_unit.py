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
