# PPTX / HTML Reverse Baseline Visual Review

Each comparison uses equal-sized panels:

1. Browser-rendered HTML source, or emitted HTML for the reverse-ingest example.
2. LibreOffice-rendered PPTX.
3. Microsoft Graph-rendered PPTX using the real PowerPoint-backed rendition path.

| Case | LibreOffice | Microsoft Graph |
| --- | ---: | ---: |
| Solid text | 0.997 | 0.996 |
| Native shapes | 0.993 | 0.993 |
| Native gradient | 0.996 | 0.971 |
| Raster fallback | 0.998 | 0.998 |
| Rich text runs | 0.995 | 0.996 |

## Forward Fidelity Corpus

![Solid background and centred heading](01-solid-text.png)

![Multiple native shapes](02-multi-rect.png)

![Native gradient](03-gradient.png)

![Raster fallback behind editable text](04-raster-flourish.png)

![Nested rich text runs](05-rich-text-runs.png)

## Reverse Ingest

The first panel below is HTML/CSS emitted after ingesting a native PowerPoint `p:pic`.

![Native PowerPoint picture reverse ingest](06-native-picture-reverse.png)
