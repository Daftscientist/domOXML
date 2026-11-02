"""Video and audio embeds: which media types map to which parts, and the stand-in poster.

PowerPoint stores a video or audio clip as a picture (its poster) that carries an
``a:videoFile``/``a:audioFile`` link, so a poster always exists. A clip with none of its own
gets a plain generated one: a play triangle for video, a speaker for audio.
"""

from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageDraw

from domoxml.core.ir.model import PictureFill

# MIME type -> (extension, kind). PowerPoint plays the mp4 family, mov, avi, wmv and common audio.
MEDIA_TYPES: dict[str, tuple[str, str]] = {
    "video/mp4": ("mp4", "video"),
    "video/x-m4v": ("m4v", "video"),
    "video/quicktime": ("mov", "video"),
    "video/webm": ("webm", "video"),
    "video/x-msvideo": ("avi", "video"),
    "video/x-ms-wmv": ("wmv", "video"),
    "audio/mpeg": ("mp3", "audio"),
    "audio/mp3": ("mp3", "audio"),
    "audio/wav": ("wav", "audio"),
    "audio/x-wav": ("wav", "audio"),
    "audio/mp4": ("m4a", "audio"),
    "audio/ogg": ("ogg", "audio"),
    "audio/aac": ("aac", "audio"),
}
# Extension -> MIME type, for [Content_Types].xml.
MEDIA_CONTENT_TYPES: dict[str, str] = {
    ext: mime
    for mime, (ext, _kind) in reversed(list(MEDIA_TYPES.items()))
    if mime not in ("audio/mp3", "audio/x-wav")
}

# YouTube and Vimeo embed players, which PowerPoint plays as online video.
_ONLINE_VIDEO = re.compile(
    r"^https://(?:www\.)?(?:youtube\.com|youtube-nocookie\.com)/embed/[\w-]{6,}(?:\?[^\s\"'<>]*)?$"
    r"|^https://player\.vimeo\.com/video/\d+(?:\?[^\s\"'<>]*)?$",
    re.IGNORECASE,
)


def online_video_url(source: str) -> str | None:
    """``source`` if it is a YouTube or Vimeo embed player URL, else ``None``."""
    return source if _ONLINE_VIDEO.match(source.strip()) else None


def default_poster(kind: str, width_px: float, height_px: float) -> PictureFill:
    """A plain stand-in poster at the clip's aspect ratio (at most 640 px wide)."""
    width = max(16, min(640, round(width_px)))
    height = max(16, round(width * height_px / width_px)) if width_px > 0 else width
    image = Image.new("RGB", (width, height), (28, 28, 40))
    draw = ImageDraw.Draw(image)
    centre_x, centre_y, size = width / 2, height / 2, min(width, height) / 5
    if kind == "audio":
        draw.polygon(
            [
                (centre_x - size, centre_y - size / 2),
                (centre_x - size / 3, centre_y - size / 2),
                (centre_x + size / 2, centre_y - size),
                (centre_x + size / 2, centre_y + size),
                (centre_x - size / 3, centre_y + size / 2),
                (centre_x - size, centre_y + size / 2),
            ],
            fill="white",
        )
    else:
        draw.polygon(
            [
                (centre_x - size * 0.7, centre_y - size),
                (centre_x - size * 0.7, centre_y + size),
                (centre_x + size, centre_y),
            ],
            fill="white",
        )
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return PictureFill(data=buffer.getvalue(), ext="png")
