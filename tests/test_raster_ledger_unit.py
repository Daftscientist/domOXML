"""The raster ledger's baseline logic must not be passable by accident."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

LEDGER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "raster_ledger.py"


@pytest.fixture
def ledger() -> ModuleType:
    spec = importlib.util.spec_from_file_location("raster_ledger_under_test", LEDGER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry(count: int, look: float, *, dropped: bool = False) -> dict[str, object]:
    return {"non_native": count, "similarity": look, "inherent": False, "dropped": dropped}


def test_a_case_without_a_baseline_entry_fails_the_check(ledger: Any) -> None:
    problems = ledger.compare_to_baseline({"new": entry(0, 1.0)}, {})
    assert any("new: no baseline entry" in problem for problem in problems)


def test_a_baseline_entry_without_a_fixture_fails_the_check(ledger: Any) -> None:
    problems = ledger.compare_to_baseline({}, {"gone": entry(0, 1.0)})
    assert any("gone: baseline entry has no fixture" in problem for problem in problems)


def test_an_incomplete_baseline_entry_fails_instead_of_being_skipped(ledger: Any) -> None:
    problems = ledger.compare_to_baseline({"x": entry(0, 1.0)}, {"x": {"non_native": 0}})
    assert any("incomplete" in problem for problem in problems)


def test_more_rasters_a_visibly_worse_render_and_a_dropped_effect_all_fail(ledger: Any) -> None:
    baseline = {"a": entry(0, 0.99), "b": entry(1, 0.99), "c": entry(0, 0.99)}
    results = {"a": entry(1, 0.99), "b": entry(1, 0.5), "c": entry(0, 0.99, dropped=True)}

    problems = ledger.compare_to_baseline(results, baseline)

    assert len(problems) == 3
    assert any("a: 1 non-native" in p for p in problems)
    assert any("b: looks worse" in p for p in problems)
    assert any("c: its text effect is missing" in p for p in problems)


def test_font_noise_inside_the_tolerance_is_not_a_regression(ledger: Any) -> None:
    assert ledger.compare_to_baseline({"t": entry(0, 0.848)}, {"t": entry(0, 0.891)}) == []


def test_update_moves_each_metric_only_in_the_better_direction(ledger: Any) -> None:
    baseline = {"a": entry(2, 0.90), "b": entry(1, 0.99)}
    results = {"a": entry(1, 0.80), "b": entry(3, 0.995)}

    merged = ledger.improved(results, baseline)

    assert (merged["a"]["non_native"], merged["a"]["similarity"]) == (1, 0.90)
    assert (merged["b"]["non_native"], merged["b"]["similarity"]) == (1, 0.995)


def test_layered_output_counts_as_raster(ledger: Any) -> None:
    assert "layered" not in ledger.NATIVE
