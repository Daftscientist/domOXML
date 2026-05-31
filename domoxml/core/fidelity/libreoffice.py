"""Render a ``.pptx`` to per-slide PNGs via headless LibreOffice — the fidelity gate's
candidate-render backend. Optional: requires LibreOffice (``soffice``) and poppler
(``pdftoppm``) on PATH. Local/CI only; never imported on the core render path.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from domoxml.core.fidelity._poppler import pdf_to_pngs


def libreoffice_binary() -> str | None:
    """Path to the LibreOffice CLI (``soffice``/``libreoffice``), or ``None`` if absent."""
    return shutil.which("soffice") or shutil.which("libreoffice")


def has_libreoffice() -> bool:
    """True when LibreOffice is available for the fidelity gate."""
    return libreoffice_binary() is not None


def render_pptx_to_pdf(pptx: bytes, *, timeout: float = 120.0) -> bytes:
    """Convert ``pptx`` to a single PDF via headless LibreOffice."""
    soffice = libreoffice_binary()
    if soffice is None:
        raise RuntimeError(
            "LibreOffice not found — install libreoffice-impress for the fidelity gate"
        )

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "deck.pptx").write_bytes(pptx)
        # Per-invocation user profile so concurrent renders don't contend on the shared
        # LibreOffice profile/lock.
        profile = f"-env:UserInstallation=file://{work / 'lo_profile'}"
        subprocess.run(
            [
                soffice,
                profile,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work),
                str(work / "deck.pptx"),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        pdf = work / "deck.pdf"
        if not pdf.exists():
            raise RuntimeError("LibreOffice did not produce a PDF")
        return pdf.read_bytes()


def render_pptx_to_pngs(pptx: bytes, *, dpi: int = 96, timeout: float = 120.0) -> list[bytes]:
    """Render each slide of ``pptx`` to a PNG via LibreOffice (→ PDF) + poppler (→ PNGs)."""
    pdf = render_pptx_to_pdf(pptx, timeout=timeout)
    return pdf_to_pngs(pdf, dpi=dpi, timeout=timeout)
