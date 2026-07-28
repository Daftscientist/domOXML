# Custom-path owned-effect review evidence

This bundle records the reverse-first `custom-path-owned-fallback` capability. The source deck
contains one editable DrawingML custom path, a legal inner-plus-outer native effect subset, full
three-shadow typed intent, and one exact transparent effect crop.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| Normalized reverse HTML | 0.999 | 0.993 | 0.981 | 0.993 |
| Re-emitted Microsoft Graph | 1.000 | 1.000 | 1.000 | 1.000 |
| Re-emitted LibreOffice | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Normalized HTML places the exact picture inside the inline SVG as a renderer-only image. The
native path remains hidden but typed and editable, and absolute raster-bound metadata lets browser
capture recover the same movable owned layer instead of collapsing to the SVG box.

## Files

- `source-graph.png`: Microsoft Graph render of the source PPTX.
- `reverse-html.png`: normalized HTML render.
- `reverse-html-diff.png`: source-to-reverse diff.
- `reemitted-graph.png`: Microsoft Graph render after PPTX -> HTML -> PPTX.
- `reemitted-graph-diff.png`: source-to-re-emitted Graph diff.
- `source-libreoffice.png`: LibreOffice render of the source PPTX.
- `reemitted-libreoffice.png`: LibreOffice render after PPTX -> HTML -> PPTX.
- `reemitted-libreoffice-diff.png`: source-to-re-emitted LibreOffice diff.
- `convergence-diff.png`: cycle-one versus cycle-two HTML diff.
