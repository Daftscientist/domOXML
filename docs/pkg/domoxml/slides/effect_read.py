"""DrawingML effect-list to canvas-IR parsing and preservation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import (
    Blur,
    Box,
    FillOverlay,
    FillOverlayBlend,
    Glow,
    GradientFill,
    PatternFill,
    Reflection,
    Rgba,
    Shadow,
    SoftEdge,
    SolidFill,
)
from domoxml.core.ir.pattern import pattern_overlay_is_proven
from domoxml.types import ConversionWarning, PreservedFragment

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"a": _A}

type Effect = Shadow | Glow | Blur | SoftEdge | Reflection | FillOverlay
type EffectContainerKind = Literal["list", "sibling"]
type EffectSourceRef = Literal["fill", "fillLine"]
type ColorParser = Callable[[Element], Rgba | None]
type GradientParser = Callable[[Element], GradientFill | None]
type PatternParser = Callable[[Element], PatternFill | None]


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    try:
        return int(element.get(name, str(default)))
    except ValueError:
        return default


def _shadow(
    element: Element,
    color_for: ColorParser,
    *,
    inset: bool,
    box: Box | None,
) -> Shadow:
    color = color_for(element) or Rgba(r=0, g=0, b=0, a=0.5)
    blur = _int_attr(element, "blurRad")
    distance = _int_attr(element, "dist")
    spread_emu = 0
    if not inset:
        spreads: list[float] = []
        if box is not None and box.width > 0 and element.get("sx") is not None:
            spreads.append((_int_attr(element, "sx", 100_000) / 100_000 - 1) * box.width / 2)
        if box is not None and box.height > 0 and element.get("sy") is not None:
            spreads.append((_int_attr(element, "sy", 100_000) / 100_000 - 1) * box.height / 2)
        if spreads:
            spread_emu = round(sum(spreads) / len(spreads))
        else:
            scale_x = _int_attr(element, "sx", 100_000)
            scale_y = _int_attr(element, "sy", 100_000)
            if scale_x != 100_000 or scale_y != 100_000:
                mean_grow = ((scale_x - 100_000) + (scale_y - 100_000)) / 200_000
                spread_emu = round(mean_grow * max(distance, 1) / 2)
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
            part="effectDag" if kind == "effectDag" else "effectLst",
            kind=kind,
            xml=ElementTree.tostring(element, encoding="unicode"),
        ),
    )


def _sibling_shadow_graph(
    effect_dag: Element,
) -> tuple[tuple[Element, ...], EffectSourceRef] | None:
    children = tuple(effect_dag)
    if effect_dag.get("type", "sib") != "sib" or len(children) < 3:
        return None
    source = children[-1]
    raw_ref = source.get("ref")
    if source.tag != f"{{{_A}}}effect" or raw_ref not in {"fill", "fillLine"}:
        return None
    source_ref: EffectSourceRef = "fillLine" if raw_ref == "fillLine" else "fill"
    shadows = children[:-1]
    if any(shadow.tag != f"{{{_A}}}outerShdw" for shadow in shadows):
        return None
    return shadows, source_ref


def effect_container_kind(shape_properties: Element) -> EffectContainerKind:
    """Return the typed effect container that can be rebuilt without source markup."""
    effect_dag = shape_properties.find("a:effectDag", _NS)
    return (
        "sibling"
        if effect_dag is not None and _sibling_shadow_graph(effect_dag) is not None
        else "list"
    )


def effect_source_ref(shape_properties: Element) -> EffectSourceRef:
    """Return the explicit source input of a supported sibling effect graph."""
    effect_dag = shape_properties.find("a:effectDag", _NS)
    graph = _sibling_shadow_graph(effect_dag) if effect_dag is not None else None
    return graph[1] if graph is not None else "fill"


def read_effects(
    shape_properties: Element,
    color_for: ColorParser,
    *,
    box: Box | None = None,
    gradient_for: GradientParser | None = None,
    pattern_for: PatternParser | None = None,
    expected_over: FillOverlay | None = None,
) -> tuple[tuple[Effect, ...], tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    """Parse native effects and explicitly preserve unsupported effect nodes."""
    effect_list = shape_properties.find("a:effectLst", _NS)
    effect_dag = shape_properties.find("a:effectDag", _NS)
    if effect_dag is not None:
        graph = _sibling_shadow_graph(effect_dag)
        if graph is None:
            warning, fragment = _preserve(
                effect_dag,
                "effectDag",
                "a:effectDag has no proven CSS graph mapping; preserved as one container",
            )
            return (), (warning,), (fragment,)
        shadow_elements, _source_ref = graph
        sibling_effects: tuple[Effect, ...] = tuple(
            _shadow(child, color_for, inset=False, box=box) for child in reversed(shadow_elements)
        )
        return sibling_effects, (), ()
    if effect_list is None:
        return (), (), ()
    effects: list[Effect] = []
    warnings: list[ConversionWarning] = []
    preserved: list[PreservedFragment] = []
    for child in effect_list:
        kind = child.tag.rsplit("}", 1)[-1]
        if kind == "outerShdw":
            effects.append(_shadow(child, color_for, inset=False, box=box))
        elif kind == "innerShdw":
            effects.append(_shadow(child, color_for, inset=True, box=box))
        elif kind == "glow":
            color = color_for(child) or Rgba(r=0, g=0, b=0, a=0.5)
            effects.append(Glow(color=color, radius_emu=_int_attr(child, "rad")))
        elif kind == "blur":
            effects.append(Blur(radius_emu=_int_attr(child, "rad")))
            warnings.append(
                ConversionWarning(
                    message=(
                        "a:blur mapped to filter:blur(); rebuilt PPTX uses an isolated "
                        "renderer fallback"
                    )
                )
            )
        elif kind == "softEdge":
            radius = _int_attr(child, "rad")
            effects.append(SoftEdge(radius_emu=radius))
            if radius > 0:
                warnings.append(
                    ConversionWarning(
                        message=(
                            "a:softEdge mapped to a geometry-aware CSS alpha mask; rebuilt PPTX "
                            "uses an isolated renderer fallback"
                        )
                    )
                )
        elif kind == "reflection":
            effects.append(
                Reflection(
                    blur_emu=_int_attr(child, "blurRad"),
                    distance_emu=_int_attr(child, "dist"),
                    start_alpha=min(
                        1.0,
                        max(
                            0.0,
                            _int_attr(child, "stA", _int_attr(child, "startA", 100_000)) / 100_000,
                        ),
                    ),
                    end_alpha=min(1.0, max(0.0, _int_attr(child, "endA") / 100_000)),
                )
            )
            warnings.append(
                ConversionWarning(
                    message=(
                        "a:reflection mapped to -webkit-box-reflect; rebuilt PPTX uses an "
                        "isolated renderer fallback"
                    )
                )
            )
        elif kind == "fillOverlay":
            solid = child.find("a:solidFill", _NS)
            gradient_element = child.find("a:gradFill", _NS)
            pattern_element = child.find("a:pattFill", _NS)
            overlay_fill: SolidFill | GradientFill | PatternFill | None = None
            present_fills = sum(
                element is not None for element in (solid, gradient_element, pattern_element)
            )
            if solid is not None and present_fills == 1:
                color = color_for(solid)
                overlay_fill = SolidFill(color=color) if color is not None else None
            elif gradient_element is not None and present_fills == 1 and gradient_for is not None:
                overlay_fill = gradient_for(gradient_element)
            elif pattern_element is not None and present_fills == 1 and pattern_for is not None:
                overlay_fill = pattern_for(pattern_element)
            blend = child.get("blend", "over")
            supported_blends: set[FillOverlayBlend] = {
                "mult",
                "screen",
                "darken",
                "lighten",
            }
            if isinstance(overlay_fill, PatternFill) and not pattern_overlay_is_proven(
                overlay_fill, blend
            ):
                overlay_fill = None
            typed_overlay: FillOverlay | None = None
            if overlay_fill is not None and blend in supported_blends:
                typed_overlay = FillOverlay(fill=overlay_fill, blend=blend)
            elif (
                blend == "over"
                and expected_over is not None
                and isinstance(overlay_fill, SolidFill)
                and 0.0 < overlay_fill.color.a < 1.0
            ):
                candidate = FillOverlay(fill=overlay_fill, blend="over")
                if candidate == expected_over:
                    typed_overlay = candidate
            if typed_overlay is not None:
                effects.append(typed_overlay)
                overlay_visible = (
                    typed_overlay.fill.color.a > 0.0
                    if isinstance(typed_overlay.fill, SolidFill)
                    else any(stop.color.a > 0.0 for stop in typed_overlay.fill.stops)
                    if isinstance(typed_overlay.fill, GradientFill)
                    else True
                )
                if overlay_visible:
                    warnings.append(
                        ConversionWarning(
                            message=(
                                "a:fillOverlay mapped to CSS background blending; rebuilt PPTX "
                                "uses an isolated renderer fallback"
                            )
                        )
                    )
            else:
                warning, fragment = _preserve(
                    child,
                    kind,
                    "a:fillOverlay has no supported CSS fill mapping; preserved as fragment",
                )
                warnings.append(warning)
                preserved.append(fragment)
        else:
            message = (
                f"a:{kind} has no CSS mapping; preserved as fragment"
                if kind == "prstShdw"
                else f"a:{kind} (in effectLst) has no CSS mapping; preserved as fragment"
            )
            warning, fragment = _preserve(child, kind, message)
            warnings.append(warning)
            preserved.append(fragment)
    return tuple(effects), tuple(warnings), tuple(preserved)
