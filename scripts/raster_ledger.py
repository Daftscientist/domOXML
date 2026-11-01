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
# A layered output holds raster content (types.CoverageItem requires a raster area), so it counts.
NATIVE = {"native", "decomposed"}
LOOKS_RIGHT = 0.97
# Text scores depend on which fonts the machine has: text-shadow measured 0.891 locally and 0.848
# in CI. The tolerance absorbs that noise yet still catches a real loss (gradient text 0.98 -> 0.34).
LOOK_TOLERANCE = 0.08
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
    return round(min(report.similarity, report.regional_similarity, report.focused_similarity), 3)


def compare_to_baseline(
    results: dict[str, dict[str, object]], baseline: dict[str, dict[str, object]]
) -> list[str]:
    """Everything wrong relative to the baseline: regressions, and any case it does not cover."""
    problems: list[str] = []
    for name in sorted(set(results) - set(baseline)):
        problems.append(f"{name}: no baseline entry (run --update after reviewing it)")
    for name in sorted(set(baseline) - set(results)):
        problems.append(f"{name}: baseline entry has no fixture")
    for name, result in results.items():
        before = baseline.get(name)
        if before is None:
            continue
        old_count, old_look = before.get("non_native"), before.get("similarity")
        count, look = result["non_native"], result["similarity"]
        if not isinstance(old_count, int) or not isinstance(old_look, float):
            problems.append(f"{name}: baseline entry is incomplete")
            continue
        if isinstance(count, int) and count > old_count:
            problems.append(f"{name}: {count} non-native outputs, baseline {old_count}")
        if isinstance(look, float) and look < old_look - LOOK_TOLERANCE:
            problems.append(f"{name}: looks worse ({look:.3f}, baseline {old_look:.3f})")
        if result.get("dropped"):
            problems.append(f"{name}: its text effect is missing from the IR")
    return problems


def improved(
    results: dict[str, dict[str, object]], baseline: dict[str, dict[str, object]]
) -> dict[str, dict[str, object]]:
    """The baseline with each metric moved only in the better direction."""
    merged: dict[str, dict[str, object]] = {}
    for name, result in results.items():
        entry = dict(result)
        before = baseline.get(name)
        if before is not None:
            old_count, old_look = before.get("non_native"), before.get("similarity")
            if isinstance(old_count, int) and isinstance(entry["non_native"], int):
                entry["non_native"] = min(old_count, entry["non_native"])
            if isinstance(old_look, float) and isinstance(entry["similarity"], float):
                entry["similarity"] = max(old_look, entry["similarity"])
        merged[name] = entry
    return merged


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
    for name, result in results.items():
        count, look = result["non_native"], result["similarity"]
        mark = "native" if count == 0 else ("inherent" if result["inherent"] else "RASTER")
        flag = "  LOOKS WRONG" if isinstance(look, float) and look < LOOKS_RIGHT else ""
        if result.get("dropped"):
            flag += "  DROPPED (effect missing from the IR)"
        print(f"{name:{width}}  {count}  {mark:8}  look {look:.3f}{flag}")
    total = sum(int(r["non_native"]) for r in results.values() if not r["inherent"])  # type: ignore[call-overload]
    print(f"\nnon-native outputs on features that have a native form: {total}")
    problems = compare_to_baseline(results, baseline)
    if arguments.update:
        regressions = [p for p in problems if "no baseline entry" not in p]
        if regressions:
            print("refusing to record a regression:", *regressions, sep="\n  ", file=sys.stderr)
            return 1
        BASELINE.write_text(
            json.dumps(improved(results, baseline), indent=2, sort_keys=True) + "\n"
        )
        print(f"wrote {BASELINE}")
        return 0
    if arguments.check and problems:
        print("ledger check failed:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
