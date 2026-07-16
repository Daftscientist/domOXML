# Node Identity Render Evidence

Generated from `capabilities/pptx/node-identity` with LibreOffice and Chromium on 2026-07-16.

| Path | Global | Regional | Structural |
|---|---:|---:|---:|
| HTML -> PPTX (LibreOffice) | 0.992 | 0.971 | 0.982 |
| PPTX -> normalized HTML | 1.000 | 1.000 | 1.000 |

- `source.png`: authored HTML rendered by Chromium.
- `libreoffice.png`: generated PPTX rendered by LibreOffice.
- `reverse.png`: generated PPTX read to normalized HTML and rendered by Chromium.
- `libreoffice-diff.png` and `reverse-diff.png`: aligned structural differences.

Direct inspection confirms that both cards retain their geometry, colors, borders, centered text,
and stacking. The forward pair has minor LibreOffice font/raster-edge differences; the reverse
pair is visually identical at the configured comparison resolution.
