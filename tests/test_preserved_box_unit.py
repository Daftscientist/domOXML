"""A preserved object is written where its box says, not where its source XML had it.

A chart (or any other preserved payload) that was moved or resized, in the IR or as normalized HTML
captured back, used to come out of build_pptx at its original position: the root XML's own transform
was emitted untouched and the node's box was ignored.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from defusedxml import ElementTree

from domoxml.core.ir.model import Box, PreservedNode
from domoxml.slides import build_pptx
from domoxml.slides.read import read_pptx_result

DECK = (
    Path(__file__).resolve().parents[1]
    / "real-decks"
    / "pptx"
    / "external-chart-preservation"
    / "source.pptx"
)
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _chart_slide() -> tuple[int, PreservedNode]:
    slides = read_pptx_result(DECK.read_bytes()).slides
    for index, slide in enumerate(slides):
        for node in slide.contents:
            if isinstance(node, PreservedNode):
                return index, node
    raise AssertionError("fixture has no preserved node")


def _frame_xfrm(pptx: bytes, slide_number: int) -> tuple[int, int, int, int]:
    with ZipFile(BytesIO(pptx)) as package:
        root = ElementTree.fromstring(package.read(f"ppt/slides/slide{slide_number}.xml"))
    frame = root.find(f".//{{{_P}}}graphicFrame")
    assert frame is not None
    off = frame.find(f"{{{_P}}}xfrm/{{{_A}}}off")
    ext = frame.find(f"{{{_P}}}xfrm/{{{_A}}}ext")
    assert off is not None and ext is not None
    return (
        int(off.get("x", "0")),
        int(off.get("y", "0")),
        int(ext.get("cx", "0")),
        int(ext.get("cy", "0")),
    )


def test_an_untouched_preserved_chart_keeps_its_source_transform() -> None:
    index, node = _chart_slide()
    slide = read_pptx_result(DECK.read_bytes()).slides[index]
    pptx = build_pptx([slide])
    assert _frame_xfrm(pptx, 1) == (node.box.x, node.box.y, node.box.width, node.box.height)


def test_a_moved_and_resized_preserved_chart_lands_at_its_box() -> None:
    index, node = _chart_slide()
    slide = read_pptx_result(DECK.read_bytes()).slides[index]
    moved = Box(
        x=node.box.x + 914400,
        y=node.box.y + 457200,
        width=node.box.width // 2,
        height=node.box.height // 2,
    )
    contents = [
        n.model_copy(update={"box": moved}) if n.node_id == node.node_id else n
        for n in slide.contents
    ]
    pptx = build_pptx([slide.model_copy(update={"contents": contents})])
    assert _frame_xfrm(pptx, 1) == (moved.x, moved.y, moved.width, moved.height)
    # The chart itself is still the native chart part, not a picture of it.
    with ZipFile(BytesIO(pptx)) as package:
        assert any(name.startswith("ppt/charts/chart") for name in package.namelist())


def test_a_turned_preserved_object_moves_by_its_centre_and_keeps_its_size() -> None:
    index, node = _chart_slide()
    slide = read_pptx_result(DECK.read_bytes()).slides[index]
    xml = node.payload.root_xml
    turned_xml = re.sub(r"<(\w+:)?xfrm>", r'<\1xfrm rot="1800000">', xml, count=1)
    assert turned_xml != xml
    turned = node.model_copy(
        update={"payload": node.payload.model_copy(update={"root_xml": turned_xml})}
    )
    # A captured turned object reports its bounds: bigger than its frame, same centre.
    bounds = Box(
        x=node.box.x + 914400 - 100_000,
        y=node.box.y - 50_000,
        width=node.box.width + 200_000,
        height=node.box.height + 100_000,
    )
    contents = [
        turned.model_copy(update={"box": bounds}) if n.node_id == node.node_id else n
        for n in slide.contents
    ]
    pptx = build_pptx([slide.model_copy(update={"contents": contents})])
    assert _frame_xfrm(pptx, 1) == (
        node.box.x + 914400,
        node.box.y,
        node.box.width,
        node.box.height,
    )
