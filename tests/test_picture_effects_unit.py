"""A ``p:pic`` carries its glow and shadow in its own ``p:spPr`` like a shape does."""

from __future__ import annotations

import io
import zipfile

from PIL import Image

from domoxml.core.ir.model import Box, Glow, PictureFill, Shadow, ShapeNode, SlideIR
from domoxml.slides import build_pptx
from domoxml.slides.read import read_pptx

_EFFECTS = (
    b"<a:effectLst>"
    b'<a:glow rad="152400"><a:srgbClr val="FFD700"><a:alpha val="75000"/></a:srgbClr></a:glow>'
    b'<a:outerShdw blurRad="127000" dist="76200" dir="2700000" algn="tl" rotWithShape="0">'
    b'<a:srgbClr val="000000"><a:alpha val="50000"/></a:srgbClr></a:outerShdw>'
    b"</a:effectLst>"
)


def _picture_deck() -> bytes:
    png = io.BytesIO()
    Image.new("RGB", (8, 6), (200, 90, 40)).save(png, "PNG")
    node = ShapeNode(
        box=Box(x=100_000, y=100_000, width=2_000_000, height=1_500_000),
        fill=PictureFill(data=png.getvalue()),
    )
    return build_pptx([SlideIR(width=12_192_000, height=6_858_000, shapes=(node,))], faces=[])


def _with_effects(deck: bytes) -> bytes:
    source, out = zipfile.ZipFile(io.BytesIO(deck)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                assert b"<p:pic>" in data
                data = data.replace(
                    b"</a:prstGeom></p:spPr></p:pic>",
                    b"</a:prstGeom>" + _EFFECTS + b"</p:spPr></p:pic>",
                )
            target.writestr(item, data)
    return out.getvalue()


def test_a_pictures_glow_and_shadow_are_read() -> None:
    [slide] = read_pptx(_with_effects(_picture_deck()))

    kinds = sorted(effect.kind for effect in slide.shapes[0].effects)

    assert kinds == ["glow", "shadow"]
    glow = next(e for e in slide.shapes[0].effects if isinstance(e, Glow))
    shadow = next(e for e in slide.shapes[0].effects if isinstance(e, Shadow))
    assert glow.radius_emu == 152_400 and glow.color.hex == "FFD700"
    assert shadow.blur_emu == 127_000 and shadow.distance_emu == 76_200


def test_a_picture_without_effects_has_none() -> None:
    [slide] = read_pptx(_picture_deck())

    assert slide.shapes[0].effects == ()
