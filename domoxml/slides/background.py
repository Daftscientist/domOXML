"""PresentationML slide-background serialization and parsing."""

from __future__ import annotations

from collections.abc import Callable
from xml.etree.ElementTree import Element

from domoxml.core.ir.lowering import sample_gradient
from domoxml.core.ir.model import (
    Fill,
    GradientFill,
    GradientStop,
    PictureFill,
    Rgba,
    SlideBackground,
    SolidFill,
)

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"p": _P}


def _srgb(color: Rgba) -> str:
    return f"{color.r:02X}{color.g:02X}{color.b:02X}"


def _solid_fill_xml(color: Rgba) -> str:
    alpha_xml = f'<a:alpha val="{round(color.a * 100_000)}"/>' if color.a < 1.0 else ""
    return f'<a:solidFill><a:srgbClr val="{_srgb(color)}">{alpha_xml}</a:srgbClr></a:solidFill>'


def _gradient_stop_xml(stop: GradientStop) -> str:
    alpha_xml = f'<a:alpha val="{round(stop.color.a * 100_000)}"/>' if stop.color.a < 1.0 else ""
    return (
        f'<a:gs pos="{round(stop.pos * 100_000)}"><a:srgbClr val="{_srgb(stop.color)}">'
        f"{alpha_xml}</a:srgbClr></a:gs>"
    )


# Real PowerPoint draws a slide background gradient with few stops in a different colour space
# from the browser (a pink-to-green page is visibly lighter in the middle). Sampled every 1/16 it
# is exact, so a background gradient is written with those stops (measured against Chrome).
_BACKGROUND_STEPS = 16


def _smoothed(stops: tuple[GradientStop, ...]) -> tuple[GradientStop, ...]:
    """``stops`` plus a sampled stop at every 1/16 between its ends that no stop sits on."""
    first, last = min(stop.pos for stop in stops), max(stop.pos for stop in stops)
    extra = [
        GradientStop(pos=k / _BACKGROUND_STEPS, color=sample_gradient(stops, k / _BACKGROUND_STEPS))
        for k in range(1, _BACKGROUND_STEPS)
        if first < k / _BACKGROUND_STEPS < last
        and all(abs(stop.pos - k / _BACKGROUND_STEPS) > 1e-6 for stop in stops)
    ]
    return tuple(sorted((*stops, *extra), key=lambda stop: stop.pos))


def without_sampled_stops(fill: GradientFill) -> GradientFill:
    """``fill`` with the stops dropped that the writer sampled in (see :func:`_unsampled`)."""
    if fill.radial:
        return fill
    return fill.model_copy(update={"stops": _unsampled(fill.stops)})


def _unsampled(stops: tuple[GradientStop, ...]) -> tuple[GradientStop, ...]:
    """``stops`` without the ones that only restate a straight blend of their neighbours.

    The inverse of :func:`_smoothed`: a stop the writer sampled lies within a level of the line
    between the stops around it, so dropping it leaves the gradient the author wrote. A hard
    transition (two stops at one position) is never dropped.
    """
    if len(stops) <= 2:
        return stops
    kept = [stops[0]]
    start = 0
    while start < len(stops) - 1:
        end = start + 1
        for candidate in range(len(stops) - 1, start, -1):
            if _straight(stops[start : candidate + 1]):
                end = candidate
                break
        kept.append(stops[end])
        start = end
    return tuple(kept)


def _straight(run: tuple[GradientStop, ...] | list[GradientStop]) -> bool:
    """Whether every interior stop of ``run`` lies within a level of the line between its ends."""
    first, last = run[0], run[-1]
    span = last.pos - first.pos
    if span <= 0 or any(first.color.a != s.color.a or s.color.a != 1.0 for s in run):
        return len(run) == 2
    for stop in run[1:-1]:
        if stop.pos <= first.pos or stop.pos >= last.pos:
            return False
        steps = stop.pos * _BACKGROUND_STEPS
        if abs(steps - round(steps)) > 1e-6:
            return False  # a position the writer never samples is the author's own
        t = (stop.pos - first.pos) / span
        for a, b, c in (
            (first.color.r, last.color.r, stop.color.r),
            (first.color.g, last.color.g, stop.color.g),
            (first.color.b, last.color.b, stop.color.b),
        ):
            if abs(a + (b - a) * t - c) > 1.0:
                return False
    return True


def _gradient_fill_xml(gradient: GradientFill) -> str:
    chosen = gradient.stops if gradient.radial else _smoothed(gradient.stops)
    stops = "".join(_gradient_stop_xml(stop) for stop in chosen)
    if gradient.radial:
        path = (
            '<a:path path="circle">'
            '<a:fillToRect l="100000" t="100000" r="100000" b="100000"/>'
            "</a:path>"
        )
        return f"<a:gradFill><a:gsLst>{stops}</a:gsLst>{path}</a:gradFill>"
    angle = round(((270 + gradient.angle_deg) % 360) * 60_000)
    return f'<a:gradFill><a:gsLst>{stops}</a:gsLst><a:lin ang="{angle}" scaled="0"/></a:gradFill>'


def background_xml(background: SlideBackground, blip_rid: str | None = None) -> str:
    """Serialize a native slide background into its ``p:bg`` element."""
    fill = background.fill
    if isinstance(fill, SolidFill):
        fill_xml = _solid_fill_xml(fill.color)
    elif isinstance(fill, GradientFill):
        fill_xml = _gradient_fill_xml(fill)
    elif isinstance(fill, PictureFill):
        fill_xml = (
            f'<a:blipFill><a:blip r:embed="{blip_rid}"/>'
            "<a:stretch><a:fillRect/></a:stretch></a:blipFill>"
            if blip_rid is not None
            else "<a:noFill/>"
        )
    else:
        foreground = _srgb(fill.fg) if isinstance(fill.fg, Rgba) else "000000"
        background_color = _srgb(fill.bg) if isinstance(fill.bg, Rgba) else "FFFFFF"
        fill_xml = (
            f'<a:pattFill prst="{fill.preset}">'
            f'<a:fgClr><a:srgbClr val="{foreground}"/></a:fgClr>'
            f'<a:bgClr><a:srgbClr val="{background_color}"/></a:bgClr>'
            "</a:pattFill>"
        )
    return f"<p:bg><p:bgPr>{fill_xml}<a:effectLst/></p:bgPr></p:bg>"


def parse_background(
    slide: Element, fill_parser: Callable[[Element], Fill | None]
) -> SlideBackground | None:
    """Parse the slide background using the caller's general DrawingML fill parser."""
    properties = slide.find("./p:cSld/p:bg/p:bgPr", _NS)
    if properties is None:
        return None
    fill = fill_parser(properties)
    if isinstance(fill, GradientFill) and not fill.radial:
        fill = without_sampled_stops(fill)
    return SlideBackground(fill=fill) if fill is not None else None
