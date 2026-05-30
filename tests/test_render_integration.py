"""End-to-end render tests. Require Chromium: ``playwright install chromium``."""

from __future__ import annotations

import pytest

from domoxml import Presentation, Slide
from domoxml.types import OutputFormat, SlideSize

pytestmark = pytest.mark.integration


def test_render_png_returns_a_real_image() -> None:
    deck = Presentation(size=SlideSize.WIDE_16_9)
    deck.add(Slide(html="<h1 style='color:#e11'>Hello</h1>"))
    result = deck.render({OutputFormat.PNG})

    assert len(result.pngs) == 1
    assert result.pngs[0].startswith(b"\x89PNG\r\n\x1a\n")  # PNG magic number
    assert result.pptx is None and result.html is None


def test_render_one_png_per_slide() -> None:
    deck = Presentation()
    deck.add(Slide(html="<p>one</p>")).add(Slide(html="<p>two</p>"))
    result = deck.render({OutputFormat.PNG})
    assert len(result.pngs) == 2


def test_indices_limits_to_selected_slides() -> None:
    deck = Presentation()
    deck.add(Slide(html="<p>a</p>")).add(Slide(html="<p>b</p>")).add(Slide(html="<p>c</p>"))
    result = deck.render({OutputFormat.PNG}, indices={1})
    assert len(result.pngs) == 1
