# Picture fill-overlay review evidence

This bundle records the bidirectional `picture-fill-overlay` capability. One uniform top CSS
gradient over one picture layer becomes an editable DrawingML picture fill with native
`a:fillOverlay` metadata and one exact shape-owned fallback. Normalized HTML retains the base
picture once and regenerates the portable layer through repeated PPTX -> HTML -> PPTX cycles.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.999 | 0.992 | 0.974 | 0.985 |
| Microsoft Graph PPTX (opt-in) | 0.999 | 0.996 | 0.988 | 0.966 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection confirms the full multicolor picture interior, multiply blend, overlay alpha,
crop, and bounds. Office differences are confined to one device pixel of rectangle-boundary
antialiasing; normalized HTML and repeated-cycle diffs are empty.

Microsoft Graph is opt-in evidence. No required LibreOffice capability threshold was lowered.

## Files

- `source.png`: authored Chromium render.
- `libreoffice.png`: aligned LibreOffice render of the generated PPTX.
- `libreoffice-diff.png`: source-to-LibreOffice diff.
- `graph.png`: aligned Microsoft Graph render of the generated PPTX.
- `graph-diff.png`: source-to-Graph diff.
- `reverse-html.png`: normalized HTML render after PPTX ingest.
- `reverse-html-diff.png`: source-to-normalized-HTML diff.
- `convergence-diff.png`: cycle-one versus cycle-two normalized HTML diff.
