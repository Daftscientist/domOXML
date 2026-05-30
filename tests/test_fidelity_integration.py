"""End-to-end fidelity gate. Requires Chromium + LibreOffice + poppler."""

from __future__ import annotations

import pytest

from domoxml import Presentation, Slide
from domoxml.core.fidelity import compare, has_libreoffice, render_pptx_to_pngs
from domoxml.types import OutputFormat, SlideSize

pytestmark = pytest.mark.integration


def test_rendered_pptx_is_faithful_to_its_source() -> None:
    if not has_libreoffice():
        pytest.skip("LibreOffice not installed")

    deck = Presentation(size=SlideSize.WIDE_16_9)
    deck.add(
        Slide(
            html=(
                "<div style='width:100%;height:100%;background:#0b1020;"
                "color:#fff;font-size:64px'>Hello</div>"
            )
        )
    )
    result = deck.render({OutputFormat.PNG, OutputFormat.PPTX})
    assert result.pptx is not None

    candidate = render_pptx_to_pngs(result.pptx)
    assert len(candidate) == 1
    report = compare(result.pngs[0], candidate[0])
    assert report.similarity > 0.9  # solid background + text matches closely
