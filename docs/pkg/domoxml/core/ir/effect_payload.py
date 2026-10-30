"""Versioned normalized-HTML payloads for exact effect IR round-trips."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from domoxml.core.ir.model import Effect, NativeEffectProjection, Shadow


class EffectPayload(BaseModel):
    """Effects carried beside renderer-facing CSS in normalized HTML."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    effects: tuple[Effect, ...]
    container: Literal["list", "sibling"] = "list"
    source_ref: Literal["fill", "fillLine"] = "fill"
    native_projection: NativeEffectProjection = "complete"

    @model_validator(mode="after")
    def _sibling_graph_is_supported(self) -> EffectPayload:
        if self.container == "sibling" and (
            len(self.effects) < 2
            or any(not isinstance(effect, Shadow) or effect.inset for effect in self.effects)
        ):
            raise ValueError("sibling effect graph requires multiple outer shadows")
        if self.container == "sibling" and self.native_projection == "schema_subset":
            raise ValueError("schema-subset native projection is only supported for effect lists")
        return self


def encode_effects(
    effects: tuple[Effect, ...],
    *,
    container: Literal["list", "sibling"] = "list",
    source_ref: Literal["fill", "fillLine"] = "fill",
    native_projection: NativeEffectProjection = "complete",
) -> str:
    """Serialize typed effects to compact, versioned JSON."""
    return EffectPayload(
        effects=effects,
        container=container,
        source_ref=source_ref,
        native_projection=native_projection,
    ).model_dump_json()


def decode_effect_payload(value: str | None) -> EffectPayload | None:
    """Validate a normalized-HTML effect payload, returning ``None`` when invalid."""
    if not value:
        return None
    try:
        return EffectPayload.model_validate_json(value)
    except (ValidationError, ValueError):
        return None


def decode_effects(value: str | None) -> tuple[Effect, ...] | None:
    """Return typed effects from a valid normalized-HTML payload."""
    payload = decode_effect_payload(value)
    return payload.effects if payload is not None else None
