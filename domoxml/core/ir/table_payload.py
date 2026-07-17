"""Versioned normalized-HTML payloads for exact table geometry round-trips."""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from domoxml.core.ir.model import Box, TableNode, TextBody


class TableGeometryPayload(BaseModel):
    """Table geometry carried beside renderer-facing HTML table layout."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    box: Box
    col_widths_emu: tuple[int, ...]
    row_heights_emu: tuple[int, ...]
    style_id: str | None = None
    first_row: bool = False
    last_row: bool = False
    first_col: bool = False
    last_col: bool = False
    band_row: bool = False
    band_col: bool = False
    header_bold_inherited: bool = False

    @model_validator(mode="after")
    def _dimensions_are_coherent(self) -> TableGeometryPayload:
        if not self.col_widths_emu or any(width <= 0 for width in self.col_widths_emu):
            raise ValueError("table columns must have positive widths")
        if not self.row_heights_emu or any(height <= 0 for height in self.row_heights_emu):
            raise ValueError("table rows must have positive heights")
        return self


def encode_table_geometry(table: TableNode) -> str:
    """Serialize exact table geometry to compact, URL-safe versioned JSON."""
    payload = TableGeometryPayload(
        box=table.box,
        col_widths_emu=table.col_widths_emu,
        row_heights_emu=tuple(row.height_emu for row in table.rows),
        style_id=table.style_id,
        first_row=table.first_row,
        last_row=table.last_row,
        first_col=table.first_col,
        last_col=table.last_col,
        band_row=table.band_row,
        band_col=table.band_col,
        header_bold_inherited=table.header_bold_inherited,
    )
    return base64.urlsafe_b64encode(payload.model_dump_json().encode("utf-8")).decode("ascii")


def decode_table_geometry(value: str | None) -> TableGeometryPayload | None:
    """Validate normalized-HTML table geometry, returning ``None`` when invalid."""
    if not value:
        return None
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        return TableGeometryPayload.model_validate_json(raw)
    except (ValidationError, ValueError, TypeError):
        return None


def _mark_bold_inherited(body: TextBody | None) -> TextBody | None:
    if body is None:
        return None
    return body.model_copy(
        update={
            "paragraphs": tuple(
                paragraph.model_copy(
                    update={
                        "runs": tuple(
                            run.model_copy(update={"bold_inherited": run.bold})
                            for run in paragraph.runs
                        )
                    }
                )
                for paragraph in body.paragraphs
            )
        }
    )


def apply_table_geometry(table: TableNode, payload: TableGeometryPayload) -> TableNode:
    """Restore exact geometry and source table-style semantics after browser extraction."""
    rows = tuple(
        row.model_copy(update={"height_emu": height})
        for row, height in zip(table.rows, payload.row_heights_emu, strict=True)
    )
    if payload.header_bold_inherited and rows:
        header = rows[0]
        rows = (
            header.model_copy(
                update={
                    "cells": tuple(
                        cell.model_copy(update={"text": _mark_bold_inherited(cell.text)})
                        for cell in header.cells
                    )
                }
            ),
            *rows[1:],
        )
    return table.model_copy(
        update={
            "box": payload.box,
            "col_widths_emu": payload.col_widths_emu,
            "style_id": payload.style_id,
            "first_row": payload.first_row,
            "last_row": payload.last_row,
            "first_col": payload.first_col,
            "last_col": payload.last_col,
            "band_row": payload.band_row,
            "band_col": payload.band_col,
            "header_bold_inherited": payload.header_bold_inherited,
            "rows": rows,
        }
    )
