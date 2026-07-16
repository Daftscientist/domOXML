# Chart Preservation Render Evidence

Generated from the pinned `external-chart-preservation` real deck with LibreOffice and Chromium on
2026-07-16.

| Path | Global | Regional | Structural |
|---|---:|---:|---:|
| source PPTX -> normalized HTML -> re-emitted PPTX | 0.994 | 0.962 | 0.972 |
| source PPTX -> normalized HTML | 0.953 | 0.702 | 0.776 |

- `source-pptx.png`: original external PPTX slide rendered by LibreOffice.
- `reemitted-pptx.png`: rebuilt PPTX slide rendered by LibreOffice.
- `normalized-html.png`: current normalized HTML view, which intentionally exposes the remaining
  reverse visual-layer gap.
- `reemitted-pptx-diff.png` and `normalized-html-diff.png`: aligned structural differences.

Direct inspection confirms that the re-emitted chart retains the original red/purple palette,
three stacked series, values, categories, axes, grid, title, legend, and geometry. The remaining
PPTX difference is primarily the surrounding slide-title typography/layout. Normalized HTML still
omits the chart pixels; it carries an invisible, owned preservation placeholder so the exact chart
graph can return to PPTX without claiming HTML visual parity.
