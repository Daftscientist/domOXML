# Line-break agreement with real PowerPoint

Lines PowerPoint (Graph PDF, `pdftotext -bbox-layout`) set, found verbatim as a line in the
domOXML round-trip HTML rendered by Chromium. Chart decks are excluded (their text is SVG).

| deck | before | after |
| --- | --- | --- |
| shapes-effects | 28/55 (0.51) | 43/55 (0.78) |
| shapes-typography | 43/79 (0.54) | 44/79 (0.56) |
| shapes-basic | 38/45 (0.84) | 38/45 (0.84) |
| tables-basic | 67/72 (0.93) | 69/72 (0.96) |
| tables-rows-cols | 71/73 (0.97) | 73/73 (1.00) |

Cause: runs naming no typeface fell back to a bare `sans-serif` (DejaVu Sans here, much wider
than Calibri); they now take the theme body font. Installing Carlito (metric-compatible with
Calibri) fixed the remaining Calibri decks. Letter-spaced and right-to-left lines still differ.
