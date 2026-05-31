"""Fidelity scoring — measure how closely a rendered ``.pptx`` matches its source render.

``compare`` is pure (Pillow only) and always available. The render backends turn a built
``.pptx`` into the candidate PNGs to score against the source render: ``libreoffice`` (the
default, CI gate) and ``graph`` (optional, bring-your-own Microsoft 365 credentials — real
PowerPoint fidelity). Together they're the measured fidelity gate the project's methodology
calls for.
"""

from domoxml.core.fidelity._poppler import has_poppler, pdf_to_pngs
from domoxml.core.fidelity.graph import (
    device_login,
    has_graph_auth,
    render_pptx_to_pngs_via_graph,
)
from domoxml.core.fidelity.libreoffice import (
    has_libreoffice,
    render_pptx_to_pdf,
    render_pptx_to_pngs,
)
from domoxml.core.fidelity.score import FidelityReport, compare

__all__ = [
    "FidelityReport",
    "compare",
    "device_login",
    "has_graph_auth",
    "has_libreoffice",
    "has_poppler",
    "pdf_to_pngs",
    "render_pptx_to_pdf",
    "render_pptx_to_pngs",
    "render_pptx_to_pngs_via_graph",
]
