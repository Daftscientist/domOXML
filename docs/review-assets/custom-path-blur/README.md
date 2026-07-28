# Custom-path blur review evidence

This bundle records the bidirectional `custom-path-blur` capability. Authored SVG blur becomes one
editable DrawingML custom path with native `a:blur` metadata and one exact transparent,
shape-owned paint layer. The fallback uses the measured three-radius blur extent and remains one
movable hybrid through repeated PPTX -> HTML -> PPTX cycles.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 1.000 | 0.997 | 0.991 | 0.982 |
| Microsoft Graph PPTX | 0.999 | 0.995 | 0.988 | 0.984 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection shows identical geometry, location, color, and blur extent. The Office diffs are
confined to subpixel resampling along the feathered boundary; normalized HTML and repeated-cycle
diffs are empty.

## Files

- `source.png`: authored Chromium render.
- `libreoffice.png`: aligned LibreOffice render of the generated PPTX.
- `libreoffice-diff.png`: source-to-LibreOffice diff.
- `graph.png`: aligned Microsoft Graph render of the generated PPTX.
- `graph-diff.png`: source-to-Graph diff.
- `reverse-html.png`: normalized HTML render after PPTX ingest.
- `reverse-html-diff.png`: source-to-normalized-HTML diff.
- `convergence-diff.png`: cycle-one versus cycle-two normalized HTML diff.
