"""Slides backend — assemble :class:`SlideIR` into a PresentationML ``.pptx``."""

from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx, read_pptx_result
from domoxml.slides.validation import validate_pptx_package

__all__ = ["build_pptx", "read_pptx", "read_pptx_result", "validate_pptx_package"]
