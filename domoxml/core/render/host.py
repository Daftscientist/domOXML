"""Host capture assembly: build :class:`RenderedSlide`s from snapshot data a
host page captured in its own browser (e.g. the page a Pyodide build runs in).

The host owns the DOM. It composes the slide page (see
:func:`domoxml.core.render.page.compose_page`), loads it in an offscreen
iframe, runs the shared snapshot payload (:data:`_SNAPSHOT_JS`, the same one
the Playwright path evaluates) in that document, collects the page's data:
resources, and rasterises the nodes the extractor plans to isolate. What
arrives here is plain data — snapshot dictionaries, base64 PNGs — and
everything after capture (planning, IR extraction, font resolution, OOXML
emission) is the same code the Playwright path runs.

Two captures differ from the Playwright path by necessity, because a web
page cannot screenshot its own rendering:

- Isolated rasters and the full-slide PNG are rendered by the caller with
  whatever rasteriser it has (the web build uses Takumi) from staged,
  style-inlined clones / the composed page, instead of being cropped out
  of a browser screenshot.
- Backdrop layers arrive as a sharp full-slide render with the element
  hidden; the blurred, shape-masked layer the extractor consumes is
  derived here (crop + Gaussian blur + rounded-rect alpha mask). The
  ``sharp`` upright variant is left ``None``: the pre-blurred layer is
  exact in place, which is the representation used whenever a renderer
  cannot blur natively itself.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from collections.abc import Iterable, Mapping
from typing import Any

from domoxml.core.render.browser import (
    _SNAPSHOT_JS,
    RenderedBackdrop,
    RenderedNode,
    RenderedRaster,
    RenderedSlide,
    _raster_bounds,
)
from domoxml.core.render.canvas_recorder import RECORDER_JS

__all__ = [
    "RECORDER_JS",
    "RESOURCES_JS",
    "SNAPSHOT_JS",
    "build_slide",
    "plan_capture",
]

SNAPSHOT_JS = _SNAPSHOT_JS

# Evaluated in the slide document by the host: collect the resources the
# Playwright path would have captured. Its route boundary only ever lets
# data: URLs through, so this returns every data: URL the page references
# via <img> or @font-face, as {url: base64 payload}.
RESOURCES_JS = """
(doc) => {
  const payload = (url) => {
    const comma = url.indexOf(',');
    if (comma < 0) return null;
    const meta = url.slice(0, comma);
    const data = url.slice(comma + 1);
    if (/;base64/i.test(meta)) return data;
    try {
      const text = decodeURIComponent(data);
      let bin = '';
      for (const byte of new TextEncoder().encode(text)) bin += String.fromCharCode(byte);
      return btoa(bin);
    } catch { return null; }
  };
  const resources = {};
  const add = (url) => {
    if (typeof url === 'string' && url.startsWith('data:') && !(url in resources)) {
      const data = payload(url);
      if (data !== null) resources[url] = data;
    }
  };
  for (const img of doc.images) add(img.currentSrc || img.src);
  for (const sheet of doc.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    for (const rule of rules) {
      if (rule.type === 7) {  // CSSRule.FONT_FACE_RULE
        for (const match of rule.cssText.matchAll(/url\\((data:[^)]+)\\)/g)) add(match[1]);
      }
    }
  }
  return resources;
}
"""


def _nodes_from_raw(raw: Iterable[dict[str, Any]]) -> tuple[RenderedNode, ...]:
    return tuple(RenderedNode.model_validate(node) for node in raw)


def _decode_b64(payload: str | None) -> bytes:
    if not payload:
        return b""
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return b""


def plan_capture(
    raw: Iterable[dict[str, Any]], *, width: int, height: int
) -> dict[str, list[dict[str, Any]]]:
    """Raster planning for one captured slide: which nodes the extractor
    will isolate, and which need backdrop layers, with slide-clamped
    bounds — the same planners and bounds the Playwright path uses."""
    from domoxml.core.ir.extract import plan_backdrop_layers, plan_isolated_rasters

    nodes = _nodes_from_raw(raw)
    probe = RenderedSlide(png=b"", width=width, height=height, nodes=nodes)

    def entries(indices: Iterable[int]) -> list[dict[str, Any]]:
        by_index = {node.index: node for node in nodes}
        out: list[dict[str, Any]] = []
        for index in sorted(indices):
            node = by_index.get(index)
            if node is None:
                continue
            x, y, right, bottom = _raster_bounds(
                node, slide_width=width, slide_height=height
            )
            out.append(
                {"index": index, "bounds": [x, y, right - x, bottom - y]}
            )
        return out

    return {
        "isolated": entries(plan_isolated_rasters(probe)),
        "backdrops": entries(plan_backdrop_layers(probe)),
    }


def _fallback_region(
    slide_png: bytes, x: float, y: float, w: float, h: float, *, scale: float
) -> bytes:
    """Pixels for one planned raster the host failed to render: the
    matching crop of the full-slide render when there is one, else a
    transparent PNG of the region. Never raises."""
    pw = max(1, int(round(w * scale)))
    ph = max(1, int(round(h * scale)))
    try:
        from PIL import Image

        if slide_png:
            image = Image.open(io.BytesIO(slide_png)).convert("RGBA")
            region = image.crop(
                (
                    int(round(x * scale)),
                    int(round(y * scale)),
                    int(round(x * scale)) + pw,
                    int(round(y * scale)) + ph,
                )
            )
        else:
            region = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        out = io.BytesIO()
        region.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        # A 1x1 transparent PNG: degenerate, but a valid fallback picture.
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )


_BLUR_RE = re.compile(r"blur\(\s*([0-9]*\.?[0-9]+)px\s*\)")
_RADIUS_RE = re.compile(r"([0-9]*\.?[0-9]+)px")


def _blurred_backdrop(
    sharp_png: bytes,
    node: RenderedNode,
    bounds: tuple[float, float, float, float],
    *,
    scale: float,
) -> RenderedRaster | None:
    """Derive the blurred, shape-masked backdrop layer from a sharp
    full-slide render taken with the element hidden."""
    if not sharp_png:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFilter

        x, y, w, h = bounds
        image = Image.open(io.BytesIO(sharp_png)).convert("RGBA")
        region = image.crop(
            (
                int(round(x * scale)),
                int(round(y * scale)),
                int(round((x + w) * scale)),
                int(round((y + h) * scale)),
            )
        )
        if region.width <= 0 or region.height <= 0:
            return None
        blur_match = _BLUR_RE.search(node.styles.get("backdropFilter", ""))
        radius = float(blur_match.group(1)) if blur_match else 10.0
        if radius > 0:
            region = region.filter(ImageFilter.GaussianBlur(radius * scale))
        mask = Image.new("L", region.size, 0)
        draw = ImageDraw.Draw(mask)
        corner_match = _RADIUS_RE.search(node.styles.get("borderRadius", ""))
        corner = float(corner_match.group(1)) * scale if corner_match else 0.0
        corner = min(corner, region.width / 2, region.height / 2)
        if corner > 0:
            draw.rounded_rectangle(
                (0, 0, region.width - 1, region.height - 1), radius=corner, fill=255
            )
        else:
            draw.rectangle((0, 0, region.width - 1, region.height - 1), fill=255)
        region.putalpha(mask)
        out = io.BytesIO()
        region.save(out, format="PNG")
        return RenderedRaster(png=out.getvalue(), x=x, y=y, width=w, height=h)
    except Exception:
        return None  # a failed backdrop degrades the slide, never blocks it


def build_slide(
    raw: Iterable[dict[str, Any]],
    *,
    width: int,
    height: int,
    scale: float = 1.0,
    png_b64: str | None = None,
    resources_b64: Mapping[str, str] | None = None,
    raster_pngs_b64: Mapping[int, str] | None = None,
    backdrop_sharp_b64: Mapping[int, str] | None = None,
) -> RenderedSlide:
    """Assemble the :class:`RenderedSlide` the Playwright path would have
    produced for the same page, from host-captured pieces."""
    nodes = _nodes_from_raw(raw)
    by_index = {node.index: node for node in nodes}

    def bounds_of(index: int) -> tuple[float, float, float, float]:
        x, y, right, bottom = _raster_bounds(
            by_index[index], slide_width=width, slide_height=height
        )
        return x, y, right - x, bottom - y

    rasters: dict[int, RenderedRaster] = {}
    for index, payload in (raster_pngs_b64 or {}).items():
        png = _decode_b64(payload)
        if not png or index not in by_index:
            continue
        x, y, w, h = bounds_of(index)
        rasters[index] = RenderedRaster(png=png, x=x, y=y, width=w, height=h)

    # The extractor's contract with a capture backend is that every node
    # the raster planner names has a raster: a schema-subset native
    # projection is only valid alongside its portable fallback picture,
    # and a missing one invalidates the whole slide. A host rasteriser
    # can fail per node (an engine gap on one element's CSS), so fill
    # any gap here — a crop of the full-slide render where one exists,
    # a transparent region as the last resort — rather than letting one
    # element's pixels take down the deck's conversion.
    slide_png = _decode_b64(png_b64)
    from domoxml.core.ir.extract import plan_isolated_rasters

    probe = RenderedSlide(png=b"", width=width, height=height, nodes=nodes)
    for index in plan_isolated_rasters(probe):
        if index in rasters or index not in by_index:
            continue
        x, y, w, h = bounds_of(index)
        rasters[index] = RenderedRaster(
            png=_fallback_region(slide_png, x, y, w, h, scale=scale),
            x=x,
            y=y,
            width=w,
            height=h,
        )

    backdrops: dict[int, RenderedBackdrop] = {}
    for index, payload in (backdrop_sharp_b64 or {}).items():
        if index not in by_index:
            continue
        blurred = _blurred_backdrop(
            _decode_b64(payload), by_index[index], bounds_of(index), scale=scale
        )
        if blurred is not None:
            backdrops[index] = RenderedBackdrop(blurred=blurred, sharp=None)

    resources = {
        url: data
        for url, payload in (resources_b64 or {}).items()
        if (data := _decode_b64(payload))
    }
    return RenderedSlide(
        png=slide_png,
        width=width,
        height=height,
        scale=scale,
        nodes=nodes,
        resources=resources,
        rasters=rasters,
        backdrops=backdrops,
    )
