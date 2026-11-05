"""Presentation only takes a full-page screenshot when PNG output is requested.

PPTX and normalized HTML need the captured layout, not the page pixels; isolated rasters and
backdrops are captured separately by the render session.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, ClassVar, Self

import pytest

import domoxml.presentation as presentation
from domoxml import Presentation
from domoxml.core.render import RenderedSlide
from domoxml.types import OutputFormat, Slide


class _RecordingSession:
    calls: ClassVar[list[dict[str, Any]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc: type[BaseException] | None, value: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    async def render(self, html: str, **kwargs: Any) -> RenderedSlide:
        _RecordingSession.calls.append(kwargs)
        png = b"\x89PNG" if kwargs.get("capture_png", True) else None
        return RenderedSlide(png=png, width=kwargs["width"], height=kwargs["height"], nodes=())


@pytest.mark.parametrize(
    ("formats", "expect_png"),
    [
        ({OutputFormat.PPTX}, False),
        ({OutputFormat.HTML}, False),
        ({OutputFormat.PNG}, True),
        ({OutputFormat.PPTX, OutputFormat.PNG}, True),
    ],
)
def test_full_page_screenshot_only_for_png(
    monkeypatch: pytest.MonkeyPatch, formats: set[OutputFormat], expect_png: bool
) -> None:
    _RecordingSession.calls = []
    monkeypatch.setattr(presentation, "BrowserSession", _RecordingSession)
    deck = Presentation().add(Slide(html="<p>hi</p>"))
    result = deck.render(formats)
    assert _RecordingSession.calls, "render was not called"
    assert all(c.get("capture_png", True) is expect_png for c in _RecordingSession.calls)
    assert bool(result.pngs) is expect_png
