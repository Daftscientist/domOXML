"""A 3-D model: ``<model-viewer>`` with an inline GLB and a native PowerPoint model frame."""

from __future__ import annotations

import base64
import io
import struct
import zipfile

import pytest

from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import MediaNode
from domoxml.core.render import BrowserSession, compose_page
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result
from domoxml.types import Theme


def _glb() -> bytes:
    """The smallest binary glTF: a header and an empty JSON chunk."""
    body = b'{"asset":{"version":"2.0"}}  '
    return (
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body))
        + struct.pack("<I4s", len(body), b"JSON")
        + body
    )


def _html(source: str) -> str:
    return (
        f'<model-viewer src="{source}" style="position:absolute;left:60px;top:40px;'
        'width:500px;height:320px;display:block"></model-viewer>'
    )


async def _slide(html: str):
    page = compose_page(html, css=None, theme=Theme(), width_px=1280, height_px=720)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)
    return extract_slide(rendered)


@pytest.mark.integration
async def test_a_model_viewer_becomes_a_native_model_frame_and_reads_back_as_a_model() -> None:
    glb = _glb()
    source = "data:model/gltf-binary;base64," + base64.b64encode(glb).decode()

    result = await _slide(_html(source))

    [node] = result.slide.contents
    assert isinstance(node, MediaNode) and node.kind == "model" and node.media_data == glb
    deck = build_pptx([result.slide], faces=[])
    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        names = package.namelist()
        slide_xml = package.read("ppt/slides/slide1.xml").decode()
        assert any(n.endswith(".glb") for n in names)
        assert 'Requires="am3d"' in slide_xml and "<am3d:model3d" in slide_xml
        assert "model/gltf.binary" in package.read("[Content_Types].xml").decode()
    [read] = read_pptx_result(deck).slides[0].contents
    assert isinstance(read, MediaNode) and read.kind == "model" and read.media_data == glb
    assert read.box == node.box and read.play_settings_xml is not None
    html = pptx_to_html(deck).slides[0].html
    assert "<model-viewer" in html and base64.b64encode(glb).decode() in html


@pytest.mark.integration
async def test_a_model_viewer_with_a_remote_or_non_glb_source_is_not_a_model_frame() -> None:
    remote = await _slide(_html("https://example.com/a.glb"))
    fake = await _slide(
        _html("data:model/gltf-binary;base64," + base64.b64encode(b"not a glb").decode())
    )

    for result in (remote, fake):
        assert not any(isinstance(n, MediaNode) for n in result.slide.contents)


def test_a_saved_camera_survives_a_round_trip() -> None:
    from domoxml.core.ir.model import Box, SlideIR

    view = (
        '<am3d:camera xmlns:am3d="http://schemas.microsoft.com/office/drawing/2017/model3d">'
        '<am3d:pos x="1" y="2" z="3"/></am3d:camera>'
    )
    node = MediaNode(
        box=Box(x=0, y=0, width=3_000_000, height=2_000_000),
        kind="model",
        media_data=_glb(),
        media_ext="glb",
        play_settings_xml=view,
    )

    deck = build_pptx([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))], faces=[])
    [read] = read_pptx_result(deck).slides[0].contents

    assert isinstance(read, MediaNode) and read.play_settings_xml is not None
    assert 'z="3"' in read.play_settings_xml
