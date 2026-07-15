"""Inline SVG path to native custom-geometry extraction."""

from __future__ import annotations

from dataclasses import dataclass

from domoxml.core.ir.model import CustomGeometry
from domoxml.core.render.browser import RenderedNode
from domoxml.core.svg_path import parse_svg_path, scale_path_to_emu
from domoxml.core.units import px_to_emu
from domoxml.types import ConversionWarning


@dataclass(frozen=True)
class SvgGeometryExtract:
    """Custom geometry plus the child node that owns its fill/stroke styles."""

    geometry: CustomGeometry | None
    style_node: RenderedNode
    warning: ConversionWarning | None = None


def extract_custom_geometry(
    node: RenderedNode,
    nodes: tuple[RenderedNode, ...],
    children: dict[int, list[int]],
) -> SvgGeometryExtract:
    """Convert a single-path inline SVG when its view box and path are supported."""
    view_box = node.src.strip().split()
    if node.tag != "svg" or len(view_box) != 4:
        return SvgGeometryExtract(geometry=None, style_node=node)
    try:
        view_width = float(view_box[2])
        view_height = float(view_box[3])
    except ValueError:
        return SvgGeometryExtract(geometry=None, style_node=node)
    if view_width <= 0 or view_height <= 0:
        return SvgGeometryExtract(geometry=None, style_node=node)

    paths = [
        nodes[index]
        for index in children.get(node.index, [])
        if nodes[index].tag == "path" and nodes[index].src
    ]
    if len(paths) != 1:
        return SvgGeometryExtract(geometry=None, style_node=node)
    style_node = paths[0]
    parsed = parse_svg_path(style_node.src)
    if parsed.bail_reason is not None:
        snippet = node.text[:24].strip()
        label = f"<{node.tag}>" + (f" “{snippet}”" if snippet else "")
        warning = ConversionWarning(
            message=(
                f"SVG path contains unsupported command ({parsed.bail_reason}); "
                "falling back to raster"
            ),
            element=label,
        )
        return SvgGeometryExtract(geometry=None, style_node=style_node, warning=warning)
    if not parsed.commands:
        return SvgGeometryExtract(geometry=None, style_node=style_node)

    width = px_to_emu(node.width)
    height = px_to_emu(node.height)
    path = scale_path_to_emu(
        parsed.commands,
        vb_w=view_width,
        vb_h=view_height,
        box_emu_w=width,
        box_emu_h=height,
    )
    geometry = CustomGeometry(width_emu=width, height_emu=height, path=tuple(path))
    return SvgGeometryExtract(geometry=geometry, style_node=style_node)
