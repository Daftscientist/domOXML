"""Direct contracts for reverse DrawingML text parsing."""

from __future__ import annotations

from xml.etree.ElementTree import Element, fromstring

from domoxml.core.ir.model import Hyperlink
from domoxml.slides.inherit import build_placeholder_context
from domoxml.slides.text_read import read_text_body, read_text_run

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _no_link(_properties: Element) -> None:
    return None


def test_reads_run_typography_and_hyperlink_through_resolver() -> None:
    run = fromstring(
        f'<a:r xmlns:a="{_A}"><a:rPr sz="1800" b="1" i="1" u="dbl" '
        'strike="sngStrike" cap="small" spc="125">'
        '<a:latin typeface="Inter"/><a:solidFill><a:srgbClr val="112233"/></a:solidFill>'
        "</a:rPr><a:t>Styled</a:t></a:r>"
    )

    parsed = read_text_run(run, {}, lambda _properties: Hyperlink(url="https://example.test"))

    assert parsed is not None
    assert (parsed.text, parsed.font_family, parsed.size_pt) == ("Styled", "Inter", 18)
    assert parsed.bold and parsed.italic
    assert parsed.underline == "dbl"
    assert parsed.strike and parsed.caps == "small"
    assert parsed.letter_spacing_pt == 1.25
    assert parsed.color.hex == "112233"
    assert parsed.hyperlink == Hyperlink(url="https://example.test")


def test_reads_body_layout_spacing_and_bullet_metadata() -> None:
    shape = fromstring(
        f'<p:sp xmlns:p="{_P}" xmlns:a="{_A}"><p:txBody>'
        '<a:bodyPr anchor="ctr" numCol="2" spcCol="100"><a:spAutoFit/></a:bodyPr>'
        '<a:p><a:pPr algn="r" lvl="2" marL="12700" indent="6350">'
        '<a:lnSpc><a:spcPct val="150000"/></a:lnSpc>'
        '<a:spcBef><a:spcPts val="600"/></a:spcBef>'
        '<a:spcAft><a:spcPts val="900"/></a:spcAft>'
        '<a:buChar char="•"/></a:pPr>'
        '<a:r><a:rPr sz="1200"/><a:t>Item</a:t></a:r>'
        "</a:p></p:txBody></p:sp>"
    )

    body = read_text_body(shape, {}, _no_link)

    assert body is not None
    assert (body.anchor, body.autofit, body.columns, body.column_gap_emu) == (
        "middle",
        "shape",
        2,
        100,
    )
    paragraph = body.paragraphs[0]
    assert (paragraph.align, paragraph.level) == ("right", 2)
    assert paragraph.line_spacing is not None and paragraph.line_spacing.percent == 1.5
    assert (paragraph.space_before_pt, paragraph.space_after_pt) == (6, 9)
    assert (paragraph.left_margin_pt, paragraph.indent_pt) == (1, 0.5)
    assert paragraph.bullet is not None and paragraph.bullet.kind == "char"


def test_reads_text_fields_in_source_order() -> None:
    shape = fromstring(
        f'<p:sp xmlns:p="{_P}" xmlns:a="{_A}"><p:txBody>'
        "<a:bodyPr/><a:p>"
        '<a:r><a:rPr sz="1200"/><a:t>Page </a:t></a:r>'
        '<a:fld id="{field-id}" type="slidenum">'
        '<a:rPr sz="1200"/><a:t>2</a:t></a:fld>'
        '<a:r><a:rPr sz="1200"/><a:t> of 3</a:t></a:r>'
        "</a:p></p:txBody></p:sp>"
    )

    body = read_text_body(shape, {}, _no_link)

    assert body is not None
    assert [run.text for run in body.paragraphs[0].runs] == ["Page ", "2", " of 3"]


def test_text_field_inherits_placeholder_paragraph_alignment() -> None:
    shape = fromstring(
        f'<p:sp xmlns:p="{_P}" xmlns:a="{_A}">'
        '<p:nvSpPr><p:nvPr><p:ph type="sldNum" idx="10"/></p:nvPr></p:nvSpPr>'
        '<p:txBody><a:bodyPr/><a:p><a:pPr lvl="0"/>'
        '<a:fld id="{field-id}" type="slidenum"><a:rPr/><a:t>2</a:t></a:fld>'
        "</a:p></p:txBody></p:sp>"
    )
    master = fromstring(
        f'<p:sldMaster xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree><p:sp>'
        '<p:nvSpPr><p:nvPr><p:ph type="sldNum" idx="4"/></p:nvPr></p:nvSpPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle><a:lvl1pPr algn="ctr">'
        '<a:defRPr sz="1000"/></a:lvl1pPr></a:lstStyle></p:txBody>'
        "</p:sp></p:spTree></p:cSld></p:sldMaster>"
    )
    context = build_placeholder_context(shape, None, master)

    body = read_text_body(shape, {}, _no_link, ph_ctx=context)

    assert body is not None
    assert body.paragraphs[0].align == "center"
    assert body.paragraphs[0].runs[0].size_pt == 10
