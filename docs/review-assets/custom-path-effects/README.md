# Custom Path Effects Evidence

The source uses two single-path SVG shapes: an offset `drop-shadow()` on a lens and a zero-offset
cyan halo on a diamond. Both lower to editable `a:custGeom` shapes with native DrawingML effects.
Normalized HTML paints the effects with path-aware CSS filters and carries the exact typed payload.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.997447 | 0.982484 | 0.953609 | 0.998626 |
| Microsoft Graph PPTX | 0.997158 | 0.980392 | 0.949437 | 0.999003 |
| PPTX to normalized HTML | 0.999999 | 1.000000 | 1.000000 | 0.999987 |
| Normalized HTML cycle 2 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

The contract floors are `0.996` global, `0.980` regional, and `0.998` structural. A deliberately
effect-stripped deck fails them:

| Omission baseline | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice without effects | 0.994353 | 0.954510 | 0.862495 | 0.995687 |
| Microsoft Graph without effects | 0.994362 | 0.955294 | 0.867668 | 0.995278 |

Direct inspection confirmed that LibreOffice and Graph preserve the path geometry, fill, stroke,
offset direction, and cyan halo. Their native effect kernels remain slightly tighter than Chromium;
the diff images localize that renderer difference to the effect falloff and one-pixel path edges.

The external Apache POI regression retains four producer-authored, formula-backed custom paths and
their four zero-blur outer shadows:

| External round trip | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.999999 | 1.000000 | 0.999917 | 0.999967 |
| Microsoft Graph PPTX | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

Its floors are `0.9998` global, `0.998` regional, `0.99` focused, and `0.99` structural. Removing
the shadows falls below all four floors on both renderers. Direct inspection confirmed the source
and candidates retain line placement, color, stroke width, branching, and the subtle downward
shadow; the LibreOffice diff is limited to isolated subpixel edge values and Graph is pixel-exact.
