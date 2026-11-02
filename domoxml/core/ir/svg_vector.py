"""An inline ``<svg>`` kept as a vector picture when it cannot become native shapes.

PowerPoint draws SVG itself (``asvg:svgBlip``), including gradients and dashes, so an SVG that
the shape converter cannot express still leaves as vector, with the isolated raster as the
fallback for renderers that ignore the extension.
"""

from __future__ import annotations

import re

from domoxml.core.ir.model import PictureFill, ShapeNode
from domoxml.core.render.browser import RenderedNode, RenderedRaster

# Resources the standalone picture could not load: PowerPoint never fetches them.
_FILTER = re.compile(r"<filter\b|\bfilter\s*[:=]", re.IGNORECASE)
_EXTERNAL = re.compile(r"<foreignObject\b|(?:xlink:)?href=\"(?!data:|#)", re.IGNORECASE)


def portable_svg(source: str) -> str | None:
    """``source`` if PowerPoint and LibreOffice both draw it as the browser does, else ``None``.

    Real PowerPoint draws ``feGaussianBlur``, ``feTurbulence`` and masks inside ``svgBlip``
    (measured), but LibreOffice prefers the SVG over the PNG fallback and draws those filters
    wrongly (similarity 0.84 and 0.06), so an SVG with a filter keeps its raster rather than risk
    a broken render elsewhere. ``feDropShadow`` is not drawn by PowerPoint at all.
    """
    if _EXTERNAL.search(source) or _FILTER.search(source):
        return None
    return source


def vector_picture(
    shape: ShapeNode, node: RenderedNode, region: RenderedRaster | None
) -> ShapeNode | None:
    """``shape`` (the isolated raster) with the node's own SVG attached as its vector form.

    The SVG is positioned inside the raster's region, so effect overflow (a blur, a shadow) lands
    where the pixels are. A transformed ``<svg>`` keeps its raster: the isolated pixels are in the
    transformed frame and the source SVG is not.
    """
    source = node.styles.get("domoxmlSvgSource")
    if (
        source is None
        or not isinstance(shape.fill, PictureFill)
        or node.styles.get("transform", "none") not in ("none", "")
    ):
        return None
    portable = portable_svg(source)
    if portable is None:
        return None
    if region is not None and (region.width, region.height) != (node.width, node.height):
        inner = portable.replace(
            "<svg",
            f'<svg x="{node.x - region.x:g}" y="{node.y - region.y:g}" overflow="visible"',
            1,
        )
        portable = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{region.width:g}" height="{region.height:g}" '
            f'viewBox="0 0 {region.width:g} {region.height:g}" overflow="visible">{inner}</svg>'
        )
    return shape.model_copy(
        update={"fill": shape.fill.model_copy(update={"svg_data": portable.encode()})}
    )
