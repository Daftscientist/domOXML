"""Web Viewer frames: an iframe page as a native web extension with its snapshot."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import Box, MediaNode, PictureFill, SlideIR
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result

_UNIT = 9525
_URL = "https://example.com/dash?view=1&lang=en"


def _snapshot() -> PictureFill:
    out = io.BytesIO()
    Image.new("RGB", (64, 40), "tan").save(out, "PNG")
    return PictureFill(data=out.getvalue(), ext="png")


def _web(poster: PictureFill | None = None) -> MediaNode:
    return MediaNode(
        box=Box(x=100 * _UNIT, y=80 * _UNIT, width=640 * _UNIT, height=360 * _UNIT),
        kind="web",
        media_url=_URL,
        poster_fill=poster,
    )


def _deck(node: MediaNode) -> bytes:
    return build_pptx([SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=(node,))], faces=[])


def test_a_web_page_is_a_web_viewer_frame_with_its_snapshot() -> None:
    deck = _deck(_web(_snapshot()))

    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        names = package.namelist()
        slide = package.read("ppt/slides/slide1.xml").decode()
        extension = next(n for n in names if n.startswith("ppt/webextensions/webextension"))
        xml = package.read(extension).decode()
        content_types = package.read("[Content_Types].xml").decode()
        rels = package.read("ppt/slides/_rels/slide1.xml.rels").decode()

    assert "we:webextensionref" in slide and "Web Viewer" in slide
    assert "WA104295837" in xml and "&quot;https://example.com/dash?view=1&amp;lang=en&quot;" in xml
    assert 'we:snapshot r:embed="rId1"' in xml
    assert "webextension+xml" in content_types and "relationships/webextension" in rels


def test_a_web_viewer_frame_reads_back_with_its_page_box_and_snapshot() -> None:
    poster = _snapshot()

    [read] = read_pptx_result(_deck(_web(poster))).slides[0].contents

    assert isinstance(read, MediaNode) and read.kind == "web"
    assert read.media_url == _URL
    assert read.box == _web().box
    assert read.poster_fill is not None and read.poster_fill.data == poster.data


def test_a_web_frame_without_a_snapshot_gets_a_blank_browser_one() -> None:
    [read] = read_pptx_result(_deck(_web())).slides[0].contents

    assert isinstance(read, MediaNode) and read.poster_fill is not None


def test_a_web_viewer_frame_becomes_an_iframe_in_html() -> None:
    html = (
        serialize_canvas([SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=(_web(),))])
        .slides[0]
        .html
    )

    assert "<iframe" in html and "example.com/dash" in html


@pytest.mark.integration
async def test_an_iframe_to_a_page_extracts_as_a_web_frame() -> None:
    from domoxml.core.ir import extract_slide
    from domoxml.core.render import BrowserSession

    page = (
        "<body style='margin:0'><iframe src='https://example.invalid/page' "
        "style='position:absolute;left:100px;top:80px;width:640px;height:360px;border:0'>"
        "</iframe></body>"
    )
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    result = extract_slide(rendered)

    [frame] = [n for n in result.slide.contents if isinstance(n, MediaNode)]
    assert frame.kind == "web" and frame.media_url == "https://example.invalid/page"
    assert frame.poster_fill is not None
