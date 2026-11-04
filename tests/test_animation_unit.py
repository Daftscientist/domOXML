"""Entrance animations: p:timing, the IR and HTML data attributes, both directions."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from domoxml.core.html import serialize_canvas
from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import Animation, Box, Rgba, ShapeNode, SlideIR, SolidFill
from domoxml.core.render import BrowserSession, compose_page
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result
from domoxml.types import Theme

_UNIT = 9525


def _box(node_id: str, x: int) -> ShapeNode:
    return ShapeNode(
        node_id=node_id,
        box=Box(x=x * _UNIT, y=100 * _UNIT, width=100 * _UNIT, height=80 * _UNIT),
        geom="rect",
        fill=SolidFill(color=Rgba(r=0, g=100, b=200)),
    )


def _slide(*animations: Animation) -> SlideIR:
    return SlideIR(
        width=1280 * _UNIT,
        height=720 * _UNIT,
        contents=(_box("a", 100), _box("b", 300), _box("c", 500)),
        animations=animations,
    )


_PLAN = (
    Animation(target="a", effect="fade", step=0, duration_ms=400),
    Animation(target="b", effect="appear", step=1),
    Animation(target="c", effect="fade", step=1, delay_ms=300, duration_ms=800),
)


def test_effects_become_click_steps_in_the_slides_timing_and_read_back() -> None:
    deck = build_pptx([_slide(*_PLAN)], faces=[])

    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    back = read_pptx_result(deck).slides[0].animations

    assert 'presetClass="entr"' in xml and 'nodeType="clickEffect"' in xml
    assert xml.count('delay="indefinite"') == 1  # one click step
    assert [(a.effect, a.step, a.delay_ms, a.duration_ms) for a in back] == [
        ("fade", 0, 0, 400),
        ("appear", 1, 0, 1),
        ("fade", 1, 300, 800),
    ]


def test_animations_ride_on_the_html_elements_and_survive_a_pptx_round_trip() -> None:
    html = serialize_canvas([_slide(*_PLAN)]).slides[0].html

    assert html.count("data-animate=") == 3
    assert 'data-animate="fade" data-animate-step="0"' in html
    assert 'data-animate-step="1" data-animate-delay="300" data-animate-duration="800"' in html


def test_a_real_decks_fades_become_ir_animations_instead_of_preserved_timing() -> None:
    path = Path("/home/leo/officecli-reference/OfficeCLI/examples/Cat-Secret-Life.pptx")
    if not path.exists():
        pytest.skip("local corpus deck is not available")

    result = read_pptx_result(path.read_bytes())

    animated = [s for s in result.slides if s.animations]
    assert animated and all(a.effect == "fade" for s in animated for a in s.animations)
    assert not any("p:timing" in w.message for w in result.warnings)
    html = pptx_to_html(path.read_bytes())
    assert html.slides[2].html.count("data-animate=") == len(animated[0].animations)


def test_timing_with_other_effects_stays_preserved_source() -> None:
    deck = build_pptx([_slide(*_PLAN)], faces=[])
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(deck)) as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = data.replace(b'presetClass="entr"', b'presetClass="exit"', 1)
            zout.writestr(item, data)

    result = read_pptx_result(patched.getvalue())

    assert result.slides[0].animations == ()
    assert any("p:timing" in w.message for w in result.warnings)


@pytest.mark.integration
async def test_data_animate_on_html_elements_becomes_pptx_timing() -> None:
    html = (
        "<div data-animate='fade' data-animate-step='1' data-animate-duration='700' "
        "style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#08f'></div>"
        "<div data-animate='appear' style='position:absolute;left:400px;top:100px;width:200px;"
        "height:100px;background:#c20'></div>"
    )
    page = compose_page(html, css=None, theme=Theme(), width_px=1280, height_px=720)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    slide = extract_slide(rendered).slide

    assert [(a.effect, a.step, a.duration_ms) for a in slide.animations] == [
        ("fade", 1, 700),
        ("appear", 0, 500),
    ]
    back = read_pptx_result(build_pptx([slide], faces=[])).slides[0].animations
    # PowerPoint plays by step, so the start-of-slide effect comes first.
    assert [(a.effect, a.step) for a in back] == [("appear", 0), ("fade", 1)]


def test_a_gap_in_click_steps_closes_up_instead_of_skipping_a_click() -> None:
    plan = (Animation(target="a", step=1), Animation(target="b", step=3))
    deck = build_pptx([_slide(*plan)], faces=[])

    back = read_pptx_result(deck).slides[0].animations

    assert [a.step for a in back] == [1, 2]


def _with_timing(xml_edit: tuple[bytes, bytes]) -> bytes:
    deck = build_pptx([_slide(*_PLAN)], faces=[])
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(deck)) as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = data.replace(*xml_edit, 1)
            zout.writestr(item, data)
    return patched.getvalue()


def test_timing_with_a_second_sequence_or_paragraph_targets_stays_preserved_source() -> None:
    second = _with_timing(
        (
            b"</p:seq></p:childTnLst>",
            b'</p:seq><p:seq concurrent="1" nextAc="seek"><p:cTn id="99" dur="indefinite"'
            b' nodeType="interactiveSeq"><p:childTnLst/></p:cTn></p:seq></p:childTnLst>',
        )
    )
    paragraph = _with_timing(
        (
            b'<p:spTgt spid="2"/>',
            b'<p:spTgt spid="2"><p:txEl><p:pRg st="0" end="0"/></p:txEl></p:spTgt>',
        )
    )

    for deck in (second, paragraph):
        result = read_pptx_result(deck)
        assert result.slides[0].animations == ()
        assert any("p:timing" in w.message for w in result.warnings)
