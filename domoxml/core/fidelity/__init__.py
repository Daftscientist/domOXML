"""Fidelity scoring — measure how closely a rendered ``.pptx`` matches its source render.

``compare`` is pure (Pillow only) and always available. ``render_pptx_to_pngs`` is the
optional, LibreOffice-backed gate that produces the candidate render to score against the
source. Together they're the measured fidelity gate the project's methodology calls for.
"""

from domoxml.core.fidelity.libreoffice import has_libreoffice, render_pptx_to_pngs
from domoxml.core.fidelity.score import FidelityReport, compare

__all__ = ["FidelityReport", "compare", "has_libreoffice", "render_pptx_to_pngs"]
