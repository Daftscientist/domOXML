# Custom-path soft-edge review evidence

This bundle records the bidirectional `custom-path-soft-edge` capability. A strict clipped
`SourceAlpha` SVG Gaussian feather becomes one editable DrawingML custom path with native
`a:softEdge` metadata and one exact transparent, shape-owned paint layer. The owned layer remains
one movable hybrid through repeated PPTX -> HTML -> PPTX cycles.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.999 | 0.996 | 0.982 | 0.993 |
| Microsoft Graph PPTX | 0.999 | 0.994 | 0.974 | 0.994 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection confirms that the feather follows the custom-path boundary, including its
concave center, rather than fading the SVG viewport. Office differences are confined to edge
resampling; normalized HTML and repeated-cycle diffs are empty.

## Files

- `source.png`: authored Chromium render.
- `libreoffice.png`: aligned LibreOffice render of the generated PPTX.
- `libreoffice-diff.png`: source-to-LibreOffice diff.
- `graph.png`: aligned Microsoft Graph render of the generated PPTX.
- `graph-diff.png`: source-to-Graph diff.
- `reverse-html.png`: normalized HTML render after PPTX ingest.
- `reverse-html-diff.png`: source-to-normalized-HTML diff.
- `convergence-diff.png`: cycle-one versus cycle-two normalized HTML diff.
