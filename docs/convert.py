# Pyodide bootstrap + dispatch for the domOXML browser demo (index.html).
# The page fetches this file and runs it with runPythonAsync after loadPackage.
#
# Publish build: no wheels. The domoxml package and defusedxml ship as loose
# source files under pkg/ (listed in pkg/manifest.json). Fetch each one with a
# relative URL, write it into Pyodide's filesystem preserving layout, and put
# the pkg root on sys.path. lxml / pydantic / pillow / fonttools come from
# Pyodide's own package loading, exactly as in the wheel build.
import asyncio
import base64
import json
import os
import sys

from pyodide.http import pyfetch

_PKG_ROOT = "/pkg"


async def _load_sources() -> None:
    manifest = await (await pyfetch("pkg/manifest.json")).json()

    async def _one(path: str) -> None:
        data = await (await pyfetch(f"pkg/{path}")).bytes()
        dest = f"{_PKG_ROOT}/{path}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)

    await asyncio.gather(*(_one(path) for path in manifest["files"]))
    if _PKG_ROOT not in sys.path:
        sys.path.insert(0, _PKG_ROOT)


await _load_sources()

from domoxml.core.render.page import compose_page
from domoxml.core.render.web import compose_pptx, open_session
from domoxml.types import CoverageReport, Representation, Theme
from domoxml.web import aconvert, aread_deck

RESULT_JSON = ""
RESULT_PPTX = None
RESULT_REEMIT = None


def _report(items, warnings):
    report = CoverageReport(items=list(items))
    return {
        "coverage_items": len(report.items),
        "native_ratio": report.native_ratio,
        "editable_ratio": report.editable_ratio,
        "non_native": [
            item.element
            for item in report.items
            if item.representation
            not in (Representation.NATIVE, Representation.DECOMPOSED)
        ],
        "warnings": [str(w) for w in warnings],
    }


def _theme():
    raw = globals().get("ARG_THEME")
    return Theme(**json.loads(raw)) if raw else Theme()


async def _dispatch(name):
    global RESULT_JSON, RESULT_PPTX, RESULT_REEMIT
    RESULT_JSON, RESULT_PPTX, RESULT_REEMIT = "", None, None
    if name == "convert":
        fragments = json.loads(ARG_FRAGMENTS)
        theme = _theme()
        width, height = int(ARG_W), int(ARG_H)
        pptx, items, warnings = await aconvert(
            fragments, width=width, height=height, theme=theme
        )
        pages = [
            compose_page(f, css=None, theme=theme, width_px=width, height_px=height)
            for f in fragments
        ]
        RESULT_PPTX = pptx
        RESULT_JSON = json.dumps(
            {"report": _report(items, warnings), "pages": pages}
        )
    elif name == "fragment":
        # Single-slide low-level path (spike checks): exposes the capture details
        # aconvert aggregates away — raster count, slide PNG size, node count.
        theme = _theme()
        width, height = int(ARG_W), int(ARG_H)
        page = compose_page(
            ARG_FRAGMENT, css=None, theme=theme, width_px=width, height_px=height
        )
        async with open_session() as session:
            slide = await session.render(page, width=width, height=height)
        pptx, items, warnings = compose_pptx([slide])
        report = _report(items, warnings)
        report["nodes_captured"] = len(slide.nodes)
        report["rasters_used"] = len(slide.rasters)
        report["resources_captured"] = len(slide.resources)
        report["slide_png_bytes"] = len(slide.png)
        RESULT_PPTX = pptx
        RESULT_JSON = json.dumps({"report": report, "pages": [page]})
    elif name == "read":
        result = await aread_deck(base64.b64decode(ARG_PPTX_B64))
        coverage = result["coverage"]
        RESULT_REEMIT = result["reemitted_pptx"]
        RESULT_JSON = json.dumps(
            {
                "slides": [
                    {"html": s.html, "width_px": s.width_px, "height_px": s.height_px}
                    for s in result["display_slides"]
                ],
                "css": result["display_css"],
                "warnings": [str(w) for w in result["warnings"]],
                "coverage": {
                    "items": len(coverage.items),
                    "native_ratio": coverage.native_ratio,
                    "editable_ratio": coverage.editable_ratio,
                },
                "reemitted": RESULT_REEMIT is not None,
            }
        )
    else:
        raise ValueError(f"unknown dispatch: {name}")
