# Multiple shadow effect-graph evidence

The source rectangle has two CSS outer shadows in front-to-back paint order. domOXML emits one
editable flat DrawingML sibling graph in reversed paint order with a final fill reference.
PowerPoint renders that native graph; LibreOffice selects one isolated fallback picture.
PPTX ingestion restores both CSS layers and the graph-container metadata.

| Boundary | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| Source HTML -> LibreOffice PPTX | 0.992176 | 0.964444 | 0.841886 | 0.973313 |
| Source HTML -> PowerPoint/Graph PPTX | 0.989820 | 0.955033 | 0.856237 | 0.984128 |
| PPTX -> normalized HTML | 0.993715 | 0.973595 | 0.898039 | 0.993926 |
| normalized HTML cycle 1 -> cycle 2 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

The forward floors reject either missing graph branch. Removing the dark shadow scores 0.916863
regional and 0.738173 focused in LibreOffice; removing the red shadow scores 0.919739 regional and
0.750855 focused. The equivalent Graph scores are 0.916601/0.750104 and 0.920523/0.755611.

Files:

- `source.png`: Chromium source render.
- `libreoffice.png` / `libreoffice-diff.png`: aligned LibreOffice candidate and diff.
- `graph.png` / `graph-diff.png`: aligned Microsoft PowerPoint/Graph candidate and diff.
- `reverse.png` / `reverse-diff.png`: normalized-HTML candidate and diff.
