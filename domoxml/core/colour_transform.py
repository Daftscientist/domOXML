"""DrawingML colour transforms (``lumMod``, ``lumOff``, ``tint``, ...) on an sRGB colour."""

from __future__ import annotations

import colorsys
from xml.etree.ElementTree import Element


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
      tint    : sRGB  → ch' = round(255 - (255 - ch) * value)   (value = share of the colour kept)
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
            # ``val`` is how much of the colour is kept: 100% is the colour, 0% is white.
            rf = max(0.0, min(1.0, 1.0 - (1.0 - rf) * value))
            gf = max(0.0, min(1.0, 1.0 - (1.0 - gf) * value))
            bf = max(0.0, min(1.0, 1.0 - (1.0 - bf) * value))

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
