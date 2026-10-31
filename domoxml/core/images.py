"""Image helpers: normalise arbitrary bitmap bytes to an OOXML-safe format, and crop a
region out of a rendered slide PNG for the raster fallback."""

from __future__ import annotations

import base64
import math
from io import BytesIO
from typing import Literal

from PIL import Image, ImageChops, ImageDraw

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
    except (OSError, ValueError, Image.DecompressionBombError):
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


# Lookup table mapping any non-zero alpha to fully opaque.
_ANY_ALPHA_TO_OPAQUE = bytes([0] + [255] * 255)


def apply_alpha_mask(png: bytes, mask_png: bytes) -> bytes | None:
    """``png`` made fully opaque wherever ``mask_png`` paints anything, transparent elsewhere.

    Returns ``None`` if either image cannot be decoded or their sizes differ.
    """
    try:
        with Image.open(BytesIO(png)) as image, Image.open(BytesIO(mask_png)) as mask:
            rgba = image.convert("RGBA")
            if mask.size != rgba.size:
                return None
            alpha = mask.convert("RGBA").getchannel("A")
            painted = Image.frombytes(
                "L", alpha.size, alpha.tobytes().translate(_ANY_ALPHA_TO_OPAQUE)
            )
            rgba.putalpha(painted)
            buffer = BytesIO()
            rgba.save(buffer, "PNG")
            return buffer.getvalue()
    except (OSError, ValueError):
        return None


def unrotate_region(
    png: bytes,
    *,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    rotation_deg: float,
    scale: float,
) -> bytes | None:
    """Sample a rotated rectangle out of ``png`` into an upright ``width`` x ``height`` image.

    ``center_*``, ``width`` and ``height`` are in CSS px and ``scale`` is the device scale of
    ``png``. The rectangle is rotated ``rotation_deg`` clockwise about its centre on the slide, so
    the result is that content in the rectangle's own frame, ready to be placed on a shape that
    PowerPoint then rotates by the same angle. Returns ``None`` if ``png`` cannot be decoded.
    """
    out_w, out_h = max(1, round(width * scale)), max(1, round(height * scale))
    cos, sin = math.cos(math.radians(rotation_deg)), math.sin(math.radians(rotation_deg))
    try:
        with Image.open(BytesIO(png)) as image:
            upright = image.convert("RGBA").transform(
                (out_w, out_h),
                Image.Transform.AFFINE,
                (
                    cos,
                    -sin,
                    scale * center_x - cos * out_w / 2 + sin * out_h / 2,
                    sin,
                    cos,
                    scale * center_y - sin * out_w / 2 - cos * out_h / 2,
                ),
                resample=Image.Resampling.BICUBIC,
            )
            buffer = BytesIO()
            upright.save(buffer, "PNG")
            return buffer.getvalue()
    except (OSError, ValueError):
        return None


def crop_slide_region(
    png: bytes,
    *,
    slide_width: int,
    slide_height: int,
    left: int,
    top: int,
    width: int,
    height: int,
    mask_polygon: tuple[tuple[float, float], ...] | None = None,
) -> bytes | None:
    """Crop an EMU box from an authoritative full-slide render.

    The returned PNG has the source box's full aspect ratio even when the box crosses a slide
    boundary. Out-of-slide pixels are transparent because the slide viewport clips them during
    normalized HTML rendering.
    """
    if slide_width <= 0 or slide_height <= 0 or width <= 0 or height <= 0:
        return None
    try:
        with Image.open(BytesIO(png)) as source:
            source.load()
            scale_x = source.width / slide_width
            scale_y = source.height / slide_height
            source_left = round(left * scale_x)
            source_top = round(top * scale_y)
            source_right = round((left + width) * scale_x)
            source_bottom = round((top + height) * scale_y)
            output_width = max(1, source_right - source_left)
            output_height = max(1, source_bottom - source_top)
            output = Image.new("RGBA", (output_width, output_height), (0, 0, 0, 0))
            clipped = (
                max(0, source_left),
                max(0, source_top),
                min(source.width, source_right),
                min(source.height, source_bottom),
            )
            if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
                return None
            region = source.convert("RGBA").crop(clipped)
            output.paste(region, (clipped[0] - source_left, clipped[1] - source_top))
            if mask_polygon is not None:
                if len(mask_polygon) < 3:
                    return None
                mask = Image.new("L", output.size, 0)
                mask_points = tuple(
                    (
                        round(point_x * scale_x) - source_left,
                        round(point_y * scale_y) - source_top,
                    )
                    for point_x, point_y in mask_polygon
                )
                ImageDraw.Draw(mask).polygon(mask_points, fill=255)
                output.putalpha(ImageChops.multiply(output.getchannel("A"), mask))
            buffer = BytesIO()
            output.save(buffer, "PNG")
            return buffer.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return the ``(width, height)`` in pixels of an encoded image, or ``None`` if undecodable.

    Used by the forward extractor to compute ``background-size: cover`` crop fractions, which
    need the source image's intrinsic aspect ratio."""
    try:
        with Image.open(BytesIO(data)) as image:
            return image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
