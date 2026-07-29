# Gradient fill-overlay review evidence

This bundle records the bidirectional `gradient-fill-overlay` capability. One translucent linear
gradient over a solid base becomes an editable DrawingML `a:gradFill` inside `a:fillOverlay`, with
one isolated renderer fallback. Normalized HTML retains exact authored stops and regenerates the
same typed effect without expanding PowerPoint's projected stop list across repeated cycles.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.999 | 0.996 | 0.982 | 0.988 |
| Microsoft Graph PPTX (opt-in) | 0.999 | 0.995 | 0.986 | 0.981 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection confirms the full coral-to-green screen blend, base color, bounds, and stop
alpha. Premultiplied-sRGB subdivision raised the Graph regional/focused scores from 0.962/0.949 to
0.995/0.986; sampled interior pixels are exact or differ by one channel value. Remaining Office
differences are confined to faint subdivision and boundary-antialiasing pixels. Normalized HTML and
repeated-cycle diffs are empty.

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
