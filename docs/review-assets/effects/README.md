# Effects Bidirectional Evidence

Generated from `capabilities/pptx/effects` with Chromium, LibreOffice, and Microsoft Graph on
2026-07-17.

| Path | Renderer | Global | Regional | Structural |
|---|---|---:|---:|---:|
| HTML -> PPTX | LibreOffice | 0.9963 | 0.9834 | 0.9866 |
| HTML -> PPTX | PowerPoint/Graph | 0.9964 | 0.9836 | 0.9821 |
| PPTX -> normalized HTML | Chromium | 0.9985 | 0.9904 | 0.9959 |
| first PPTX -> second PPTX | LibreOffice | 1.0000 | 1.0000 | 1.0000 |
| first PPTX -> second PPTX | PowerPoint/Graph | 1.0000 | 1.0000 | 1.0000 |

- `source-html.png`: Chromium render of offset shadow plus spread, inset shadow, and glow.
- `forward-pptx-*.png`: generated PPTX rendered by LibreOffice and PowerPoint/Graph.
- `reverse-html.png`: Chromium render after PPTX ingest and normalized HTML serialization.
- `forward-diff-*.png` and `reverse-diff.png`: aligned source/target differences.
- `convergence-diff-graph.png`: first and second PPTX PowerPoint render difference.

Direct inspection confirms that card geometry, fills, centered text, offset shadow direction and
spread, inset shadow, and glow halo remain present and correctly placed. Outer shadow and glow are
native editable DrawingML effects with exact structural assertions. The inset shadow is one movable
raster layer because LibreOffice ignores native `a:innerShdw`; this is an intentional portable
layering decision rather than a silent approximation. Remaining first-generation differences are
limited to Office/browser blur kernels and font rasterization. The regenerated PPTX is
pixel-identical to the first PPTX under both Office renderers.
