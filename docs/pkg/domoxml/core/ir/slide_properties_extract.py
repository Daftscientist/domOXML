"""Slide-level properties captured from the rendered HTML root."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from domoxml.core.ir.model import (
    Fill,
    SlideBackground,
    SlideTransition,
    TransitionDirection,
    TransitionType,
)
from domoxml.core.render.browser import RenderedNode

_VALID_TRANSITION_TYPES: frozenset[str] = frozenset(TransitionType.__args__)  # type: ignore[attr-defined]
_VALID_DIRECTIONS: frozenset[str] = frozenset(TransitionDirection.__args__)  # type: ignore[attr-defined]

type FillResolver = Callable[[RenderedNode], tuple[Fill | None, str | None]]


def extract_transition(styles: dict[str, str]) -> SlideTransition | None:
    """Read captured ``data-transition*`` values into the canvas IR."""
    raw_type = styles.get("domoxmlTransition", "").strip()
    if not raw_type:
        return None
    transition_type: TransitionType = (
        raw_type if raw_type in _VALID_TRANSITION_TYPES else "fade"  # type: ignore[assignment]
    )
    duration_ms: int | None = None
    raw_duration = styles.get("domoxmlTransitionDuration", "").strip()
    if raw_duration:
        with contextlib.suppress(ValueError):
            duration_ms = int(raw_duration)
    direction: TransitionDirection | None = None
    raw_direction = styles.get("domoxmlTransitionDirection", "").strip()
    if raw_direction in _VALID_DIRECTIONS:
        direction = raw_direction  # type: ignore[assignment]
    return SlideTransition(type=transition_type, duration_ms=duration_ms, direction=direction)


def extract_slide_properties(
    nodes: tuple[RenderedNode, ...], fill_for: FillResolver
) -> tuple[RenderedNode | None, SlideTransition | None, SlideBackground | None]:
    """Find the opted-in slide root and extract its transition and native background."""
    root = next(
        (
            node
            for node in nodes
            if node.parent == 0
            and (
                node.styles.get("domoxmlTransition")
                or node.styles.get("domoxmlSlideRoot") == "true"
            )
        ),
        None,
    )
    if root is None:
        return None, None, None
    fill, reason = fill_for(root)
    background = SlideBackground(fill=fill) if fill is not None and reason is None else None
    return root, extract_transition(root.styles), background
