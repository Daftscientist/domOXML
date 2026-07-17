# Table style fidelity evidence

Source, untouched round-trip candidate, and amplified difference renders for the pinned
`external-table-style` deck. The candidates were produced after retaining the DrawingML table
style reference and flags through Canvas IR and normalized HTML.

| Backend | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice | 0.999 | 0.991 | 0.966 | 0.991 |
| Microsoft Graph / PowerPoint | 0.999 | 0.988 | 0.945 | 0.986 |

The former LibreOffice round trip explicitly baked PowerPoint's header bold into every run and
scored `0.997 / 0.976 / 0.914 / 0.934`; the focused and structural gates now reject that output.
Graph continues to apply the source table style's bold header, while LibreOffice continues to
apply its regular-weight interpretation, matching each renderer's source behavior.
