"""Unit tests for text body properties: anchor, autofit, columns — fwd + rev."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

from domoxml.core.drawingml.shape import shape_xml
from domoxml.core.html import serialize_canvas
from domoxml.core.ir.extract import _detect_anchor, _detect_autofit, _detect_columns
from domoxml.core.ir.model import (
    Box,
    ShapeNode,
    SlideIR,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.slides import build_pptx
from domoxml.slides.read import read_pptx

# --------------------------------------------------------------------------- helpers


def _simple_body(
    anchor: str = "top",
    autofit: str = "normal",
    columns: int = 1,
    column_gap_emu: int = 0,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> TextBody:
    return TextBody(
        paragraphs=(
            TextParagraph(
                runs=(TextRun(text="hello", font_family="sans-serif", size_pt=12),),
            ),
        ),
        anchor=anchor,  # type: ignore[arg-type]
        autofit=autofit,  # type: ignore[arg-type]
        columns=columns,
        column_gap_emu=column_gap_emu,
        margins=margins,
    )


def _shape(body: TextBody) -> ShapeNode:
    return ShapeNode(box=Box(x=0, y=0, width=3_000_000, height=1_000_000), text=body)


def _xml(body: TextBody) -> str:
    return shape_xml(_shape(body), shape_id=1)


def _slide_ir(body: TextBody) -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(_shape(body),),
    )


def _roundtrip_body(body: TextBody) -> TextBody:
    """Forward IR → PPTX → reverse reader → IR round trip."""
    [slide] = read_pptx(build_pptx([_slide_ir(body)], faces=[]))
    assert slide.shapes[0].text is not None
    return slide.shapes[0].text


def _html_for(body: TextBody) -> str:
    """Serialize IR → HTML."""
    pres = serialize_canvas([_slide_ir(body)])
    return pres.slides[0].html


# --------------------------------------------------------------------------- detection from styles


def test_detect_anchor_default_top() -> None:
    """No flex → anchor top."""
    assert _detect_anchor({}) == "top"
    assert _detect_anchor({"display": "block"}) == "top"


def test_detect_anchor_flex_column_justify_center() -> None:
    """display:flex + flex-direction:column + justify-content:center → middle."""
    styles = {"display": "flex", "flexDirection": "column", "justifyContent": "center"}
    assert _detect_anchor(styles) == "middle"


def test_detect_anchor_flex_column_justify_end() -> None:
    """display:flex + flex-direction:column + justify-content:flex-end → bottom."""
    styles = {"display": "flex", "flexDirection": "column", "justifyContent": "flex-end"}
    assert _detect_anchor(styles) == "bottom"


def test_detect_anchor_flex_row_align_center() -> None:
    """display:flex + align-items:center (row, default direction) → middle."""
    styles = {"display": "flex", "flexDirection": "row", "alignItems": "center"}
    assert _detect_anchor(styles) == "middle"


def test_detect_anchor_flex_row_align_end() -> None:
    """display:flex + align-items:flex-end (row) → bottom."""
    styles = {"display": "flex", "flexDirection": "row", "alignItems": "flex-end"}
    assert _detect_anchor(styles) == "bottom"


def test_detect_autofit_default_normal() -> None:
    assert _detect_autofit({}) == "normal"


def test_detect_autofit_overflow_hidden() -> None:
    assert _detect_autofit({"overflow": "hidden"}) == "normal"


def test_detect_autofit_nowrap() -> None:
    assert _detect_autofit({"whiteSpace": "nowrap"}) == "shape"


def test_detect_columns_default_one() -> None:
    cols, gap = _detect_columns({})
    assert cols == 1
    assert gap == 0


def test_detect_columns_count_and_gap() -> None:
    cols, gap = _detect_columns({"columnCount": "2", "columnGap": "24px"})
    assert cols == 2
    assert gap > 0  # 24px converted to EMU > 0


def test_detect_columns_auto_stays_one() -> None:
    cols, _ = _detect_columns({"columnCount": "auto"})
    assert cols == 1


# ---------------------------------------------------------- forward: IR → bodyPr XML


def test_bodypr_anchor_top_emits_t() -> None:
    xml = _xml(_simple_body(anchor="top"))
    assert 'anchor="t"' in xml


def test_bodypr_anchor_middle_emits_ctr() -> None:
    xml = _xml(_simple_body(anchor="middle"))
    assert 'anchor="ctr"' in xml


def test_bodypr_anchor_bottom_emits_b() -> None:
    xml = _xml(_simple_body(anchor="bottom"))
    assert 'anchor="b"' in xml


def test_bodypr_normal_autofit_emits_normAutofit() -> None:
    xml = _xml(_simple_body(autofit="normal"))
    assert "<a:normAutofit/>" in xml
    assert "<a:spAutoFit/>" not in xml


def test_bodypr_shape_autofit_emits_spAutoFit() -> None:
    xml = _xml(_simple_body(autofit="shape"))
    assert "<a:spAutoFit/>" in xml
    assert "<a:normAutofit/>" not in xml


def test_bodypr_none_autofit_emits_noAutofit() -> None:
    xml = _xml(_simple_body(autofit="none"))
    assert "<a:noAutofit/>" in xml
    assert "<a:normAutofit/>" not in xml


def test_bodypr_single_column_has_no_numCol() -> None:
    xml = _xml(_simple_body(columns=1))
    assert "numCol" not in xml


def test_bodypr_two_columns_emits_numCol() -> None:
    xml = _xml(_simple_body(columns=2))
    assert 'numCol="2"' in xml


def test_bodypr_two_columns_with_gap_emits_spcCol() -> None:
    xml = _xml(_simple_body(columns=2, column_gap_emu=228_600))
    assert 'numCol="2"' in xml
    assert 'spcCol="228600"' in xml


def test_bodypr_two_columns_no_gap_no_spcCol() -> None:
    xml = _xml(_simple_body(columns=2, column_gap_emu=0))
    assert 'numCol="2"' in xml
    assert "spcCol" not in xml


def test_bodypr_emits_text_insets() -> None:
    xml = _xml(_simple_body(margins=(100, 200, 300, 400)))
    assert 'lIns="100"' in xml
    assert 'tIns="200"' in xml
    assert 'rIns="300"' in xml
    assert 'bIns="400"' in xml


# --------------------------------------------------------------------------- round trip: fwd → rev


def test_roundtrip_anchor_middle() -> None:
    body = _roundtrip_body(_simple_body(anchor="middle"))
    assert body.anchor == "middle"


def test_roundtrip_anchor_bottom() -> None:
    body = _roundtrip_body(_simple_body(anchor="bottom"))
    assert body.anchor == "bottom"


def test_roundtrip_anchor_top() -> None:
    body = _roundtrip_body(_simple_body(anchor="top"))
    assert body.anchor == "top"


def test_roundtrip_autofit_shape() -> None:
    body = _roundtrip_body(_simple_body(autofit="shape"))
    assert body.autofit == "shape"


def test_roundtrip_autofit_normal() -> None:
    body = _roundtrip_body(_simple_body(autofit="normal"))
    assert body.autofit == "normal"


def test_roundtrip_columns_two() -> None:
    body = _roundtrip_body(_simple_body(columns=2, column_gap_emu=228_600))
    assert body.columns == 2
    assert body.column_gap_emu == 228_600


def test_roundtrip_columns_one() -> None:
    body = _roundtrip_body(_simple_body(columns=1))
    assert body.columns == 1


def test_roundtrip_text_insets() -> None:
    body = _roundtrip_body(_simple_body(margins=(100, 200, 300, 400)))
    assert body.margins == (100, 200, 300, 400)


# ---------------------------------------------------------- reverse: bodyPr XML → HTML


def test_html_anchor_top_no_flex() -> None:
    """anchor=top: no flex CSS emitted (keep minimal output)."""
    html = _html_for(_simple_body(anchor="top"))
    # flex should not appear for the default top anchor
    assert "justify-content" not in html


def test_html_anchor_middle_emits_flex_center() -> None:
    html = _html_for(_simple_body(anchor="middle"))
    assert "display:flex" in html
    assert "flex-direction:column" in html
    assert "justify-content:center" in html


def test_html_anchor_bottom_emits_flex_end() -> None:
    html = _html_for(_simple_body(anchor="bottom"))
    assert "display:flex" in html
    assert "flex-direction:column" in html
    assert "justify-content:flex-end" in html


def test_html_columns_emits_column_count() -> None:
    html = _html_for(_simple_body(columns=2, column_gap_emu=228_600))
    assert "column-count:2" in html
    assert "column-fill:auto" in html
    assert "column-gap:" in html


def test_html_single_column_no_column_css() -> None:
    html = _html_for(_simple_body(columns=1))
    assert "column-count" not in html


def test_html_text_insets_emit_padding() -> None:
    html = _html_for(_simple_body(margins=(96_000, 192_000, 288_000, 384_000)))
    assert "padding:20.1575px 30.2362px 40.315px 10.0787px" in html


def test_html_autofit_none_emits_metadata() -> None:
    html = _html_for(_simple_body(autofit="none"))
    assert 'data-domoxml-autofit="none"' in html


def test_html_autofit_shape_emits_metadata() -> None:
    html = _html_for(_simple_body(autofit="shape"))
    assert 'data-domoxml-autofit="shape"' in html


def test_html_autofit_normal_no_metadata() -> None:
    """autofit=normal is the default — no metadata attribute."""
    html = _html_for(_simple_body(autofit="normal"))
    assert "data-domoxml-autofit" not in html
