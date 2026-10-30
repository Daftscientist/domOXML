"""Takumi renderer contract tests; no Node packages or Chromium required."""

from __future__ import annotations

import json

import pytest

from domoxml import Presentation
from domoxml.core.ir.model import PictureFill, SolidFill
from domoxml.core.render.takumi_backend import (
    TakumiRenderedSlide,
    TakumiRenderError,
    _decode_worker_reply,
    extract_takumi,
)
from domoxml.types import Editability, Representation


def test_takumi_selection_is_explicit_and_chromium_remains_default() -> None:
    assert Presentation().render_engine == "chromium"
    assert Presentation(render_engine="takumi").render_engine == "takumi"
    with pytest.raises(ValueError, match="unsupported render_engine"):
        Presentation(render_engine="unknown")  # type: ignore[arg-type]


def test_takumi_css_parse_failure_retains_engine_message_and_stage() -> None:
    message = (
        "invalid value for transform: string 'rotate(18deg) skew(-12deg)': "
        "Unexpected token"
    )
    payload = json.dumps({"ok": False, "stage": "paint", "message": message}).encode()
    with pytest.raises(TakumiRenderError, match="Takumi paint failed") as error:
        _decode_worker_reply(payload, b"", 1)
    assert error.value.stage == "paint"
    assert error.value.detail == message
    assert message in str(error.value)


def test_worker_crash_surfaces_stderr_instead_of_a_generic_raster_warning() -> None:
    with pytest.raises(TakumiRenderError, match="module not found"):
        _decode_worker_reply(b"", b"module not found", 1)


def test_simple_takumi_fill_is_native() -> None:
    slide = TakumiRenderedSlide(
        png=b"image",
        width=1280,
        height=720,
        steps=({
            "type": "fill",
            "bounds": {"x": 40, "y": 60, "width": 180, "height": 90},
            "color": [79, 70, 229, 255],
        },),
    )
    result = extract_takumi(slide)
    assert len(result.slide.shapes) == 1
    fill = result.slide.shapes[0].fill
    assert isinstance(fill, SolidFill)
    assert fill.color.hex == "4F46E5"
    assert result.coverage[0].representation is Representation.NATIVE
    assert not result.warnings


def test_text_is_native_and_remains_editable() -> None:
    slide = TakumiRenderedSlide(
        png=b"image",
        width=1280,
        height=720,
        steps=({
            "type": "text", "text": "Hello", "x": 40, "y": 50,
            "width": 240, "height": 38, "fontSize": 32,
            "fontFamily": "Geist", "fontWeight": 700, "fontStyle": "normal",
            "color": [12, 23, 34, 255],
        },),
    )
    result = extract_takumi(slide)
    text = result.slide.shapes[0].text
    assert text is not None
    assert text.paragraphs[0].runs[0].text == "Hello"
    assert text.paragraphs[0].runs[0].bold is True
    assert result.coverage[0].editability is Editability.SEMANTIC


def test_unsupported_effect_never_crops_a_composited_region() -> None:
    """The already extracted native fill must not be doubled below a raster crop."""
    slide = TakumiRenderedSlide(
        png=b"authoritative-slide-png",
        width=1280,
        height=720,
        steps=(
            {"type": "fill",
             "bounds": {"x": 30, "y": 40, "width": 200, "height": 90},
             "color": [30, 40, 50, 255]},
            {"type": "unsupported", "reason": "backdrop-filter compositing"},
        ),
    )
    result = extract_takumi(slide)
    assert len(result.slide.shapes) == 1
    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.slide.shapes[0].fill.data == slide.png
    assert result.coverage[0].representation is Representation.RASTERIZED
    assert result.coverage[0].editability is Editability.NONE
    assert "backdrop-filter" in result.warnings[0].message


def test_bad_native_step_fails_closed_to_whole_slide_raster() -> None:
    slide = TakumiRenderedSlide(
        png=b"authoritative-slide-png",
        width=1280,
        height=720,
        steps=({"type": "fill", "bounds": {}, "color": [1, 2, 3, 255]},),
    )
    result = extract_takumi(slide)
    assert result.coverage[0].representation is Representation.RASTERIZED
    assert len(result.slide.shapes) == 1
