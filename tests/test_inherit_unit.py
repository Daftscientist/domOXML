"""Reverse placeholder→layout→master→theme inheritance resolution.

Each test hand-builds a minimal OPC package (slide + layout + master + theme, wired by
relationships) so the real ``read_pptx`` inheritance path runs end to end, then asserts the
resolved IR. Expected colours are computed by hand against the same formulas the resolver
uses (see ``inherit.apply_color_transforms``)."""

from __future__ import annotations

import colorsys
from xml.etree.ElementTree import fromstring

from domoxml.core.opc import write_package
from domoxml.slides import read_pptx
from domoxml.slides.inherit import apply_color_transforms

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# A theme with a distinguishable major/minor font and a full colour scheme.
_THEME = (
    f'<a:theme xmlns:a="{_A}" name="T"><a:themeElements>'
    '<a:clrScheme name="C">'
    '<a:dk1><a:srgbClr val="111111"/></a:dk1>'
    '<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
    '<a:dk2><a:srgbClr val="222222"/></a:dk2>'
    '<a:lt2><a:srgbClr val="EEEEEE"/></a:lt2>'
    '<a:accent1><a:srgbClr val="4472C4"/></a:accent1>'
    '<a:accent2><a:srgbClr val="ED7D31"/></a:accent2>'
    '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>'
    '<a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
    '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>'
    '<a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
    '<a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
    '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>'
    "</a:clrScheme>"
    '<a:fontScheme name="F">'
    '<a:majorFont><a:latin typeface="Major Sans"/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Minor Serif"/></a:minorFont>'
    "</a:fontScheme>"
    "<a:fmtScheme/></a:themeElements></a:theme>"
)


def _deck(*, slide_sp: str, layout_sp: str = "", master_sp: str = "", tx_styles: str = "") -> bytes:
    """Build a one-slide deck wired slide→layout→master→theme.

    ``slide_sp``/``layout_sp``/``master_sp`` are <p:sp> fragments placed in each spTree.
    ``tx_styles`` is the master <p:txStyles> block (titleStyle/bodyStyle/otherStyle)."""

    def _sld(sp: str) -> str:
        return (
            f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f"<p:grpSpPr/>{sp}</p:spTree></p:cSld>"
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
            'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
            'accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:sld>'
        )

    layout = (
        f'<p:sldLayout xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        f"<p:grpSpPr/>{layout_sp}</p:spTree></p:cSld></p:sldLayout>"
    )
    master = (
        f'<p:sldMaster xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        f"<p:grpSpPr/>{master_sp}</p:spTree></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        f"{tx_styles}</p:sldMaster>"
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
        "ppt/slides/slide1.xml": _sld(slide_sp),
        "ppt/slides/_rels/slide1.xml.rels": (
            f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
            f'Type="{_R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>'
        ),
        "ppt/slideLayouts/slideLayout1.xml": layout,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": (
            f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
            f'Type="{_R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>'
        ),
        "ppt/slideMasters/slideMaster1.xml": master,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": (
            f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
            f'Type="{_R}/theme" Target="../theme/theme1.xml"/></Relationships>'
        ),
        "ppt/theme/theme1.xml": _THEME,
    }
    return write_package(parts)


def _ph_sp(
    *,
    ph_type: str,
    ph_idx: str | None,
    xfrm: str = "",
    body: str = "",
    body_pr: str = "",
) -> str:
    """A placeholder <p:sp>. Empty ``xfrm`` omits the a:xfrm (forcing inheritance)."""
    idx_attr = f' idx="{ph_idx}"' if ph_idx is not None else ""
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="ph"/><p:cNvSpPr/>'
        f'<p:nvPr><p:ph type="{ph_type}"{idx_attr}/></p:nvPr></p:nvSpPr>'
        f"<p:spPr>{xfrm}</p:spPr>"
        f"<p:txBody><a:bodyPr{body_pr}/><a:lstStyle/>{body}</p:txBody></p:sp>"
    )


_XFRM = '<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'


def test_geometry_inherited_from_layout_placeholder() -> None:
    # Slide placeholder has no a:xfrm; the layout placeholder (same idx) supplies it.
    slide = _ph_sp(ph_type="body", ph_idx="1", xfrm="")
    layout = _ph_sp(
        ph_type="body", ph_idx="1", xfrm=_XFRM.format(x=914400, y=685800, cx=3000000, cy=1000000)
    )
    [ir] = read_pptx(_deck(slide_sp=slide, layout_sp=layout))
    box = ir.shapes[0].box
    assert (box.x, box.y, box.width, box.height) == (914400, 685800, 3000000, 1000000)


