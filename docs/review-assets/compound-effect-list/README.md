# Compound effect-list evidence

The source shape combines CSS `blur(6px)` with one offset shadow. domOXML emits one editable,
schema-ordered DrawingML `effectLst` plus one isolated portable fallback, then recovers the same
typed effects and fallback through two normalized-HTML cycles.

| Boundary | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| Source HTML -> LibreOffice PPTX | 0.991443 | 0.957386 | 0.826617 | 0.967961 |
| Source HTML -> PowerPoint/Graph PPTX | 0.992076 | 0.963922 | 0.852816 | 0.980722 |
| PPTX -> normalized HTML | 0.994241 | 0.973333 | 0.885607 | 0.992674 |
| normalized HTML cycle 1 -> cycle 2 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

The forward floors are omission-sensitive. Removing blur scores 0.985934 global, 0.947190
regional, and 0.814268 focused in LibreOffice; removing the shadow scores 0.984869 global,
0.923922 regional, and 0.759116 focused.

Files:

- `source.png`: Chromium source render.
- `libreoffice.png` / `libreoffice-diff.png`: aligned LibreOffice candidate and diff.
- `graph.png` / `graph-diff.png`: aligned Microsoft PowerPoint/Graph candidate and diff.
- `reverse.png` / `reverse-diff.png`: normalized-HTML candidate and diff.
