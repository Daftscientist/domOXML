"""Deterministic projection of exact IR effects into DrawingML effect-list slots."""

from __future__ import annotations

from domoxml.core.ir.model import Effect, NativeEffectProjection, Shadow


def effect_list_position(effect: Effect) -> int:
    """Return the fixed ``CT_EffectList`` child position from ECMA-376."""
    if isinstance(effect, Shadow):
        return 3 if effect.inset else 4
    return {
        "blur": 0,
        "fillOverlay": 1,
        "glow": 2,
        "reflection": 6,
        "softEdge": 7,
    }[effect.kind]


def project_native_effects(
    effects: tuple[Effect, ...],
    projection: NativeEffectProjection,
) -> tuple[Effect, ...]:
    """Return the exact tuple or its first-authored child for each effect-list slot."""
    if projection == "complete":
        return effects
    by_position: dict[int, Effect] = {}
    for effect in effects:
        by_position.setdefault(effect_list_position(effect), effect)
    return tuple(by_position[position] for position in sorted(by_position))
