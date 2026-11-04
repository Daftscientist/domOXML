# pyright: basic, reportArgumentType=false
# Built with the untyped native-lab dev tool and python-pptx; ruff still applies.
"""Frames PowerPoint saves with their own picture: 3-D models and embedded objects."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from domoxml import Presentation
from domoxml.types import Representation


def _deck_with_3d_model(glb: bytes | None = None) -> bytes:  # pyright: ignore
    """A slide holding a 3-D model frame whose ``mc:Fallback`` is its poster picture."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import native_lab  # pyright: ignore[reportMissingImports]

    glb = glb or native_lab._glb_triangle()  # type: ignore[attr-defined]
    poster = native_lab._png(native_lab.Image.new("RGB", (400, 220), (30, 90, 200)))  # type: ignore[attr-defined]
    deck = native_lab.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    model = native_lab._part(  # type: ignore[attr-defined]
        slide,
        "/ppt/media/m.glb",
        "model/gltf.binary",
        glb,
        "http://schemas.microsoft.com/office/2017/06/relationships/model3d",
    )
    image = native_lab._part(
        slide, "/ppt/media/p.png", "image/png", poster, f"{native_lab._REL}/image"
    )  # type: ignore[attr-defined]
    frame = (
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        f' xmlns:r="{native_lab._REL}">'  # type: ignore[attr-defined]
        '<mc:Choice xmlns:am3d="http://schemas.microsoft.com/office/drawing/2017/model3d" '
        'Requires="am3d"><p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="3D"/>'
        "<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>"
        '<p:xfrm><a:off x="914400" y="914400"/><a:ext cx="3657600" cy="2011680"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/drawing/2017/model3d">'
        f'<am3d:model3d r:embed="{model}"/></a:graphicData></a:graphic></p:graphicFrame>'
        "</mc:Choice><mc:Fallback>"
        '<p:pic><p:nvPicPr><p:cNvPr id="6" name="3D"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{image}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        '<p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="3657600" cy="2011680"/>'
        '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
        "</mc:Fallback></mc:AlternateContent>"
    )
    slide.shapes._spTree.append(native_lab.etree.fromstring(frame))  # type: ignore[attr-defined]
    buffer = BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def test_a_3d_model_frame_reads_as_a_native_model_with_the_poster_saved_with_it() -> None:
    from domoxml.core.ir.model import MediaNode
    from domoxml.slides.read import read_pptx

    deck = _deck_with_3d_model()
    [node] = [n for n in read_pptx(deck)[0].contents if isinstance(n, MediaNode)]
    html = Presentation.from_pptx(deck)

    assert node.kind == "model" and node.media_data is not None and node.poster_fill is not None
    assert all(i.representation is Representation.NATIVE for i in html.coverage.items)
    assert "<model-viewer" in html.slides[0].html


def test_a_model_frame_that_is_not_binary_gltf_stays_preserved_source() -> None:
    from domoxml.core.ir.model import PreservedNode
    from domoxml.core.opc import rewrite_root_xml
    from domoxml.slides.read import read_pptx

    deck = _deck_with_3d_model(glb=b"not a glb")
    slide = read_pptx(deck)[0]
    node = next(n for n in slide.contents if isinstance(n, PreservedNode))
    xml = rewrite_root_xml(node, shape_id=9, allocate_shape_id=lambda: 10, relationship_ids={})

    assert 'Requires="am3d"' in xml and "xmlns:am3d=" in xml
    html = Presentation.from_pptx(deck)
    layers = [i for i in html.coverage.items if i.representation is Representation.ELEMENT_LAYER]
    assert len(layers) == 1 and "poster picture" in layers[0].reason


def test_a_cropped_poster_is_shown_cropped_and_a_dangling_one_does_not_abort() -> None:
    from domoxml.core.ir.model import PictureFill, SrcRect
    from domoxml.slides.read import _cropped  # pyright: ignore[reportPrivateUsage]

    source = native_lab_png(200, 100)
    cropped = _cropped(
        PictureFill(
            data=source, ext="png", crop=SrcRect(left=0.25, right=0.25, top=0.0, bottom=0.0)
        )
    )

    from PIL import Image

    with Image.open(BytesIO(cropped.data)) as image:
        assert image.size == (100, 100) and cropped.crop is None


def native_lab_png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, "PNG")
    return buffer.getvalue()
