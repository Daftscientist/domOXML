"""PresentationML slide-transition serialization and parsing."""

from __future__ import annotations

from xml.etree.ElementTree import Element

from domoxml.core.ir.model import SlideTransition, TransitionDirection, TransitionType

_TRANSITION_TYPE_MAP: dict[str, TransitionType] = {
    "fade": "fade",
    "push": "push",
    "wipe": "wipe",
    "cut": "cut",
    "split": "split",
    "cover": "cover",
    "uncover": "uncover",
    "zoom": "zoom",
    "dissolve": "dissolve",
    "morph": "morph",
    "fly": "push",
    "strips": "wipe",
    "wheel": "dissolve",
    "random": "fade",
}
_DIRECTION_ATTRS = ("dir", "side", "through")
_VALID_DIRECTIONS: frozenset[str] = frozenset(TransitionDirection.__args__)  # type: ignore[attr-defined]


def transition_xml(transition: SlideTransition | None) -> str:
    """Serialize a slide transition, or return an empty string when absent."""
    if transition is None or transition.type == "none":
        return ""
    dur_attr = f' dur="{transition.duration_ms}"' if transition.duration_ms is not None else ""
    dir_attr = f' dir="{transition.direction}"' if transition.direction is not None else ""
    transition_type = transition.type
    if transition_type in {"push", "cover", "uncover", "wipe"}:
        child = f"<p:{transition_type}{dir_attr}/>"
    elif transition_type == "split":
        orient = transition.direction if transition.direction in {"horz", "vert"} else "horz"
        child = f'<p:split orient="{orient}"/>'
    else:
        child = f"<p:{transition_type}/>"
    return f"<p:transition{dur_attr}>{child}</p:transition>"


def parse_transition(element: Element) -> SlideTransition:
    """Parse a ``p:transition`` element into the canvas IR representation."""
    dur_raw = element.get("dur")
    duration_ms = int(dur_raw) if dur_raw is not None and dur_raw.isdigit() else None
    transition_type: TransitionType = "fade"
    direction: TransitionDirection | None = None
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name not in _TRANSITION_TYPE_MAP:
            continue
        transition_type = _TRANSITION_TYPE_MAP[local_name]
        for attribute in _DIRECTION_ATTRS:
            value = child.get(attribute)
            if value is not None and value in _VALID_DIRECTIONS:
                direction = value  # type: ignore[assignment]
                break
        break
    return SlideTransition(type=transition_type, duration_ms=duration_ms, direction=direction)
