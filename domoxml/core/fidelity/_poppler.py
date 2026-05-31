"""Rasterise a PDF to per-slide PNGs via poppler (``pdftoppm``) — shared by the fidelity
backends. Each backend (LibreOffice, Graph) produces a PDF; this turns it into one PNG per
page. Optional: requires poppler-utils on PATH. Local/CI only; never on the core render path.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_SLIDE_INDEX_RE = re.compile(r"slide-(\d+)\.png$")


def _page_index(path: Path) -> int:
    match = _SLIDE_INDEX_RE.search(path.name)
    return int(match.group(1)) if match else 0


def has_poppler() -> bool:
    """True when poppler's ``pdftoppm`` is available."""
    return shutil.which("pdftoppm") is not None


def pdf_to_pngs(pdf: bytes, *, dpi: int = 96, timeout: float = 120.0) -> list[bytes]:
    """Render each page of ``pdf`` to a PNG via poppler's ``pdftoppm``."""
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        raise RuntimeError("poppler not found — install poppler-utils for the fidelity gate")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "deck.pdf").write_bytes(pdf)
        subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), str(work / "deck.pdf"), str(work / "slide")],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        # Sort by numeric page index (don't rely on pdftoppm's zero-padding).
        pages = sorted(work.glob("slide-*.png"), key=_page_index)
        return [path.read_bytes() for path in pages]
