#!/usr/bin/env python3
"""Measure which CSS features still take a raster path, one fixture per feature.

A raster fallback is a choice, not content: wherever a feature has a native DrawingML form it
should not be baked. This renders one small fixture per feature through the real pipeline and
counts how many outputs are not native, so the number can only go down. The fixtures live in
``fidelity/raster-cases.json`` and ``fidelity/raster-ledger.json`` is the committed baseline.
``--check`` fails if any case got worse (more rasters, or a visibly worse render) and
``--update`` records an improvement. Native is not the same as faithful, so each case is also
scored against Chrome. Inherently raster content (canvas, iframe, procedural filters) is
listed too and is expected to stay.

    python scripts/raster_ledger.py                # print the table
    python scripts/raster_ledger.py --check        # CI: fail on a regression
    python scripts/raster_ledger.py --update       # record improvements
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from domoxml import Presentation, Slide
from domoxml.core.fidelity.libreoffice import render_pptx_to_pngs
from domoxml.core.fidelity.score import compare
from domoxml.core.ir import extract_slide
from domoxml.core.render import BrowserSession, compose_page
from domoxml.types import OutputFormat, Theme

FIDELITY = Path(__file__).resolve().parent.parent / "fidelity"
BASELINE = FIDELITY / "raster-ledger.json"
CASES_FILE = FIDELITY / "raster-cases.json"
NATIVE = {"native", "decomposed", "layered"}
LOOKS_RIGHT = 0.97
LOOK_TOLERANCE = 0.02
BOX = "position:absolute;left:200px;top:150px;width:360px;height:220px;"


def load_cases() -> dict[str, tuple[str, bool]]:
    """Fixtures from ``fidelity/raster-cases.json``; ``{BOX}`` expands to a standard box."""
    raw: dict[str, dict[str, object]] = json.loads(CASES_FILE.read_text())
    return {
        name: (str(case["html"]).replace("{BOX}", BOX), bool(case["inherent"]))
        for name, case in raw.items()
    }


async def measure() -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    async with BrowserSession() as session:
        for name, (html, inherent) in load_cases().items():
            page = compose_page(html, css=None, theme=Theme(), width_px=1280, height_px=720)
            extracted = extract_slide(await session.render(page, width=1280, height=720))
            rasters = [
                item for item in extracted.coverage if item.representation.value not in NATIVE
            ]
            results[name] = {
                "non_native": len(rasters),
                "inherent": inherent,
                "reasons": sorted({item.reason or item.representation.value for item in rasters})[
                    :3
                ],
                "similarity": await similarity(html),
            }
    return results


async def similarity(html: str) -> float:
    """How closely LibreOffice's render of the PPTX matches Chrome's, 0..1.

    Native is not the same as faithful: a feature can be dropped without a raster, so a case only
    counts as done when it also looks right.
    """
    deck = Presentation().add(Slide(html=html))
    rendered = await deck.arender({OutputFormat.PPTX, OutputFormat.PNG})
    assert rendered.pptx is not None and rendered.pngs
    candidate = render_pptx_to_pngs(rendered.pptx)[0]
    report = compare(rendered.pngs[0], candidate)
    return round(min(report.similarity, report.regional_similarity), 3)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="fail if any case regressed")
    parser.add_argument("--update", action="store_true", help="record improvements in the baseline")
    arguments = parser.parse_args()
    results = asyncio.run(measure())
    baseline: dict[str, dict[str, object]] = (
        json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    )
    width = max(map(len, results))
    worse: list[str] = []
    for name, result in results.items():
        before = baseline.get(name, {}).get("non_native")
        before_look = baseline.get(name, {}).get("similarity")
        now = result["non_native"]
        look = result["similarity"]
        mark = "native" if now == 0 else ("inherent" if result["inherent"] else "RASTER")
        flag = "  LOOKS WRONG" if isinstance(look, float) and look < LOOKS_RIGHT else ""
        note = "" if before is None or before == now else f"  (baseline {before})"
        print(f"{name:{width}}  {now}  {mark:8}  look {look:.3f}{flag}{note}")
        if isinstance(before, int) and isinstance(now, int) and now > before:
            worse.append(name)
        if (
            isinstance(before_look, float)
            and isinstance(look, float)
            and look < before_look - LOOK_TOLERANCE
        ):
            worse.append(f"{name} (looks worse)")
    total = sum(int(r["non_native"]) for r in results.values() if not r["inherent"])  # type: ignore[call-overload]
    print(f"\nnon-native outputs on features that have a native form: {total}")
    if arguments.update:
        BASELINE.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        print(f"wrote {BASELINE}")
    if arguments.check and worse:
        print("REGRESSED:", ", ".join(worse), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
