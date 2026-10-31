"""The native-recipe lab must never report stale results or upload when told not to."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

LAB_PATH = Path(__file__).resolve().parent.parent / "scripts" / "native_lab.py"


@pytest.fixture
def lab(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("native_lab_under_test", LAB_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path)
    return module


def test_render_discards_a_previous_run_instead_of_reporting_it(
    lab: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A candidate Office now rejects must not be shown as its earlier, valid render.
    (tmp_path / "gp-probe.pdf").write_bytes(b"%PDF stale")
    (tmp_path / "gp-probe.png").write_bytes(b"stale png")
    (tmp_path / "lo-probe.png").write_bytes(b"stale png")
    graph_tool = tmp_path / "graph_render.py"
    graph_tool.write_text("")
    monkeypatch.setattr(lab, "GRAPH_TOOL", graph_tool)
    asked: list[Path] = []

    def reject(path: Path) -> str:
        asked.append(path)
        return "PPTCannotOpenFileMetroFileCorruption"

    monkeypatch.setattr(lab, "office_error", reject)

    # Neither LibreOffice nor Graph produces anything this time.
    def nothing_produced(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=1)

    monkeypatch.setattr(subprocess, "run", nothing_produced)

    made = lab.render(tmp_path / "probe.pptx", graph=True)

    assert made == [], "nothing from this run succeeded, so nothing may be reported"
    assert asked == [tmp_path / "probe.pptx"], "Office's rejection is surfaced, not hidden"
    assert not (tmp_path / "gp-probe.pdf").exists()
    assert not (tmp_path / "gp-probe.png").exists()
    assert not (tmp_path / "lo-probe.png").exists()


def test_no_graph_flag_stops_the_blur_scale_probe_from_calling_real_powerpoint(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("an upload or render was attempted despite --no-graph")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(lab, "office_error", forbidden)
    monkeypatch.setattr(lab, "_GRAPH", False)

    lab.probe_blur_scale()
