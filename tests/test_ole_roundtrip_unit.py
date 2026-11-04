"""Embedded (OLE) objects: shown as their preview, kept whole through HTML and back."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from domoxml.core.chart_author import parse_chart_spec, workbook_bytes
from domoxml.core.ir.model import PreservedNode, SlideIR
from domoxml.core.roundtrip import render_html_roundtrip
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result

_E = 9525
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_BOX = '<a:off x="1000000" y="1000000"/><a:ext cx="3000000" cy="1500000"/>'
_FRAME = (
    '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="Embedded sheet"/>'
    "<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>"
    f"<p:xfrm>{_BOX}</p:xfrm><a:graphic>"
    '<a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole">'
    '<p:oleObj name="Worksheet" r:id="rId10" imgW="3000000" imgH="1500000" '
    'progId="Excel.Sheet.12"><p:embed/><p:pic><p:nvPicPr><p:cNvPr id="0" name=""/><p:cNvPicPr/>'
    '<p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId11"/><a:stretch><a:fillRect/>'
    f"</a:stretch></p:blipFill><p:spPr><a:xfrm>{_BOX}</a:xfrm>"
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic></p:oleObj>'
    "</a:graphicData></a:graphic></p:graphicFrame>"
)
_RELS = (
    f'<Relationship Id="rId10" Type="{_REL}/package" '
    'Target="../embeddings/Microsoft_Excel_Sheet1.xlsx"/>'
    f'<Relationship Id="rId11" Type="{_REL}/image" Target="../media/ole1.png"/>'
)


def ole_deck() -> bytes:
    """A one-slide deck holding an embedded workbook shown as a small green preview picture."""
    spec = parse_chart_spec('{"type":"bar","categories":["a"],"series":[{"values":[1]}]}')
    assert spec is not None
    preview = io.BytesIO()
    Image.new("RGB", (80, 40), "#2a6").save(preview, "PNG")
    base = build_pptx([SlideIR(width=1280 * _E, height=720 * _E, contents=())], faces=[])
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = data.decode().replace("</p:spTree>", _FRAME + "</p:spTree>").encode()
            if item.filename == "ppt/slides/_rels/slide1.xml.rels":
                data = (
                    data.decode().replace("</Relationships>", _RELS + "</Relationships>").encode()
                )
            if item.filename == "[Content_Types].xml":
                text = data.decode()
                added = f'<Default Extension="xlsx" ContentType="{_XLSX}"/>'
                if 'Extension="png"' not in text:
                    added += '<Default Extension="png" ContentType="image/png"/>'
                data = text.replace("</Types>", added + "</Types>").encode()
            zout.writestr(item, data)
        zout.writestr("ppt/embeddings/Microsoft_Excel_Sheet1.xlsx", workbook_bytes(spec))
        zout.writestr("ppt/media/ole1.png", preview.getvalue())
    return out.getvalue()


def test_an_embedded_workbook_reads_as_its_preview_with_the_object_attached() -> None:
    result = read_pptx_result(ole_deck())

    [node] = result.slides[0].contents
    assert isinstance(node, PreservedNode) and node.fallback is not None
    assert node.payload.kind == "graphicFrame"
    assert any(part.name.endswith(".xlsx") for part in node.payload.parts)
    [item] = result.coverage.items
    assert item.source_retention.value == "attached"


@pytest.mark.integration
def test_the_embedded_object_survives_pptx_to_html_to_pptx() -> None:
    html = pptx_to_html(ole_deck())

    assert "data-domoxml-preserved-payload" in html.slides[0].html
    rebuilt = render_html_roundtrip(html).pptx
    assert rebuilt is not None
    with zipfile.ZipFile(io.BytesIO(rebuilt)) as package:
        names = package.namelist()
        slide = package.read("ppt/slides/slide1.xml")
    assert any(n.startswith("ppt/embeddings/") and n.endswith(".xlsx") for n in names)
    assert b"oleObj" in slide and b'progId="Excel.Sheet.12"' in slide
