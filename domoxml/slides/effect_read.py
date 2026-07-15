"""DrawingML effect-list to canvas-IR parsing and preservation."""

from __future__ import annotations

from collections.abc import Callable
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import Blur, Glow, Reflection, Rgba, Shadow, SoftEdge
from domoxml.types import ConversionWarning, PreservedFragment

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"a": _A}

type Effect = Shadow | Glow | Blur | SoftEdge | Reflection
type ColorParser = Callable[[Element], Rgba | None]


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    try:
        return int(element.get(name, str(default)))
    except ValueError:
        return default


def _shadow(element: Element, color_for: ColorParser, *, inset: bool) -> Shadow:
    color = color_for(element) or Rgba(r=0, g=0, b=0, a=0.5)
    blur = _int_attr(element, "blurRad")
    distance = _int_attr(element, "dist")
    spread_emu = 0
    if not inset:
        scale_x = _int_attr(element, "sx", 100_000)
        scale_y = _int_attr(element, "sy", 100_000)
        if scale_x != 100_000 or scale_y != 100_000:
            mean_scale = ((scale_x - 100_000) / 100_000 + (scale_y - 100_000) / 100_000) / 2
            spread_emu = max(1, round(mean_scale * max(distance, 1)))
    return Shadow(
        color=color,
        blur_emu=blur,
        distance_emu=distance,
        direction_deg=_int_attr(element, "dir") / 60_000,
        inset=inset,
        spread_emu=spread_emu,
    )


def _preserve(
    element: Element, kind: str, message: str
) -> tuple[ConversionWarning, PreservedFragment]:
    return (
        ConversionWarning(message=message),
        PreservedFragment(
            part="effectLst",
            kind=kind,
            xml=ElementTree.tostring(element, encoding="unicode"),
        ),
    )


def read_effects(
    shape_properties: Element, color_for: ColorParser
) -> tuple[tuple[Effect, ...], tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    """Parse native effects and explicitly preserve unsupported effect nodes."""
    effect_list = shape_properties.find("a:effectLst", _NS)
    if effect_list is None:
        return (), (), ()
    effects: list[Effect] = []
    warnings: list[ConversionWarning] = []
    preserved: list[PreservedFragment] = []
    for child in effect_list:
        kind = child.tag.rsplit("}", 1)[-1]
        if kind == "outerShdw":
            effects.append(_shadow(child, color_for, inset=False))
        elif kind == "innerShdw":
            effects.append(_shadow(child, color_for, inset=True))
        elif kind == "glow":
            color = color_for(child) or Rgba(r=0, g=0, b=0, a=0.5)
            effects.append(Glow(color=color, radius_emu=_int_attr(child, "rad")))
        elif kind == "blur":
            effects.append(Blur(radius_emu=_int_attr(child, "rad")))
            warnings.append(
                ConversionWarning(
                    message="a:blur mapped to filter:blur() — forward round-trip will rasterise"
                )
            )
        elif kind == "softEdge":
            effects.append(SoftEdge(radius_emu=_int_attr(child, "rad")))
        elif kind == "reflection":
            effects.append(
                Reflection(
                    blur_emu=_int_attr(child, "blurRad"),
                    distance_emu=_int_attr(child, "dist"),
                    start_alpha=min(1.0, max(0.0, _int_attr(child, "startA", 100_000) / 100_000)),
                    end_alpha=min(1.0, max(0.0, _int_attr(child, "endA") / 100_000)),
                )
            )
            warnings.append(
                ConversionWarning(
                    message="a:reflection approximated as -webkit-box-reflect; "
                    "forward round-trip will rasterise"
                )
            )
        else:
            message = (
                f"a:{kind} has no CSS mapping; preserved as fragment"
                if kind in {"prstShdw", "fillOverlay"}
                else f"a:{kind} (in effectLst) has no CSS mapping; preserved as fragment"
            )
            warning, fragment = _preserve(child, kind, message)
            warnings.append(warning)
            preserved.append(fragment)
    return tuple(effects), tuple(warnings), tuple(preserved)
