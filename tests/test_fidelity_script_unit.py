# pyright: reportPrivateUsage=false
"""Unit coverage for the fidelity CLI's CI contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from scripts import fidelity_check


def _corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    case = corpus / "case"
    case.mkdir(parents=True)
    (case / "slide.html").write_text("<p>test</p>")
    return corpus


def _unavailable(_backend: str) -> tuple[bool, str]:
    return False, "renderer unavailable"


def test_missing_backend_is_optional_for_local_runs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(fidelity_check, "_backend_available", _unavailable)

    result = fidelity_check.main(
        ["--corpus", str(_corpus(tmp_path)), "--out", str(tmp_path / "out")]
    )

    assert result == 0


def test_required_backend_fails_closed_and_writes_summary(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(fidelity_check, "_backend_available", _unavailable)
    out = tmp_path / "out"

    result = fidelity_check.main(
        [
            "--corpus",
            str(_corpus(tmp_path)),
            "--out",
            str(out),
            "--require-backend",
        ]
    )

    assert result == 2
    summary = json.loads((out / "summary.json").read_text())
    assert summary["scores"] == []
    assert summary["skipped"] == ["libreoffice: renderer unavailable"]


@pytest.mark.parametrize("message", fidelity_check._TRANSIENT_RENDER_ERRORS)
def test_render_case_retries_one_transient_browser_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch, message: str
) -> None:
    case = fidelity_check.load_corpus(_corpus(tmp_path))[0]
    attempts = 0

    def render(_case: object) -> tuple[tuple[bytes, ...], bytes]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(message)
        return ((b"source",), b"pptx")

    monkeypatch.setattr(fidelity_check, "_render_case", render)

    assert fidelity_check._render_case_with_retry(case) == ((b"source",), b"pptx")
    assert attempts == 2


def test_render_case_stops_after_one_transient_retry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    case = fidelity_check.load_corpus(_corpus(tmp_path))[0]
    attempts = 0

    def render(_case: object) -> tuple[tuple[bytes, ...], bytes]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Page.captureScreenshot: Unable to capture screenshot")

    monkeypatch.setattr(fidelity_check, "_render_case", render)

    with pytest.raises(RuntimeError, match="Unable to capture screenshot"):
        fidelity_check._render_case_with_retry(case)
    assert attempts == 2


def test_render_case_does_not_retry_non_transient_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    case = fidelity_check.load_corpus(_corpus(tmp_path))[0]
    attempts = 0

    def render(_case: object) -> tuple[tuple[bytes, ...], bytes]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("invalid PPTX package")

    monkeypatch.setattr(fidelity_check, "_render_case", render)

    with pytest.raises(RuntimeError, match="invalid PPTX package"):
        fidelity_check._render_case_with_retry(case)
    assert attempts == 1


def test_markdown_summary_contains_both_fidelity_gates(tmp_path: Path) -> None:
    score = fidelity_check.SlideScore(
        case="table",
        backend="libreoffice",
        slide=0,
        similarity=0.99,
        regional_similarity=0.98,
        focused_similarity=0.96,
        perceptible_ratio=0.01,
        threshold=0.95,
        regional_threshold=0.97,
        focused_threshold=0.94,
    )

    fidelity_check._write_summary([score], [], tmp_path)

    markdown = (tmp_path / "summary.md").read_text()
    assert "| Similarity | Regional | Focused |" in markdown
    assert "| 0.950 | 0.970 |" not in markdown
    assert "| 0.95 | 0.97 | 0.94 |" in markdown
