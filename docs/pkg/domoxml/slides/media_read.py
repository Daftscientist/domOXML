"""PresentationML video and audio node parsing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Literal
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import Box, MediaNode, PictureFill
from domoxml.core.opc import OpcPackage

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A, "p": _P}
_EMBED = f"{{{_R}}}embed"
_LINK = f"{{{_R}}}link"

type PosterParser = Callable[[Element], PictureFill | None]


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    try:
        return int(element.get(name, str(default)))
    except ValueError:
        return default


def read_media(
    element: Element,
    package: OpcPackage,
    slide_part: str,
    poster_for: PosterParser,
) -> MediaNode | None:
    """Read a video/audio picture, including embedded or external media relationships."""
    non_visual = element.find("p:nvPicPr/p:nvPr", _NS)
    if non_visual is None:
        return None
    media = non_visual.find("p:videoFile", _NS)
    kind: Literal["video", "audio"] = "video"
    if media is None:
        media = non_visual.find("p:audioFile", _NS)
        kind = "audio"
    if media is None:
        return None

    properties = element.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if properties is None or offset is None or extent is None:
        return None
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )

    relationship_id = media.get(_LINK) or media.get(_EMBED)
    media_data: bytes | None = None
    media_url: str | None = None
    media_ext = "mp4"
    if relationship_id is not None:
        for relationship in package.relationships(slide_part):
            if relationship.id != relationship_id:
                continue
            if relationship.target_mode != "Internal":
                media_url = relationship.target
                suffix = PurePosixPath(relationship.target.split("?", 1)[0]).suffix
            else:
                try:
                    media_part = package.resolve(slide_part, relationship)
                    media_data = package.read(media_part)
                    suffix = PurePosixPath(media_part).suffix
                except (KeyError, ValueError):
                    suffix = ""
            media_ext = suffix.lower().lstrip(".") or media_ext
            break

    blip_fill = element.find("p:blipFill", _NS)
    poster = poster_for(blip_fill) if blip_fill is not None else None
    play_settings = non_visual.find("p:videoPr" if kind == "video" else "p:audioPr", _NS)
    play_xml = (
        ElementTree.tostring(play_settings, encoding="unicode")
        if play_settings is not None
        else None
    )
    return MediaNode(
        box=box,
        kind=kind,
        media_data=media_data,
        media_url=media_url,
        media_ext=media_ext,
        poster_fill=poster,
        play_settings_xml=play_xml,
    )
