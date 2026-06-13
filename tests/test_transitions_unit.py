"""Unit tests for slide transitions, native backgrounds, and animation/SmartArt/OLE preservation."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    GradientFill,
    GradientStop,
    Rgba,
    SlideBackground,
    SlideIR,
    SlideTransition,
    SolidFill,
)
from domoxml.core.opc import write_package
from domoxml.slides import build_pptx, read_pptx
from domoxml.slides.read import read_pptx_result

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_slide_xml(
    extra_sppr: str = "", transition: str = "", bg: str = "", spTree_extra: str = ""
) -> bytes:
    """Build a minimal one-slide PPTX with optional extra XML on the slide root."""
    sp = (
        f'<p:sp xmlns:p="{_P}" xmlns:a="{_A}"><p:nvSpPr>'
        '<p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3000000" cy="1000000"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{extra_sppr}</p:spPr>'
        "<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>"
    )
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": (
            '<?xml version="1.0"?><Types '
            'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/></Types>'
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
            f'Type="{_R}/officeDocument" Target="ppt/presentation.xml"/></Relationships>'
        ),
        "ppt/presentation.xml": (
            f'<p:presentation xmlns:p="{_P}" xmlns:r="{_R}"><p:sldIdLst>'
            '<p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
            '<p:sldSz cx="12192000" cy="6858000"/></p:presentation>'
        ),
        "ppt/_rels/presentation.xml.rels": (
            f'<Relationships xmlns="{_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{_R}/slide" Target="slides/slide1.xml"/>'
            "</Relationships>"
        ),
        "ppt/slides/slide1.xml": (
            f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld>{bg}<p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f"<p:grpSpPr/>{sp}{spTree_extra}</p:spTree></p:cSld>{transition}</p:sld>"
        ),
        "ppt/slides/_rels/slide1.xml.rels": f'<Relationships xmlns="{_PKG_REL}"/>',
    }
    return write_package(parts)


# ---------------------------------------------------------------------------
# Forward: IR → p:transition XML
# ---------------------------------------------------------------------------


def test_forward_fade_transition_xml() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        transition=SlideTransition(type="fade"),
    )
    pptx = build_pptx([slide])
    # Rebuild the slide XML and check for p:transition
    from domoxml.core.opc import OpcPackage

    pkg = OpcPackage.from_bytes(pptx)
    slide_xml = pkg.read("ppt/slides/slide1.xml")
    assert b"<p:transition" in slide_xml
    assert b"<p:fade" in slide_xml


def test_forward_push_transition_with_direction() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        transition=SlideTransition(type="push", direction="r"),
    )
    pptx = build_pptx([slide])
    from domoxml.core.opc import OpcPackage

    pkg = OpcPackage.from_bytes(pptx)
    slide_xml = pkg.read("ppt/slides/slide1.xml")
    assert b"<p:push" in slide_xml
    assert b'dir="r"' in slide_xml


def test_forward_wipe_transition_with_duration() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        transition=SlideTransition(type="wipe", duration_ms=700),
    )
    pptx = build_pptx([slide])
    from domoxml.core.opc import OpcPackage

    pkg = OpcPackage.from_bytes(pptx)
    slide_xml = pkg.read("ppt/slides/slide1.xml")
    assert b"<p:wipe" in slide_xml
    assert b'dur="700"' in slide_xml


def test_forward_no_transition_omits_element() -> None:
    slide = SlideIR(width=12_192_000, height=6_858_000, shapes=())
    pptx = build_pptx([slide])
    from domoxml.core.opc import OpcPackage

    pkg = OpcPackage.from_bytes(pptx)
    slide_xml = pkg.read("ppt/slides/slide1.xml")
    assert b"<p:transition" not in slide_xml


# ---------------------------------------------------------------------------
# Forward: IR → p:bg gradient fill XML
# ---------------------------------------------------------------------------


def test_forward_gradient_background_emits_p_bg() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        background=SlideBackground(
            fill=GradientFill(
                stops=(
                    GradientStop(pos=0.0, color=Rgba(r=102, g=126, b=234)),
                    GradientStop(pos=1.0, color=Rgba(r=118, g=75, b=162)),
                ),
                angle_deg=135.0,
            )
        ),
    )
    pptx = build_pptx([slide])
    from domoxml.core.opc import OpcPackage

    pkg = OpcPackage.from_bytes(pptx)
    slide_xml = pkg.read("ppt/slides/slide1.xml")
    assert b"<p:bg>" in slide_xml
    assert b"<p:bgPr>" in slide_xml
    assert b"<a:gradFill>" in slide_xml


def test_forward_solid_background_emits_p_bg() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        background=SlideBackground(fill=SolidFill(color=Rgba(r=30, g=30, b=80))),
    )
    pptx = build_pptx([slide])
    from domoxml.core.opc import OpcPackage

    pkg = OpcPackage.from_bytes(pptx)
    slide_xml = pkg.read("ppt/slides/slide1.xml")
    assert b"<p:bg>" in slide_xml
    assert b"<a:solidFill>" in slide_xml
    assert b"1E1E50" in slide_xml


# ---------------------------------------------------------------------------
# Reverse: p:transition → SlideTransition IR
# ---------------------------------------------------------------------------


def test_reverse_reads_fade_transition() -> None:
    tr_xml = f'<p:transition xmlns:p="{_P}"><p:fade/></p:transition>'
    pptx = _minimal_slide_xml(transition=tr_xml)
    [slide] = read_pptx(pptx)
    assert slide.transition is not None
    assert slide.transition.type == "fade"


def test_reverse_reads_push_transition_with_direction() -> None:
    tr_xml = f'<p:transition xmlns:p="{_P}"><p:push dir="r"/></p:transition>'
    pptx = _minimal_slide_xml(transition=tr_xml)
    [slide] = read_pptx(pptx)
    assert slide.transition is not None
    assert slide.transition.type == "push"
    assert slide.transition.direction == "r"


def test_reverse_reads_transition_duration() -> None:
    tr_xml = f'<p:transition dur="700" xmlns:p="{_P}"><p:wipe/></p:transition>'
    pptx = _minimal_slide_xml(transition=tr_xml)
    [slide] = read_pptx(pptx)
    assert slide.transition is not None
    assert slide.transition.duration_ms == 700


def test_reverse_no_transition_gives_none() -> None:
    pptx = _minimal_slide_xml()
    [slide] = read_pptx(pptx)
    assert slide.transition is None


# ---------------------------------------------------------------------------
# Reverse: p:bg → SlideBackground IR
# ---------------------------------------------------------------------------


def test_reverse_reads_solid_background() -> None:
    bg_xml = (
        f'<p:bg xmlns:p="{_P}" xmlns:a="{_A}">'
        "<p:bgPr>"
        '<a:solidFill><a:srgbClr val="1E1E50"/></a:solidFill>'
        "<a:effectLst/>"
        "</p:bgPr></p:bg>"
    )
    pptx = _minimal_slide_xml(bg=bg_xml)
    [slide] = read_pptx(pptx)
    assert slide.background is not None
    assert isinstance(slide.background.fill, SolidFill)
    assert slide.background.fill.color.r == 0x1E
    assert slide.background.fill.color.b == 0x50


def test_reverse_reads_gradient_background() -> None:
    bg_xml = (
        f'<p:bg xmlns:p="{_P}" xmlns:a="{_A}">'
        "<p:bgPr>"
        "<a:gradFill>"
        '<a:gsLst><a:gs pos="0"><a:srgbClr val="667EEA"/></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="764BA2"/></a:gs></a:gsLst>'
        '<a:lin ang="14400000" scaled="0"/>'
        "</a:gradFill>"
        "<a:effectLst/>"
        "</p:bgPr></p:bg>"
    )
    pptx = _minimal_slide_xml(bg=bg_xml)
    [slide] = read_pptx(pptx)
    assert slide.background is not None
    assert isinstance(slide.background.fill, GradientFill)
    assert len(slide.background.fill.stops) == 2


def test_reverse_no_background_gives_none() -> None:
    pptx = _minimal_slide_xml()
    [slide] = read_pptx(pptx)
    assert slide.background is None


# ---------------------------------------------------------------------------
# Reverse HTML serialization: transition data-attrs and background CSS
# ---------------------------------------------------------------------------


def test_html_emits_transition_data_attrs() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        transition=SlideTransition(type="fade", duration_ms=500),
    )
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert 'data-transition="fade"' in html
    assert 'data-transition-duration="500"' in html


def test_html_emits_background_gradient_css() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        background=SlideBackground(
            fill=GradientFill(
                stops=(
                    GradientStop(pos=0.0, color=Rgba(r=102, g=126, b=234)),
                    GradientStop(pos=1.0, color=Rgba(r=118, g=75, b=162)),
                ),
                angle_deg=135.0,
            )
        ),
    )
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert "background-image" in html
    assert "gradient" in html


def test_html_emits_background_solid_color_css() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        background=SlideBackground(fill=SolidFill(color=Rgba(r=30, g=30, b=80))),
    )
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert "background-color" in html
    assert "1e1e50" in html.lower() or "30,30,80" in html


def test_html_no_transition_no_data_attr() -> None:
    slide = SlideIR(width=12_192_000, height=6_858_000, shapes=())
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert "data-transition" not in html


# ---------------------------------------------------------------------------
# Reverse: round-trip (fwd+rev) for transitions
# ---------------------------------------------------------------------------


def test_round_trip_transition_fade() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        transition=SlideTransition(type="fade", duration_ms=500),
    )
    [recovered] = read_pptx(build_pptx([slide]))
    assert recovered.transition is not None
    assert recovered.transition.type == "fade"
    assert recovered.transition.duration_ms == 500


def test_round_trip_transition_push_with_direction() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(),
        transition=SlideTransition(type="push", direction="r"),
    )
    [recovered] = read_pptx(build_pptx([slide]))
    assert recovered.transition is not None
    assert recovered.transition.type == "push"
    assert recovered.transition.direction == "r"


# ---------------------------------------------------------------------------
# Preservation: p:timing (animations) → PreservedFragment + warning
# ---------------------------------------------------------------------------


def test_reverse_preserves_timing_with_warning() -> None:
    timing_xml = f'<p:timing xmlns:p="{_P}"><p:tnLst/></p:timing>'
    pptx = _minimal_slide_xml(transition=timing_xml)
    result = read_pptx_result(pptx)
    assert any(f.kind == "timing" for f in result.preserved)
    assert any("p:timing" in w.message for w in result.warnings)
    assert any("animations" in w.message for w in result.warnings)


# ---------------------------------------------------------------------------
# Preservation: SmartArt (graphicFrame) → PreservedFragment + warning
# ---------------------------------------------------------------------------


def test_reverse_preserves_smartart_graphicframe_with_warning() -> None:
    _DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
    gf_xml = (
        f'<p:graphicFrame xmlns:p="{_P}" xmlns:a="{_A}">'
        "<p:nvGraphicFramePr>"
        '<p:cNvPr id="3" name="SmartArt 1"/>'
        "<p:cNvGraphicFramePr/><p:nvPr/>"
        "</p:nvGraphicFramePr>"
        '<p:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></p:xfrm>'
        f'<a:graphic><a:graphicData uri="{_DIAGRAM_URI}"/></a:graphic>'
        "</p:graphicFrame>"
    )
    pptx = _minimal_slide_xml(spTree_extra=gf_xml)
    result = read_pptx_result(pptx)
    # Should be preserved (no mapping to HTML)
    gf_frags = [f for f in result.preserved if f.kind == "graphicFrame"]
    assert gf_frags, "expected a preserved graphicFrame"
    gf_warns = [w for w in result.warnings if "graphicFrame" in w.message]
    assert gf_warns, "expected a warning for graphicFrame"
    assert any("SmartArt" in w.message or "diagram" in w.message for w in gf_warns)


# ---------------------------------------------------------------------------
# Preservation: OLE object → PreservedFragment + warning
# ---------------------------------------------------------------------------


def test_reverse_preserves_ole_object_with_warning() -> None:
    ole_xml = (
        f'<p:oleObj xmlns:p="{_P}" xmlns:r="{_R}" r:id="rId99" progId="Excel.Sheet">'
        "<p:embed/>"
        "</p:oleObj>"
    )
    pptx = _minimal_slide_xml(spTree_extra=ole_xml)
    result = read_pptx_result(pptx)
    ole_frags = [f for f in result.preserved if f.kind == "oleObj"]
    assert ole_frags, "expected a preserved oleObj"
    ole_warns = [w for w in result.warnings if "oleObj" in w.message or "OLE" in w.message]
    assert ole_warns, "expected a warning for oleObj"
