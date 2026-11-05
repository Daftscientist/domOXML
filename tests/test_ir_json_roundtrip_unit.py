"""The canvas IR round-trips through JSON exactly, including embedded image, media and font bytes.

JSON is the boundary between domOXML and non-Python hosts (e.g. a browser app talking to domOXML
running under Pyodide), so every model reachable from a slide must serialize and validate back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domoxml.core.fonts import FontFace
from domoxml.core.ir.model import SlideIR
from domoxml.slides.read import read_pptx_result

DECKS = sorted((Path(__file__).resolve().parents[1] / "real-decks" / "pptx").glob("*/source.pptx"))


@pytest.mark.parametrize("deck", DECKS, ids=lambda p: p.parent.name)
def test_slide_ir_round_trips_through_json(deck: Path) -> None:
    result = read_pptx_result(deck.read_bytes())
    assert result.slides
    for slide in result.slides:
        restored = SlideIR.model_validate_json(slide.model_dump_json())
        assert restored == slide


def test_font_face_round_trips_through_json() -> None:
    face = FontFace(family="Inter", bold=True, italic=False, data=bytes(range(256)))
    assert FontFace.model_validate_json(face.model_dump_json()) == face
