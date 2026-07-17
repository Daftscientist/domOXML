"""Versioned normalized-HTML payloads for exact table geometry round-trips."""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from domoxml.core.ir.model import Box, TableNode


class TableGeometryPayload(BaseModel):
    """Table geometry carried beside renderer-facing HTML table layout."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    box: Box
    col_widths_emu: tuple[int, ...]
    row_heights_emu: tuple[int, ...]

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
