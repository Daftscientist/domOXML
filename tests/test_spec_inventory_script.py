"""Tests for the reproducible ECMA-376 inventory generator."""

# Tests intentionally exercise the generator's internal parsing boundaries.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts import generate_spec_inventories as generator


def test_shared_types_namespace_has_standard_prefix() -> None:
    namespace = "http://schemas.openxmlformats.org/officeDocument/2006/sharedTypes"
    assert generator._NAMESPACE_ALIASES[namespace] == "s"


def test_generated_section_uses_end_marker_after_begin_marker() -> None:
    document = f"stray {generator._END}\nhead\n{generator._BEGIN}\nold\n{generator._END}\ntail\n"
    generated = f"{generator._BEGIN}\nnew\n{generator._END}"

    result = generator._replace_generated(document, generated)

    assert result == f"stray {generator._END}\nhead\n{generated}\ntail\n"


def test_missing_schema_archive_member_has_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = tmp_path / "part4.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("unexpected.txt", b"missing schemas")
    data = archive_path.read_bytes()
    monkeypatch.setattr(generator, "SCHEMA_ARCHIVE_SHA256", hashlib.sha256(data).hexdigest())

    with pytest.raises(KeyError, match="missing expected archive member"):
        generator._load_xsds(archive_path)


def test_missing_primary_xsd_has_context() -> None:
    with pytest.raises(KeyError, match=r"missing expected XSD part: pml\.xsd"):
        generator._inventory("pptx", {})
