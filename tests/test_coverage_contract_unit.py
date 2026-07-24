"""Executable invariants for representation and editability coverage."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domoxml.types import (
    CoverageItem,
    CoverageReport,
    Editability,
    Representation,
    SourceRetention,
)


def test_report_tracks_native_editable_and_layered_axes() -> None:
    report = CoverageReport(
        items=(
            CoverageItem(
                element="native",
                representation=Representation.NATIVE,
                editability=Editability.SEMANTIC,
            ),
            CoverageItem(
                element="decomposed",
                representation=Representation.DECOMPOSED,
                editability=Editability.COMPONENTS,
                output_count=3,
                reason="split into editable borders",
            ),
            CoverageItem(
                element="layer",
                representation=Representation.ELEMENT_LAYER,
                editability=Editability.LAYERS,
                output_count=1,
                raster_area_emu2=200,
                reason="browser-only filter",
            ),
        )
    )

    assert report.native_ratio == 2 / 3
    assert report.editable_ratio == 2 / 3
    assert report.layered_ratio == 1 / 3
    assert report.raster_area_emu2 == 200
    assert report.output_count == 5
    assert report.count(Representation.DECOMPOSED) == 1
    assert report.count_editability(Editability.COMPONENTS) == 1
    assert report.count_source_retention(SourceRetention.NOT_REQUIRED) == 3


@pytest.mark.parametrize(
    ("representation", "editability", "output_count", "raster_area"),
    [
        (Representation.NATIVE, Editability.LAYERS, 1, 0),
        (Representation.DECOMPOSED, Editability.COMPONENTS, 1, 0),
        (Representation.HYBRID, Editability.SEMANTIC, 2, 0),
        (Representation.LAYERED, Editability.LAYERS, 1, 100),
        (Representation.ELEMENT_LAYER, Editability.LAYERS, 1, 0),
        (Representation.RASTERIZED, Editability.LAYERS, 1, 100),
        (Representation.FAILED, Editability.NONE, 1, 0),
    ],
)
def test_rejects_incoherent_representation_contracts(
    representation: Representation,
    editability: Editability,
    output_count: int,
    raster_area: int,
) -> None:
    with pytest.raises(ValidationError):
        CoverageItem(
            element="invalid",
            representation=representation,
            editability=editability,
            output_count=output_count,
            raster_area_emu2=raster_area,
            reason="invalid combination",
        )


def test_failed_visual_can_explicitly_record_source_loss() -> None:
    item = CoverageItem(
        element="missing",
        representation=Representation.FAILED,
        editability=Editability.NONE,
        source_retention=SourceRetention.LOST,
        output_count=0,
        reason="renderer returned an empty region",
    )

    assert item.source_retention is SourceRetention.LOST


def test_rasterized_visual_is_visible_but_not_claimed_editable() -> None:
    item = CoverageItem(
        element="unsafe-source-crop",
        representation=Representation.RASTERIZED,
        editability=Editability.NONE,
        source_retention=SourceRetention.ATTACHED,
        raster_area_emu2=200,
        reason="source crop cannot prove independent ownership",
    )

    assert item.output_count == 1
    assert CoverageReport(items=(item,)).layered_ratio == 1.0
