"""Contract tests for reverse video and audio parsing."""

from __future__ import annotations

from xml.etree.ElementTree import Element, fromstring

from domoxml.core.ir.model import PictureFill
from domoxml.core.opc import OpcPackage
from domoxml.slides.media_read import read_media

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_SLIDE_PART = "ppt/slides/slide1.xml"


def _media_picture(kind: str, relationship_attribute: str = "link") -> Element:
    settings = "videoPr" if kind == "video" else "audioPr"
    return fromstring(
        f'<p:pic xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}">'
        f'<p:nvPicPr><p:nvPr><p:{kind}File r:{relationship_attribute}="rId2"/>'
        f'<p:{settings} fullScrn="1"/></p:nvPr></p:nvPicPr>'
        "<p:blipFill/><p:spPr><a:xfrm>"
        '<a:off x="10" y="20"/><a:ext cx="300" cy="200"/>'
        "</a:xfrm></p:spPr></p:pic>"
    )


def _package(target: str, *, external: bool, media: bytes | None = None) -> OpcPackage:
    target_mode = ' TargetMode="External"' if external else ""
    parts = {
        _SLIDE_PART: b"<slide/>",
        "ppt/slides/_rels/slide1.xml.rels": (
            f'<Relationships xmlns="{_PKG_REL}">'
            f'<Relationship Id="rId2" Type="{_R}/media" Target="{target}"{target_mode}/>'
            "</Relationships>"
        ).encode(),
    }
    if media is not None:
        parts["ppt/media/clip.mp4"] = media
    return OpcPackage(parts)


def test_reads_embedded_video_and_delegates_poster_parsing() -> None:
    poster = PictureFill(data=b"poster", ext="png")
    seen: list[Element] = []

    def parse_poster(element: Element) -> PictureFill:
        seen.append(element)
        return poster

    media = read_media(
        _media_picture("video", "embed"),
        _package("../media/clip.mp4", external=False, media=b"video-bytes"),
        _SLIDE_PART,
        parse_poster,
    )

    assert media is not None
    assert media.kind == "video"
    assert media.media_data == b"video-bytes"
    assert media.media_ext == "mp4"
    assert media.poster_fill == poster
    assert media.box.model_dump() == {"x": 10, "y": 20, "width": 300, "height": 200}
    assert media.play_settings_xml is not None and "videoPr" in media.play_settings_xml
    assert len(seen) == 1


def test_reads_external_audio_url_and_extension() -> None:
    media = read_media(
        _media_picture("audio"),
        _package("https://example.test/sound.mp3?token=x", external=True),
        _SLIDE_PART,
        lambda _element: None,
    )

    assert media is not None
    assert media.kind == "audio"
    assert media.media_url == "https://example.test/sound.mp3?token=x"
    assert media.media_data is None
    assert media.media_ext == "mp3"
    assert media.play_settings_xml is not None and "audioPr" in media.play_settings_xml
