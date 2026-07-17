"""Placeholder/layout/master/theme effective-style resolution for the reverse reader.

ECMA-376 precedence chain (highest to lowest):
  slide p:spPr / p:txBody rPr|pPr
  → layout placeholder spPr / txBody lstStyle
  → master placeholder spPr / txBody lstStyle
  → master p:txStyles (titleStyle / bodyStyle / otherStyle per ph type)
  → theme font/color scheme defaults

Color-transform formulas (ECMA-376 §20.1.2.3 / §20.1.8.*)
  All transforms operate on HLS or sRGB as stated:
  - lumMod  : new_L = L * value               (HLS, in [0, 1])
  - lumOff  : new_L = L + value               (HLS, clamped to [0, 1])
  - shade   : new_ch = ch * value             (sRGB per-channel, scales toward black)
  - tint    : new_ch = ch + (1 - ch) * value  (sRGB per-channel, scales toward white)
  - alpha   : replaces alpha channel directly (value is the fraction in [0, 1])
  - satMod  : new_S = S * value               (HLS, clamped to [0, 1])
  Transforms are applied in document order (child element order).
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from xml.etree.ElementTree import Element

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"a": _A, "p": _P}

# Placeholder types that resolve to each txStyles slot.
_TITLE_TYPES = frozenset({"title", "ctrTitle"})
_BODY_TYPES = frozenset({"body", "subTitle"})

# lstStyle level attribute → XPath tag name (a:lvl1pPr … a:lvl9pPr).
_LVL_TAG = {i: f"{{{_A}}}lvl{i}pPr" for i in range(1, 10)}

# Theme font scheme: typeface values that redirect to the theme major/minor font.
_MAJOR_SENTINEL = "+mj-lt"
_MINOR_SENTINEL = "+mn-lt"


# ---------------------------------------------------------------------------
# Context carriers — pre-parsed per slide so helpers stay stateless.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlaceholderContext:
    """Pre-looked-up XML elements for one placeholder shape's inheritance chain.

    ``None`` means a level is absent (e.g. no layout or no master placeholder
    for this idx/type combination).  ``master_tx_styles`` is the master-level
    ``p:txStyles`` element (which carries titleStyle/bodyStyle/otherStyle)."""

    ph_type: str  # the ph type attribute value; empty string if not a ph
    ph_idx: int  # the ph idx attribute; 0 if absent (title default)
    layout_ph_sppr: Element | None  # layout placeholder spPr
    layout_ph_body_pr: Element | None  # layout placeholder txBody bodyPr
    layout_ph_lstStyle: Element | None  # layout placeholder txBody lstStyle
    master_ph_sppr: Element | None  # master placeholder spPr
    master_ph_body_pr: Element | None  # master placeholder txBody bodyPr
    master_ph_lstStyle: Element | None  # master placeholder txBody lstStyle
    master_tx_styles: Element | None  # master p:txStyles


@dataclass(frozen=True)
class ThemeContext:
    """Theme-level resources for one slide."""

    major_latin: str  # a:fontScheme majorFont a:latin typeface
    minor_latin: str  # a:fontScheme minorFont a:latin typeface
    colors: dict[str, str]  # resolved hex strings keyed by scheme slot name


# ---------------------------------------------------------------------------
# Placeholder lookup helpers
# ---------------------------------------------------------------------------


def _ph_element(sp: Element) -> Element | None:
    """Return the p:ph element inside p:nvSpPr/p:nvPr, or None."""
    return sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)


def _ph_attrs(ph: Element) -> tuple[str, int]:
    """(type, idx) from a p:ph element (with ECMA defaults)."""
    return ph.get("type", "body"), int(ph.get("idx", "0"))


def _find_ph_in_tree(root: Element, ph_type: str, ph_idx: int) -> Element | None:
    """Find the best-matching placeholder sp in a layout/master XML root.

    Matching priority per ECMA-376 §19.3.1.36:
      1. Exact idx match
      2. Type match (when idx alone does not resolve)
    For title/ctrTitle on a slide, fall back to any master ph with type=title.
    """
    exact_idx: Element | None = None
    type_match: Element | None = None
    for sp in root.findall(".//p:sp", _NS):
        cand_ph = _ph_element(sp)
        if cand_ph is None:
            continue
        cand_type, cand_idx = _ph_attrs(cand_ph)
        if cand_idx == ph_idx:
            exact_idx = sp
            break
        if type_match is None and cand_type == ph_type:
            type_match = sp
    return exact_idx if exact_idx is not None else type_match


def _master_ph_type(ph_type: str) -> str:
    """Map a slide/layout ph type to the canonical master ph type for lookup.

    ctrTitle → title, subTitle → body (master has generic title/body).
    """
    if ph_type == "ctrTitle":
        return "title"
    if ph_type == "subTitle":
        return "body"
    return ph_type


def build_placeholder_context(
    slide_sp: Element,
    layout_root: Element | None,
    master_root: Element | None,
) -> PlaceholderContext | None:
    """Build a PlaceholderContext for a slide shape, or None if not a placeholder."""
    ph = _ph_element(slide_sp)
    if ph is None:
        return None
    ph_type, ph_idx = _ph_attrs(ph)

    layout_ph_sppr: Element | None = None
    layout_ph_body_pr: Element | None = None
    layout_ph_lstStyle: Element | None = None
    master_ph_sppr: Element | None = None
    master_ph_body_pr: Element | None = None
    master_ph_lstStyle: Element | None = None
    master_tx_styles: Element | None = None

    if layout_root is not None:
        layout_sp = _find_ph_in_tree(layout_root, ph_type, ph_idx)
        if layout_sp is not None:
            layout_ph_sppr = layout_sp.find("p:spPr", _NS)
            layout_body = layout_sp.find("p:txBody", _NS)
            if layout_body is not None:
                layout_ph_body_pr = layout_body.find("a:bodyPr", _NS)
                layout_ph_lstStyle = layout_body.find("a:lstStyle", _NS)

    if master_root is not None:
        master_type = _master_ph_type(ph_type)
        master_sp = _find_ph_in_tree(master_root, master_type, ph_idx)
        if master_sp is not None:
            master_ph_sppr = master_sp.find("p:spPr", _NS)
            master_body = master_sp.find("p:txBody", _NS)
            if master_body is not None:
                master_ph_body_pr = master_body.find("a:bodyPr", _NS)
                master_ph_lstStyle = master_body.find("a:lstStyle", _NS)
        master_tx_styles = master_root.find("p:txStyles", _NS)

    return PlaceholderContext(
        ph_type=ph_type,
        ph_idx=ph_idx,
        layout_ph_sppr=layout_ph_sppr,
        layout_ph_body_pr=layout_ph_body_pr,
        layout_ph_lstStyle=layout_ph_lstStyle,
        master_ph_sppr=master_ph_sppr,
        master_ph_body_pr=master_ph_body_pr,
        master_ph_lstStyle=master_ph_lstStyle,
        master_tx_styles=master_tx_styles,
    )


# ---------------------------------------------------------------------------
# Geometry (xfrm) inheritance
# ---------------------------------------------------------------------------


def inherit_xfrm(
    slide_sppr: Element | None,
    ctx: PlaceholderContext | None,
) -> Element | None:
    """Return the first a:xfrm found in the precedence chain (slide → layout → master)."""
    for sppr in _sppr_chain(slide_sppr, ctx):
        xfrm = sppr.find("a:xfrm", _NS)
        if xfrm is not None:
            return xfrm
    return None


# ---------------------------------------------------------------------------
# spPr child inheritance (fill, line, effects)
# ---------------------------------------------------------------------------


def inherit_sppr_child(
    tag: str,
    slide_sppr: Element | None,
    ctx: PlaceholderContext | None,
) -> Element | None:
    """Return the first occurrence of ``tag`` in the spPr precedence chain."""
    for sppr in _sppr_chain(slide_sppr, ctx):
        found = sppr.find(tag, _NS)
        if found is not None:
            return found
    return None


def _sppr_chain(
    slide_sppr: Element | None,
    ctx: PlaceholderContext | None,
) -> list[Element]:
    chain: list[Element] = []
    if slide_sppr is not None:
        chain.append(slide_sppr)
    if ctx is not None:
        if ctx.layout_ph_sppr is not None:
            chain.append(ctx.layout_ph_sppr)
        if ctx.master_ph_sppr is not None:
            chain.append(ctx.master_ph_sppr)
    return chain


# ---------------------------------------------------------------------------
# Text-style inheritance for paragraphs and runs
# ---------------------------------------------------------------------------


def resolve_ppr(
    slide_ppr: Element | None,
    level: int,
    ctx: PlaceholderContext | None,
) -> Element | None:
    """Return the best a:pPr for ``level`` following the full precedence chain.

    If ``slide_ppr`` is set, it wins outright (slide-level always wins).
    Otherwise we walk layout lstStyle → master lstStyle → master txStyles at
    the right level tag.
    """
    if slide_ppr is not None:
        return slide_ppr
    lvl_tag = _LVL_TAG.get(max(1, min(9, level + 1)))
    if lvl_tag is None:
        return None
    for lst in _lstStyle_chain(ctx):
        lvl_ppr = lst.find(lvl_tag, _NS)
        if lvl_ppr is not None:
            return lvl_ppr
    return None


def _tx_style_for_type(tx_styles: Element, ph_type: str) -> Element | None:
    if ph_type in _TITLE_TYPES:
        return tx_styles.find("p:titleStyle", _NS)
    if ph_type in _BODY_TYPES:
        return tx_styles.find("p:bodyStyle", _NS)
    return tx_styles.find("p:otherStyle", _NS)


def _lstStyle_chain(ctx: PlaceholderContext | None) -> list[Element]:
    """Return ordered list of lstStyle Elements to search for level pPr/rPr."""
    chain: list[Element] = []
    if ctx is None:
        return chain
    if ctx.layout_ph_lstStyle is not None:
        chain.append(ctx.layout_ph_lstStyle)
    if ctx.master_ph_lstStyle is not None:
        chain.append(ctx.master_ph_lstStyle)
    if ctx.master_tx_styles is not None:
        style = _tx_style_for_type(ctx.master_tx_styles, ctx.ph_type)
        if style is not None:
            chain.append(style)
    return chain


def resolve_run_rpr(
    slide_rpr: Element | None,
    level: int,
    ctx: PlaceholderContext | None,
) -> Element | None:
    """Return the best a:rPr for a run, walking the full chain."""
    if slide_rpr is not None:
        return slide_rpr
    lvl_tag = _LVL_TAG.get(max(1, min(9, level + 1)))
    if lvl_tag is None:
        return None
    for lst in _lstStyle_chain(ctx):
        lvl_ppr = lst.find(lvl_tag, _NS)
        if lvl_ppr is not None:
            defRPr = lvl_ppr.find("a:defRPr", _NS)
            if defRPr is not None:
                return defRPr
    return None


# ---------------------------------------------------------------------------
# Theme font scheme resolution
# ---------------------------------------------------------------------------


def resolve_typeface(typeface: str, theme: ThemeContext) -> str:
    """Resolve +mj-lt / +mn-lt theme-font sentinels to the actual family name."""
    if typeface == _MAJOR_SENTINEL:
        return theme.major_latin or "sans-serif"
    if typeface == _MINOR_SENTINEL:
        return theme.minor_latin or "sans-serif"
    return typeface or "sans-serif"


def parse_theme_fonts(theme_root: Element) -> tuple[str, str]:
    """Return (major_latin, minor_latin) from an a:theme XML root."""
    major_el = theme_root.find(".//a:fontScheme/a:majorFont/a:latin", _NS)
    minor_el = theme_root.find(".//a:fontScheme/a:minorFont/a:latin", _NS)
    major_tf = (major_el.get("typeface", "") if major_el is not None else "") or "Calibri Light"
    minor_tf = (minor_el.get("typeface", "") if minor_el is not None else "") or "Calibri"
    return major_tf, minor_tf


# ---------------------------------------------------------------------------
# Color-transform resolution
# ---------------------------------------------------------------------------


def apply_color_transforms(
    r: int, g: int, b: int, a: float, color_el: Element
) -> tuple[int, int, int, float]:
    """Apply all DrawingML color-transform children of ``color_el`` in document order.

    Returns (r, g, b, a) with r/g/b in [0, 255] and a in [0.0, 1.0].

    Formulas (ECMA-376 §20.1.2.3 and §20.1.8.*):
      lumMod  : H,L,S → L' = clamp(L * value, 0, 1)           (HLS lightness multiply)
      lumOff  : H,L,S → L' = clamp(L + value, 0, 1)           (HLS lightness offset)
      satMod  : H,L,S → S' = clamp(S * value, 0, 1)           (HLS saturation multiply)
      shade   : sRGB  → ch' = round(ch * value)                (scale each channel toward 0)
      tint    : sRGB  → ch' = round(ch + (255 - ch) * value)   (scale each channel toward 255)
      alpha   : replaces alpha directly with value              (fraction [0, 1])
    """
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0

    for child in color_el:
        local = child.tag.rsplit("}", 1)[-1]
        raw = int(child.get("val", "0"))
        # DrawingML stores fractions as 1000ths of a percent (100000 = 100%)
        value = raw / 100_000.0

        if local in ("lumMod", "lumOff", "satMod"):
            hue, lum, sat = colorsys.rgb_to_hls(rf, gf, bf)
            if local == "lumMod":
                lum = max(0.0, min(1.0, lum * value))
            elif local == "lumOff":
                lum = max(0.0, min(1.0, lum + value))
            else:  # satMod
                sat = max(0.0, min(1.0, sat * value))
            rf, gf, bf = colorsys.hls_to_rgb(hue, lum, sat)

        elif local == "shade":
            rf = max(0.0, min(1.0, rf * value))
            gf = max(0.0, min(1.0, gf * value))
            bf = max(0.0, min(1.0, bf * value))

        elif local == "tint":
            rf = max(0.0, min(1.0, rf + (1.0 - rf) * value))
            gf = max(0.0, min(1.0, gf + (1.0 - gf) * value))
            bf = max(0.0, min(1.0, bf + (1.0 - bf) * value))

        elif local == "alpha":
            a = max(0.0, min(1.0, value))

        # Other transforms (hueMod, hueOff, comp, inv, gray, gamma, invGamma) are
        # uncommon; we leave the colour unchanged and do not warn — they fall
        # through silently which is better than crashing.

    r_out = round(rf * 255)
    g_out = round(gf * 255)
    b_out = round(bf * 255)
    return (
        max(0, min(255, r_out)),
        max(0, min(255, g_out)),
        max(0, min(255, b_out)),
        a,
    )


def resolve_scheme_color(
    scheme_el: Element,
    colors: dict[str, str],
) -> tuple[int, int, int, float] | None:
    """Resolve an a:schemeClr element to (r, g, b, a), applying all child transforms.

    ``colors`` is the fully-remapped theme color dict produced by ``_slide_colors``.
    Returns None if the slot cannot be resolved.
    """
    slot = scheme_el.get("val", "")
    hex_val = colors.get(slot)
    if hex_val is None or len(hex_val) != 6:
        return None
    try:
        r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
    except ValueError:
        return None
    r, g, b, a = apply_color_transforms(r, g, b, 1.0, scheme_el)
    return r, g, b, a
