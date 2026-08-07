"""End-to-end render tests. Require Chromium: ``playwright install chromium``."""

from __future__ import annotations

import http.server
import threading

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


def test_render_html_returns_per_slide_browser_fragments() -> None:
    deck = Presentation(css="h1{letter-spacing:1px}")
    deck.add(Slide(html="<h1>Coffee that tastes like <em>calm</em>.</h1>"))
    result = deck.render({OutputFormat.HTML})

    assert result.html is not None
    assert len(result.html.slides) == 1
    assert "domoxml-slide" in result.html.slides[0].html
    assert "Coffee that tastes like " in result.html.slides[0].html
    assert "calm" in result.html.slides[0].html
    assert result.coverage.items

    round_trip = Presentation(css=result.html.css)
    round_trip.add(Slide(html=result.html.slides[0].html))
    rendered = round_trip.render({OutputFormat.PNG})
    assert rendered.pngs[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_render_never_reaches_the_network() -> None:
    """Every way a URL can end up fetched by the renderer — img src, legacy `background=`,
    SVG `fill="url(...)"`, CSS `background-image` — must never leave the process, even when
    it points at a real, reachable local server."""
    received: list[str] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = f"http://127.0.0.1:{server.server_address[1]}/probe.png"
        html = f"""
        <table background="{target}"><tr><td>legacy attr</td></tr></table>
        <img src="{target}">
        <div style="width:10px;height:10px;background-image:url({target})"></div>
        <svg width="10" height="10"><rect width="10" height="10" fill="url({target})"/></svg>
        """
        deck = Presentation(size=SlideSize.WIDE_16_9)
        deck.add(Slide(html=html))
        result = deck.render({OutputFormat.PNG})
        assert result.pngs[0].startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert received == []
