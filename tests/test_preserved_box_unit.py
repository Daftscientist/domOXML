"""A preserved object is written where its box says, not where its source XML had it.

A chart (or any other preserved payload) that was moved or resized, in the IR or as normalized HTML
captured back, used to come out of build_pptx at its original position: the root XML's own transform
was emitted untouched and the node's box was ignored.
"""

from __future__ import annotations

import math
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
    angle = math.radians(30)
    bw = round(node.box.width * abs(math.cos(angle)) + node.box.height * abs(math.sin(angle)))
    bh = round(node.box.width * abs(math.sin(angle)) + node.box.height * abs(math.cos(angle)))
    centre_x = node.box.x + 914400 + node.box.width // 2
    centre_y = node.box.y + node.box.height // 2
    bounds = Box(x=centre_x - bw // 2, y=centre_y - bh // 2, width=bw, height=bh)
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


def test_a_fallback_box_moves_the_shape_by_the_same_amount() -> None:
    """A box describing a fallback (a full-slide render) moves the frame with it, not onto it."""
    index, node = _chart_slide()
    slide = read_pptx_result(DECK.read_bytes()).slides[index]
    full = Box(x=0, y=0, width=slide.width, height=slide.height)
    placed = node.model_copy(
        update={"box": full, "payload": node.payload.model_copy(update={"placed_box": full})}
    )
    untouched = [placed if n.node_id == node.node_id else n for n in slide.contents]
    pptx = build_pptx([slide.model_copy(update={"contents": untouched})])
    assert _frame_xfrm(pptx, 1) == (node.box.x, node.box.y, node.box.width, node.box.height)
    moved_box = full.model_copy(update={"x": 457200})
    moved = [
        placed.model_copy(update={"box": moved_box}) if n.node_id == node.node_id else n
        for n in slide.contents
    ]
    pptx = build_pptx([slide.model_copy(update={"contents": moved})])
    expected = (node.box.x + 457200, node.box.y, node.box.width, node.box.height)
    assert _frame_xfrm(pptx, 1) == expected


def test_an_unreadable_rotation_keeps_the_source_transform() -> None:
    index, node = _chart_slide()
    slide = read_pptx_result(DECK.read_bytes()).slides[index]
    xml = re.sub(r"<(\w+:)?xfrm>", r'<\1xfrm rot="bad">', node.payload.root_xml, count=1)
    broken = node.model_copy(
        update={
            "box": node.box.model_copy(update={"x": node.box.x + 914400}),
            "payload": node.payload.model_copy(update={"root_xml": xml}),
        }
    )
    contents = [broken if n.node_id == node.node_id else n for n in slide.contents]
    pptx = build_pptx([slide.model_copy(update={"contents": contents})])
    assert _frame_xfrm(pptx, 1) == (node.box.x, node.box.y, node.box.width, node.box.height)
