"""Slides backend — assemble :class:`SlideIR` into a PresentationML ``.pptx``."""

from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx

__all__ = ["build_pptx", "read_pptx"]
