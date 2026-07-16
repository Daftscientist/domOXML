"""Shared helpers for compiling reverse HTML back into a presentation."""

from __future__ import annotations

import base64
import mimetypes

from domoxml.presentation import Presentation, Slide
from domoxml.types import CustomSize, HtmlPresentation, OutputFormat, RenderResult


def inline_assets(html: HtmlPresentation) -> HtmlPresentation:
    """Replace reverse-output asset paths with data URLs for an in-memory browser render."""
    css = html.css
    slides: list[str] = [slide.html for slide in html.slides]
    for asset in html.assets:
        mime = mimetypes.guess_type(asset.path)[0] or "application/octet-stream"
        encoded = base64.b64encode(asset.data).decode("ascii")
        data_url: str = f"data:{mime};base64,{encoded}"
        references: tuple[str, str] = (f"../{asset.path}", asset.path)
        for reference in references:
            css = css.replace(reference, data_url)
            slides = [source.replace(reference, data_url) for source in slides]
    return html.model_copy(
        update={
            "css": css,
            "slides": tuple(
                slide.model_copy(update={"html": source})
                for slide, source in zip(html.slides, slides, strict=True)
            ),
            "assets": (),
        }
    )


def render_html_roundtrip(html: HtmlPresentation) -> RenderResult:
    """Compile every reverse HTML slide back to browser PNG and editable PPTX outputs."""
    html = inline_assets(html)
    first = html.slides[0]
    deck = Presentation(
        css=html.css,
        size=CustomSize(width_in=first.width_px / 96, height_in=first.height_px / 96),
    )
    for slide in html.slides:
        deck.add(
            Slide(
                html=slide.html,
                size=CustomSize(width_in=slide.width_px / 96, height_in=slide.height_px / 96),
            )
        )
    return deck.render({OutputFormat.PNG, OutputFormat.PPTX})
