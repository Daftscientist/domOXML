"""The Normalized IR — a format-agnostic scene the resolver/backends consume.

The extractor turns a :class:`~domoxml.core.render.RenderedSlide` (Chromium's computed
layout) into a :class:`SlideIR`. Positions are in EMUs, ready for OOXML. v0 models the
canvas (positioned boxes + text); flow nodes for docs come later.
"""

from domoxml.core.ir.extract import extract_slide
from domoxml.core.ir.model import Box, Rgba, ShapeNode, SlideIR, TextRun

__all__ = ["Box", "Rgba", "ShapeNode", "SlideIR", "TextRun", "extract_slide"]
