"""Image helpers: normalise arbitrary bitmap bytes to an OOXML-safe format, and crop a
region out of a rendered slide PNG for the raster fallback."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Literal

from PIL import Image

type ImageExt = Literal["png", "jpeg", "gif"]

# Formats PowerPoint embeds without complaint. Anything else is transcoded to PNG.
_NATIVE_FORMATS: dict[str, ImageExt] = {"PNG": "png", "JPEG": "jpeg", "GIF": "gif"}


def normalise_image(data: bytes) -> tuple[bytes, ImageExt] | None:
    """Return ``(bytes, extension)`` ready to embed, transcoding exotic formats (WebP, BMP,
    TIFF…) to PNG. Returns ``None`` if ``data`` is not a decodable image."""
    try:
        with Image.open(BytesIO(data)) as image:
            fmt = (image.format or "").upper()
            if fmt in _NATIVE_FORMATS:
                return data, _NATIVE_FORMATS[fmt]
            buffer = BytesIO()
            image.convert("RGBA").save(buffer, "PNG")
            return buffer.getvalue(), "png"
    except (OSError, ValueError):
        return None


def decode_data_uri(uri: str) -> bytes | None:
    """Decode the payload of a ``data:`` URI (base64 or percent-encoded), or ``None``."""
    if not uri.startswith("data:"):
        return None
    try:
        header, _, payload = uri.partition(",")
        if ";base64" in header.lower():
            return base64.b64decode(payload)
        from urllib.parse import unquote_to_bytes

        return unquote_to_bytes(payload)
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return None


def crop_png(png: bytes, *, left: float, top: float, width: float, height: float) -> bytes | None:
    """Crop a region (device pixels) out of ``png`` and return it as PNG bytes.

    Coordinates are clamped to the image; returns ``None`` if the region is empty or the
    source bytes can't be decoded.
    """
    try:
        with Image.open(BytesIO(png)) as image:
            img_w, img_h = image.size
            x0 = max(0, min(img_w, round(left)))
            y0 = max(0, min(img_h, round(top)))
            x1 = max(x0, min(img_w, round(left + width)))
            y1 = max(y0, min(img_h, round(top + height)))
            if x1 <= x0 or y1 <= y0:
                return None
            region = image.crop((x0, y0, x1, y1))
            buffer = BytesIO()
            region.save(buffer, "PNG")
            return buffer.getvalue()
    except (OSError, ValueError):
        return None
