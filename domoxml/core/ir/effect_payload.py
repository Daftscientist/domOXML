"""Versioned normalized-HTML payloads for exact effect IR round-trips."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from domoxml.core.ir.model import Effect


class EffectPayload(BaseModel):
    """Effects carried beside renderer-facing CSS in normalized HTML."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    effects: tuple[Effect, ...]


def encode_effects(effects: tuple[Effect, ...]) -> str:
    """Serialize typed effects to compact, versioned JSON."""
    return EffectPayload(effects=effects).model_dump_json()


def decode_effects(value: str | None) -> tuple[Effect, ...] | None:
    """Validate a normalized-HTML effect payload, returning ``None`` when invalid."""
    if not value:
        return None
    try:
        return EffectPayload.model_validate_json(value).effects
    except (ValidationError, ValueError):
        return None
