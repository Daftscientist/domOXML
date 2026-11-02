# pyright: basic, reportArgumentType=false
# Built with the untyped native-lab dev tool and python-pptx; ruff still applies.
"""SmartArt: the drawing part PowerPoint saved becomes ordinary editable shapes."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from domoxml import Presentation
from domoxml.core.ir.model import ShapeNode
from domoxml.slides.read import read_pptx
from domoxml.types import Representation

_DSP = "http://schemas.microsoft.com/office/drawing/2008/diagram"
_DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"


def _box(x: int, y: int, w: int, h: int, color: str, label: str, geom: str = "roundRect") -> str:
    return (
        '<dsp:sp modelId="{00000000-0000-0000-0000-000000000000}"><dsp:nvSpPr>'
        '<dsp:cNvPr id="0" name=""/><dsp:cNvSpPr/></dsp:nvSpPr><dsp:spPr>'
        f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        f'<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill></dsp:spPr>'
        '<dsp:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/><a:r>'
        '<a:rPr lang="en-US" sz="2400"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
        f"</a:rPr><a:t>{label}</a:t></a:r></a:p></dsp:txBody></dsp:sp>"
    )


def _deck_with_smartart(*, with_drawing: bool = True) -> bytes:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import native_lab  # pyright: ignore[reportMissingImports]

    deck = native_lab.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    drawing = (
        f'<dsp:drawing xmlns:dgm="{_DGM}" xmlns:dsp="{_DSP}" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dsp:spTree>'
        '<dsp:nvGrpSpPr><dsp:cNvPr id="0" name=""/><dsp:cNvGrpSpPr/></dsp:nvGrpSpPr><dsp:grpSpPr/>'
        + _box(0, 600000, 2400000, 1200000, "4472C4", "Plan")
        + _box(3000000, 600000, 2400000, 1200000, "ED7D31", "Build")
        + _box(6000000, 600000, 2400000, 1200000, "70AD47", "Ship")
        + "</dsp:spTree></dsp:drawing>"
    ).encode()
    drawing_rel = "rId99"
    model = (
        f'<dgm:dataModel xmlns:dgm="{_DGM}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<dgm:ptLst/><dgm:cxnLst/><dgm:bg/><dgm:whole/><dgm:extLst>"
        '<a:ext uri="http://schemas.microsoft.com/office/drawing/2008/diagram">'
        f'<dsp:dataModelExt xmlns:dsp="{_DSP}" relId="{{rid}}" '
        'minVer="http://schemas.openxmlformats.org/drawingml/2006/diagram"/></a:ext>'
        "</dgm:extLst></dgm:dataModel>"
    )
    drawing_id = ""
    if with_drawing:
        drawing_id = native_lab._part(
            slide,
            "/ppt/diagrams/drawing1.xml",
            "application/vnd.ms-office.drawingml.diagramDrawing+xml",
            drawing,
            "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing",
        )
    data_id = native_lab._part(
        slide,
        "/ppt/diagrams/data1.xml",
        "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
        model.replace("{rid}", drawing_id or drawing_rel).encode(),
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData",
    )
    frame = (
        '<p:graphicFrame xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        f'xmlns:r="{native_lab._REL}"><p:nvGraphicFramePr><p:cNvPr id="4" name="Diagram 3"/>'
        "<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>"
        '<p:xfrm><a:off x="914400" y="914400"/><a:ext cx="8400000" cy="2400000"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
        f'<dgm:relIds xmlns:dgm="{_DGM}" r:dm="{data_id}" r:lo="{data_id}" r:qs="{data_id}" '
        f'r:cs="{data_id}"/></a:graphicData></a:graphic></p:graphicFrame>'
    )
    slide.shapes._spTree.append(native_lab.etree.fromstring(frame))
    buffer = BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def test_smartart_becomes_its_drawn_shapes_at_slide_coordinates() -> None:
    slide = read_pptx(_deck_with_smartart())[0]

    shapes = [node for node in slide.contents if isinstance(node, ShapeNode) and node.text]
    assert [s.text.paragraphs[0].runs[0].text for s in shapes if s.text] == [
        "Plan",
        "Build",
        "Ship",
    ]
    # The drawing is relative to the frame (914400, 914400); shapes land on the slide.
    assert [s.box.x for s in shapes] == [914400, 914400 + 3000000, 914400 + 6000000]
    assert all(s.box.y == 914400 + 600000 for s in shapes)
    assert len({s.node_id for s in shapes}) == 3


def test_smartart_reaches_html_as_editable_components_not_a_failure() -> None:
    html = Presentation.from_pptx(_deck_with_smartart())

    [item] = [i for i in html.coverage.items if "SmartArt" in i.reason]
    assert item.representation is Representation.DECOMPOSED and item.output_count == 3
    assert item.raster_area_emu2 == 0 and item.source_retention.value == "lost"
    assert all(i.representation is not Representation.FAILED for i in html.coverage.items)
    page = html.slides[0].html
    assert "Plan" in page and "Build" in page and "Ship" in page


def test_a_diagram_with_no_saved_drawing_is_still_preserved_not_lost() -> None:
    html = Presentation.from_pptx(_deck_with_smartart(with_drawing=False))

    assert not any("SmartArt converted" in i.reason for i in html.coverage.items)
    assert any("data-domoxml-preserved-payload" in s.html for s in html.slides)


def test_a_round_rect_without_an_adjust_guide_gets_powerpoints_default_corner() -> None:
    slide = read_pptx(_deck_with_smartart())[0]
    first = next(n for n in slide.contents if isinstance(n, ShapeNode) and n.text)

    # 16.667% of the short side (1,200,000 EMU) is the preset's own default.
    assert first.geom == "roundRect"
    assert abs(first.corner_radius_emu - round(0.16667 * 1_200_000)) <= 1


def _style_only_deck() -> bytes:
    """A diagram whose shape has no explicit fill, only ``fillRef`` / ``fontRef`` colours."""
    deck = _deck_with_smartart()
    import zipfile

    source = zipfile.ZipFile(BytesIO(deck))
    parts = {name: source.read(name) for name in source.namelist()}
    drawing = parts["ppt/diagrams/drawing1.xml"].decode()
    drawing = drawing.replace(
        '<a:solidFill><a:srgbClr val="4472C4"/></a:solidFill></dsp:spPr>',
        '</dsp:spPr><dsp:style><a:lnRef idx="2"><a:schemeClr val="accent1"/></a:lnRef>'
        '<a:fillRef idx="1"><a:srgbClr val="123456"/></a:fillRef><a:effectRef idx="0">'
        '<a:schemeClr val="accent1"/></a:effectRef><a:fontRef idx="minor">'
        '<a:srgbClr val="FEDCBA"/></a:fontRef></dsp:style>',
        1,
    )
    drawing = drawing.replace(
        '<a:rPr lang="en-US" sz="2400"><a:solidFill><a:srgbClr val="FFFFFF"/>'
        "</a:solidFill></a:rPr>",
        '<a:rPr lang="en-US" sz="2400"/>',
        1,
    )
    parts["ppt/diagrams/drawing1.xml"] = drawing.encode()
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name, content in parts.items():
            target.writestr(name, content)
    return out.getvalue()


def test_colours_referenced_only_by_the_diagram_style_are_made_explicit() -> None:
    from domoxml.core.ir.model import SolidFill

    slide = read_pptx(_style_only_deck())[0]
    first = next(n for n in slide.contents if isinstance(n, ShapeNode) and n.text)

    assert isinstance(first.fill, SolidFill) and first.fill.color.hex == "123456"
    assert first.line is not None
    run = first.text.paragraphs[0].runs[0] if first.text else None
    assert run is not None and run.color.hex == "FEDCBA"


def test_two_unnamed_drawings_keep_the_frame_preserved_instead_of_guessing() -> None:
    import zipfile

    source = zipfile.ZipFile(BytesIO(_deck_with_smartart()))
    parts = {name: source.read(name) for name in source.namelist()}
    parts["ppt/diagrams/data1.xml"] = parts["ppt/diagrams/data1.xml"].replace(b'relId="', b'x="', 1)
    rels = parts["ppt/slides/_rels/slide1.xml.rels"].decode()
    rels = rels.replace(
        "</Relationships>",
        '<Relationship Id="rId77" Type="http://schemas.microsoft.com/office/2007/relationships/'
        'diagramDrawing" Target="../diagrams/drawing1.xml"/></Relationships>',
    )
    parts["ppt/slides/_rels/slide1.xml.rels"] = rels.encode()
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name, content in parts.items():
            target.writestr(name, content)

    html = Presentation.from_pptx(out.getvalue())

    assert not any("SmartArt converted" in i.reason for i in html.coverage.items)
