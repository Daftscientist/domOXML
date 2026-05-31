"""Unit tests for the render layer that need no browser."""

from __future__ import annotations

import pytest

from domoxml import Presentation, Slide
from domoxml.core.render.page import compile_theme, compose_page
from domoxml.core.units import pixels, px_to_emu
from domoxml.types import CustomSize, OutputFormat, SlideSize, Theme


def test_pixels_for_presets() -> None:
    assert pixels(SlideSize.WIDE_16_9) == (1280, 720)
    assert pixels(SlideSize.STANDARD_4_3) == (960, 720)


def test_pixels_for_custom_size() -> None:
    assert pixels(CustomSize(width_in=10, height_in=5)) == (960, 480)


def test_px_to_emu() -> None:
    assert px_to_emu(96) == 914_400


def test_compile_theme_emits_root_vars() -> None:
    css = compile_theme(Theme())
    assert ":root{" in css
    assert "--accent:" in css
    assert "--font-body:" in css


def test_compose_page_is_sized_and_embeds_the_slide() -> None:
    html = compose_page("<h1>hi</h1>", css=None, theme=Theme(), width_px=1280, height_px=720)
    assert html.startswith("<!doctype html>")
    assert "1280px" in html
    assert "720px" in html
    assert "<h1>hi</h1>" in html


def test_pptx_on_empty_deck_is_none_without_a_browser() -> None:
    # No slides → nothing to render → no browser launched, pptx is None (graceful).
    assert Presentation().render({OutputFormat.PPTX}).pptx is None


def test_out_of_range_indices_raise_clearly() -> None:
    deck = Presentation()
    deck.add(Slide(html="<p>only one</p>"))
    with pytest.raises(IndexError):
        deck.render({OutputFormat.PNG}, indices={5})


@pytest.mark.parametrize(
    ("width_px", "height_px"),
    [(0, 720), (-1, 720), (1280, 0), (1280, -100), (0, 0)],
)
def test_compose_page_rejects_nonpositive_dimensions(width_px: int, height_px: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        compose_page("<p>x</p>", css=None, theme=Theme(), width_px=width_px, height_px=height_px)


def test_theme_values_cannot_break_the_root_block() -> None:
    hostile = Theme.model_validate({"palette": {"accent": "red; } body { display:none"}})
    css = compile_theme(hostile)
    assert css.count("{") == 1 and css.count("}") == 1  # still one clean :root block
