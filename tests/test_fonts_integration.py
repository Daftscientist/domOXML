"""Font-embedding integration: requires fontconfig + the Poppins font installed."""

from __future__ import annotations

import io
import shutil
import zipfile

import pytest
from pptx import Presentation as PptxRead

from domoxml.core.fonts import load_faces
from domoxml.core.ir.model import Box, ShapeNode, SlideIR, TextBody, TextParagraph, TextRun
from domoxml.slides import build_pptx

pytestmark = pytest.mark.integration


def test_used_font_is_embedded_and_pptx_stays_valid() -> None:
    if shutil.which("fc-match") is None:
        pytest.skip("fontconfig not available")

    deck = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=4_000_000, height=1_000_000),
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(
                                TextRun(
                                    text="Driftwood",
                                    font_family="Poppins",
                                    size_pt=40.0,
                                    bold=True,
                                ),
                            ),
                        ),
                    )
                ),
            ),
        ),
    )
    if not load_faces([deck]):
        pytest.skip("Poppins (TTF) not installed on this system")

    data = build_pptx([deck])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert any(n.startswith("ppt/fonts/") and n.endswith(".fntdata") for n in names)
        presentation = archive.read("ppt/presentation.xml").decode()
    assert 'embedTrueTypeFonts="1"' in presentation
    assert '<p:font typeface="Poppins"/>' in presentation
    PptxRead(io.BytesIO(data))  # still opens as a valid deck
