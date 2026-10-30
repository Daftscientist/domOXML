"""Versioned normalized-HTML payloads for exact custom-geometry round-trips."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from domoxml.core.ir.model import CustomGeometry


class CustomGeometryPayload(BaseModel):
    """Custom geometry carried beside its renderer-facing SVG path."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    geometry: CustomGeometry


def encode_custom_geometry(geometry: CustomGeometry) -> str:
    """Serialize typed custom geometry to compact, versioned JSON."""
    return CustomGeometryPayload(geometry=geometry).model_dump_json()


def decode_custom_geometry(value: str | None) -> CustomGeometry | None:
    """Validate a normalized-HTML geometry payload, returning ``None`` when invalid."""
    if not value:
        return None
    try:
        return CustomGeometryPayload.model_validate_json(value).geometry
    except (ValidationError, ValueError):
        return None
