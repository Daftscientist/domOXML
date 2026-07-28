# Custom-path reflection review evidence

This bundle records the bidirectional `custom-path-reflection` capability. A strict lone
below-reflection on authored SVG becomes one editable DrawingML custom path with native
`a:reflection` metadata and one exact transparent, shape-owned paint layer. The fallback includes
the measured reflection extent and remains one movable hybrid through repeated PPTX -> HTML ->
PPTX cycles.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.999 | 0.994 | 0.978 | 0.995 |
| Microsoft Graph PPTX | 0.999 | 0.993 | 0.979 | 0.995 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection shows identical geometry, placement, color, gradient extent, and reflection
distance. The Office diffs are confined to edge antialiasing; normalized HTML and repeated-cycle
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
