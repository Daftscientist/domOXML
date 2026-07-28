# Custom-path fill-overlay review evidence

This bundle records the bidirectional `custom-path-fill-overlay` capability. A strict sRGB SVG
flood, alpha clip, and blend graph becomes one editable DrawingML custom path with native
`a:fillOverlay` metadata and one exact shape-owned paint layer. The owned layer remains one movable
hybrid through repeated PPTX -> HTML -> PPTX cycles.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.999 | 0.996 | 0.981 | 0.991 |
| Microsoft Graph PPTX (opt-in) | 0.999 | 0.994 | 0.972 | 0.993 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection confirms that the multiply blend paints the full custom-path interior without
changing its bounds or concave center. Office differences are confined to boundary antialiasing;
normalized HTML and repeated-cycle diffs are empty.

The capability's `0.98` focused floor is enforced by the required LibreOffice backend. Microsoft
Graph is opt-in evidence and is reported without applying or lowering that floor.

## Files

- `source.png`: authored Chromium render.
- `libreoffice.png`: aligned LibreOffice render of the generated PPTX.
- `libreoffice-diff.png`: source-to-LibreOffice diff.
- `graph.png`: aligned Microsoft Graph render of the generated PPTX.
- `graph-diff.png`: source-to-Graph diff.
- `reverse-html.png`: normalized HTML render after PPTX ingest.
- `reverse-html-diff.png`: source-to-normalized-HTML diff.
- `convergence-diff.png`: cycle-one versus cycle-two normalized HTML diff.
