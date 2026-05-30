"""The render layer — drive headless Chromium to rasterise a slide and capture its
computed layout. The single source of truth all outputs (PNG, and later the .pptx
decoration layer + the IR) derive from.
"""

from domoxml.core.render.browser import BrowserSession, RenderedNode, RenderedSlide
from domoxml.core.render.page import compile_theme, compose_page

__all__ = [
    "BrowserSession",
    "RenderedNode",
    "RenderedSlide",
    "compile_theme",
    "compose_page",
]
