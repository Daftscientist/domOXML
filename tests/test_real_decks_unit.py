"""Contracts for the pinned representative PPTX corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from domoxml.core.real_decks import (
    RealDeckCase,
    load_real_decks,
    validate_opc_package,
    validate_real_deck,
)
from domoxml.presentation import Presentation


def test_repository_real_decks_have_valid_pins_and_relationships() -> None:
    cases = load_real_decks(Path("real-decks/pptx"))

    assert {case.id for case in cases} == {
        "external-chart-preservation",
        "external-embedded-font",
        "external-image-crop",
        "external-table-style",
    }
    for case in cases:
        assert hashlib.sha256(case.pptx).hexdigest() == case.provenance.sha256
        assert validate_opc_package(case.pptx) == ()


def test_repository_real_decks_match_reverse_contracts() -> None:
    for case in load_real_decks(Path("real-decks/pptx")):
        assert validate_real_deck(case, Presentation.from_pptx(case.pptx)) == ()


def test_real_deck_requires_visual_gate_or_exclusion() -> None:
    raw = {
        "id": "missing-visual-contract",
        "pptx": b"pptx",
        "provenance": {
            "source_url": "https://example.test/deck.pptx",
            "source_revision": "abc",
            "license": "MIT",
            "sha256": "0" * 64,
        },
        "package": {"slides": 1},
        "reverse": {},
    }

    with pytest.raises(ValidationError, match="visual floors or one visual_exclusion"):
        RealDeckCase.model_validate(raw)


def test_real_deck_rejects_out_of_range_visual_slide() -> None:
    raw = {
        "id": "bad-slide",
        "pptx": b"pptx",
        "provenance": {
            "source_url": "https://example.test/deck.pptx",
            "source_revision": "abc",
            "license": "MIT",
            "sha256": "0" * 64,
        },
        "package": {"slides": 1},
        "reverse": {},
        "visual": [{"slide": 1, "min_similarity": 0.9, "min_regional_similarity": 0.8}],
    }

    with pytest.raises(ValidationError, match="visual slide indices out of range"):
        RealDeckCase.model_validate(raw)
