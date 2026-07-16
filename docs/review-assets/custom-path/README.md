# Custom Path Bidirectional Evidence

Generated from `capabilities/pptx/custom-path` with Chromium, LibreOffice, and Microsoft Graph on
2026-07-16.

| Path | Renderer | Global | Regional | Structural |
|---|---|---:|---:|---:|
| HTML -> PPTX | LibreOffice | 0.9996 | 0.9990 | 0.9963 |
| HTML -> PPTX | PowerPoint/Graph | 0.9996 | 0.9987 | 0.9960 |
| PPTX -> normalized HTML | Chromium | 1.0000 | 1.0000 | 1.0000 |
| first PPTX -> second PPTX | LibreOffice | 1.0000 | 1.0000 | 1.0000 |
| first PPTX -> second PPTX | PowerPoint/Graph | 1.0000 | 1.0000 | 1.0000 |

- `source-html.png`: Chromium render of the authored cubic Bezier path and `<hr>` connector.
- `forward-pptx-libreoffice.png` and `forward-pptx-graph.png`: generated PPTX rendered by each
  Office backend.
- `reverse-html.png`: Chromium render after PPTX ingest and normalized HTML serialization.
- `forward-diff-*.png` and `reverse-diff.png`: aligned source/target differences.
- `convergence-diff-graph.png`: first and second PPTX PowerPoint render difference.

Direct inspection confirms that the blue path fill, dark-blue path outline, Bezier silhouette,
gray connector color, stroke widths, size, and placement remain present in every render. The
small forward differences are confined to edge antialiasing. The normalized HTML reverse rounds
to a perfect score, and the regenerated PPTX is pixel-identical to the first PPTX under both
Office renderers. Both PPTX files contain native `a:custGeom`/`a:cubicBezTo`, `a:ln`, and
`p:cxnSp` structures rather than a raster layer.