def test_geometry_inherited_from_master_when_layout_absent() -> None:
    # Neither slide nor layout placeholder carry a:xfrm; the master placeholder supplies it.
    slide = _ph_sp(ph_type="body", ph_idx="1", xfrm="")
    layout = _ph_sp(ph_type="body", ph_idx="1", xfrm="")
    master = _ph_sp(
        ph_type="body", ph_idx="1", xfrm=_XFRM.format(x=100000, y=200000, cx=4000000, cy=2000000)
    )
    [ir] = read_pptx(_deck(slide_sp=slide, layout_sp=layout, master_sp=master))
    box = ir.shapes[0].box
    assert (box.x, box.y, box.width, box.height) == (100000, 200000, 4000000, 2000000)


def test_text_body_properties_inherit_from_layout_placeholder() -> None:
    slide = _ph_sp(
        ph_type="title",
        ph_idx="0",
        xfrm=_XFRM.format(x=0, y=0, cx=5_000_000, cy=1_000_000),
        body="<a:p><a:r><a:t>Heading</a:t></a:r></a:p>",
    )
    layout = _ph_sp(
        ph_type="title",
        ph_idx="0",
        body_pr=' anchor="b" lIns="0" tIns="100" rIns="200" bIns="300"',
    )

    [ir] = read_pptx(_deck(slide_sp=slide, layout_sp=layout))

    text = ir.shapes[0].text
    assert text is not None
    assert text.anchor == "bottom"
    assert text.margins == (0, 100, 200, 300)


def test_title_run_inherits_master_titlestyle_size_and_font() -> None:
    # Title placeholder run carries no size/font; master titleStyle lvl1 supplies both.
    slide = _ph_sp(
        ph_type="title",
        ph_idx="0",
        xfrm=_XFRM.format(x=0, y=0, cx=5000000, cy=1000000),
        body="<a:p><a:r><a:t>Heading</a:t></a:r></a:p>",
    )
    tx_styles = (
        f'<p:txStyles xmlns:p="{_P}" xmlns:a="{_A}"><p:titleStyle>'
        '<a:lvl1pPr><a:defRPr sz="4400"><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr>'
        "</p:titleStyle><p:bodyStyle/><p:otherStyle/></p:txStyles>"
    )
    [ir] = read_pptx(_deck(slide_sp=slide, tx_styles=tx_styles))
    run = ir.shapes[0].text.paragraphs[0].runs[0]  # type: ignore[union-attr]
    assert run.size_pt == 44.0
    # +mj-lt resolves through the theme's majorFont latin typeface.
    assert run.font_family == "Major Sans"


def test_body_level2_paragraph_inherits_bodystyle_lvl2() -> None:
    # A second-level body paragraph (lvl="1", 0-based) picks up bodyStyle lvl2pPr.
    slide = _ph_sp(
        ph_type="body",
        ph_idx="1",
        xfrm=_XFRM.format(x=0, y=0, cx=5000000, cy=3000000),
        body='<a:p><a:pPr lvl="1"/><a:r><a:t>Sub point</a:t></a:r></a:p>',
    )
    tx_styles = (
        f'<p:txStyles xmlns:p="{_P}" xmlns:a="{_A}"><p:titleStyle/><p:bodyStyle>'
        '<a:lvl1pPr><a:defRPr sz="2800"/></a:lvl1pPr>'
        '<a:lvl2pPr><a:defRPr sz="2000"><a:latin typeface="+mn-lt"/></a:defRPr></a:lvl2pPr>'
        "</p:bodyStyle><p:otherStyle/></p:txStyles>"
    )
    [ir] = read_pptx(_deck(slide_sp=slide, tx_styles=tx_styles))
    run = ir.shapes[0].text.paragraphs[0].runs[0]  # type: ignore[union-attr]
    assert run.size_pt == 20.0  # lvl2, not lvl1's 28
    assert run.font_family == "Minor Serif"  # +mn-lt → theme minorFont


