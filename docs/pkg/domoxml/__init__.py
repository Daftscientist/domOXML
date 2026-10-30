"""domOXML — transpile HTML/CSS into editable OOXML (PowerPoint first)."""

from __future__ import annotations

from domoxml.presentation import Presentation, pptx_to_html
from domoxml.types import Slide

__version__ = "0.1.0a0"

__all__ = ["Presentation", "Slide", "__version__", "pptx_to_html"]
