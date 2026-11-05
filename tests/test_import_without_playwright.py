"""domOXML imports and converts PPTX without Playwright installed (browser runtimes, e.g. Pyodide).

Only HTML capture needs a browser; reading, writing and serializing must not import Playwright.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "real-decks" / "pptx" / "external-image-crop" / "source.pptx"

SCRIPT = f"""
import sys
# Make any attempt to import Playwright fail, exactly as on a runtime that doesn't ship it.
sys.modules["playwright"] = None
sys.modules["playwright.async_api"] = None
from pathlib import Path
import domoxml
from domoxml import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result
data = Path({str(DECK)!r}).read_bytes()
result = read_pptx_result(data)
assert result.slides, "no slides read"
assert pptx_to_html(data).slides, "no HTML slides"
assert build_pptx(list(result.slides)).startswith(b"PK"), "not a zip package"
print("ok")
"""


def test_pptx_paths_work_without_playwright() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "ok"