def test_slide_level_run_overrides_inherited_style() -> None:
    # Explicit slide rPr beats the master titleStyle entirely.
    slide = _ph_sp(
        ph_type="title",
        ph_idx="0",
        xfrm=_XFRM.format(x=0, y=0, cx=5000000, cy=1000000),
        body=(
            '<a:p><a:r><a:rPr sz="1200"><a:latin typeface="Courier New"/></a:rPr>'
            "<a:t>Override</a:t></a:r></a:p>"
        ),
    )
    tx_styles = (
        f'<p:txStyles xmlns:p="{_P}" xmlns:a="{_A}"><p:titleStyle>'
        '<a:lvl1pPr><a:defRPr sz="4400"><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr>'
        "</p:titleStyle><p:bodyStyle/><p:otherStyle/></p:txStyles>"
    )
    [ir] = read_pptx(_deck(slide_sp=slide, tx_styles=tx_styles))
    run = ir.shapes[0].text.paragraphs[0].runs[0]  # type: ignore[union-attr]
    assert run.size_pt == 12.0
    assert run.font_family == "Courier New"


def test_scheme_color_with_lummod_lumoff_resolves_to_rgb() -> None:
    # accent1 (4472C4) with lumMod 75% → hand-computed 2F5597.
    run_rpr = (
        '<a:rPr sz="1800"><a:solidFill><a:schemeClr val="accent1">'
        '<a:lumMod val="75000"/></a:schemeClr></a:solidFill>'
        '<a:latin typeface="Arial"/></a:rPr>'
    )
    slide = _ph_sp(
        ph_type="body",
        ph_idx="1",
        xfrm=_XFRM.format(x=0, y=0, cx=5000000, cy=1000000),
        body=f"<a:p><a:r>{run_rpr}<a:t>Coloured</a:t></a:r></a:p>",
    )
    [ir] = read_pptx(_deck(slide_sp=slide))
    color = ir.shapes[0].text.paragraphs[0].runs[0].color  # type: ignore[union-attr]
    assert (color.r, color.g, color.b) == (0x2F, 0x55, 0x97)


def test_clrmap_remaps_tx1_to_theme_dk1() -> None:
    # A run referencing schemeClr "tx1" must remap via clrMap (tx1→dk1) to dk1's 111111.
    run_rpr = (
        '<a:rPr sz="1800"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
        '<a:latin typeface="Arial"/></a:rPr>'
    )
    slide = _ph_sp(
        ph_type="body",
        ph_idx="1",
        xfrm=_XFRM.format(x=0, y=0, cx=5000000, cy=1000000),
        body=f"<a:p><a:r>{run_rpr}<a:t>TextColour</a:t></a:r></a:p>",
    )
    [ir] = read_pptx(_deck(slide_sp=slide))
    color = ir.shapes[0].text.paragraphs[0].runs[0].color  # type: ignore[union-attr]
    assert (color.r, color.g, color.b) == (0x11, 0x11, 0x11)


# --------------------------------------------------------------------------- transform units


def test_apply_color_transforms_lummod_matches_colorsys() -> None:
    el = fromstring(
        f'<a:schemeClr xmlns:a="{_A}" val="accent1"><a:lumMod val="75000"/></a:schemeClr>'
    )
    r, g, b, a = apply_color_transforms(0x44, 0x72, 0xC4, 1.0, el)
    h, lum, s = colorsys.rgb_to_hls(0x44 / 255, 0x72 / 255, 0xC4 / 255)
    rr, gg, bb = colorsys.hls_to_rgb(h, lum * 0.75, s)
    assert (r, g, b) == (round(rr * 255), round(gg * 255), round(bb * 255))
    assert a == 1.0


def test_apply_color_transforms_shade_scales_toward_black() -> None:
    el = fromstring(f'<a:srgbClr xmlns:a="{_A}" val="FF0000"><a:shade val="50000"/></a:srgbClr>')
    r, g, b, _ = apply_color_transforms(255, 0, 0, 1.0, el)
    assert (r, g, b) == (128, 0, 0)


def test_apply_color_transforms_tint_scales_toward_white() -> None:
    el = fromstring(f'<a:srgbClr xmlns:a="{_A}" val="000000"><a:tint val="50000"/></a:srgbClr>')
    r, g, b, _ = apply_color_transforms(0, 0, 0, 1.0, el)
    assert (r, g, b) == (128, 128, 128)


def test_apply_color_transforms_alpha_sets_fraction() -> None:
    el = fromstring(f'<a:srgbClr xmlns:a="{_A}" val="FF0000"><a:alpha val="40000"/></a:srgbClr>')
    _, _, _, a = apply_color_transforms(255, 0, 0, 1.0, el)
    assert abs(a - 0.4) < 1e-9
