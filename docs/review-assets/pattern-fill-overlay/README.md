# Pattern fill-overlay review evidence

This bundle records the bidirectional `pattern-fill-overlay` capability. One calibrated opaque
horizontal stripe pattern over a solid base retains an editable DrawingML `a:pattFill` inside
`a:fillOverlay`. Direct native calibration found Graph tile-edge differences and complete
LibreOffice omission, so one exact shape-owned picture is visible in both renderer branches while
the native shape remains hidden and editable.

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice PPTX | 0.995 | 0.993 | 0.971 | 0.999 |
| Microsoft Graph PPTX (opt-in) | 0.992 | 0.994 | 0.976 | 0.998 |
| Normalized reverse HTML | 1.000 | 1.000 | 1.000 | 1.000 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

Direct inspection confirms full four-pixel stripe cadence, multiply blend, base colour, shape
bounds, and stacking in Chromium, LibreOffice, and Graph. The remaining Office diffs are
renderer resampling along one-pixel stripe edges and the rectangle boundary; no stripe is omitted.
Normalized HTML and repeated-cycle diffs are empty. Uncalibrated repeating gradients and
DrawingML pattern presets remain on preserved or owned-fallback paths instead of being promoted.

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
