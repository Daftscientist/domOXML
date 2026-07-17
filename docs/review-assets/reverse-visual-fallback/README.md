# Reverse visual fallback evidence

The images cover slide 2 of the pinned `external-chart-preservation` deck. The chart is an
unsupported `p:graphicFrame` on reverse ingest. Its exact source graph remains attached for PPTX
re-emission, while the normalized HTML uses one renderer-derived element crop.

## LibreOffice

| Path | Global | Regional | Structural |
|---|---:|---:|---:|
| PPTX -> normalized HTML | 0.995568 | 0.978012 | 0.946722 |
| source PPTX -> rebuilt PPTX | 0.994036 | 0.959128 | 0.979512 |

- `source-pptx-libreoffice.png`
- `source-slide1-libreoffice.png` (pinned first-page input for the two-slide capability fixture)
- `reverse-html-libreoffice.png`
- `reverse-diff-libreoffice.png`
- `rebuilt-pptx-libreoffice.png`
- `convergence-diff-libreoffice.png`

## Microsoft Graph

| Path | Global | Regional | Structural |
|---|---:|---:|---:|
| PPTX -> normalized HTML | 0.995285 | 0.975581 | 0.948003 |
| source PPTX -> rebuilt PPTX | 0.994827 | 0.963296 | 0.985349 |

- `source-pptx-graph.png`
- `reverse-html-graph.png`
- `reverse-diff-graph.png`
- `rebuilt-pptx-graph.png`
- `convergence-diff-graph.png`

The heading, chart title, plot, labels, legend, colors, and source stacking were inspected directly
in both renderer sets. The remaining thin diff contours are raster scaling and antialiasing deltas;
the full-slide evidence is retained rather than cropping review to the chart box.
