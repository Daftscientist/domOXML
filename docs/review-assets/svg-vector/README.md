# SVG Vector Bidirectional Evidence

Generated from `capabilities/pptx/svg-vector` with Chromium and LibreOffice on 2026-07-16.

| Path | Global | Regional | Structural |
|---|---:|---:|---:|
| HTML -> PPTX | 0.999 | 0.994 | 0.993 |
| PPTX -> normalized HTML | 1.000 | 1.000 | 1.000 |

- `source-html.png`: Chromium render of the authored SVG image.
- `forward-pptx.png`: LibreOffice render of the generated PPTX with PNG fallback and
  `asvg:svgBlip` vector source.
- `reverse-html.png`: Chromium render after PPTX ingest and normalized HTML serialization.
- `forward-diff.png` and `reverse-diff.png`: aligned structural differences.

Direct inspection confirms matching blue background, orange circle, white SVG label, geometry,
size, and placement. The small forward difference is confined to renderer antialiasing around the
circle edge and text. The normalized HTML reverse render is pixel-identical, and the second PPTX
retains the SVG package part and `asvg:svgBlip` relationship rather than becoming a raster layer.
