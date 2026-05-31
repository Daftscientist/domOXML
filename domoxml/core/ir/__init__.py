"""The Normalized IR — a format-agnostic scene the resolver/backends consume.

The extractor turns a :class:`~domoxml.core.render.RenderedSlide` (Chromium's computed
layout) into a :class:`SlideIR` plus per-element coverage and warnings (:class:`ExtractResult`).
Positions are in EMUs, ready for OOXML. v0 models the canvas (positioned boxes + text);
flow nodes for docs come later.
"""

from domoxml.core.ir.extract import ExtractResult, extract_slide
from domoxml.core.ir.model import (
    Box,
    Fill,
    GradientFill,
    GradientStop,
    Line,
    PictureFill,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)

__all__ = [
    "Box",
    "ExtractResult",
    "Fill",
    "GradientFill",
    "GradientStop",
    "Line",
    "PictureFill",
    "Rgba",
    "Shadow",
    "ShapeNode",
    "SlideIR",
    "SolidFill",
    "TextBody",
    "TextParagraph",
    "TextRun",
    "extract_slide",
]
