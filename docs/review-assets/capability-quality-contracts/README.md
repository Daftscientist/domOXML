# Capability quality contracts

Render evidence for the repeated-ingestion and quality-ratchet change.

## Forward renderer evidence

The bullet and table triplets compare the Chromium HTML source with the aligned LibreOffice PPTX
render. They retain the existing renderer-specific font-metric differences rather than hiding them:

- bullets: global `0.992`, regional `0.950`, structural `0.945`;
- table: global `0.998`, regional `0.983`, structural `0.961`.

## Repeated-ingestion evidence

`cycle1`/`cycle2` and `cycle2`/`cycle3` compare browser renders after rebuilding and re-ingesting
the previous cycle's PPTX. The bullet and table diffs are exact black zero-diff renders. The chart
render is non-identical at `0.999`, with only the faint residue visible in its attached diff.

- bullets: cycle 2 global/regional/structural `1.000 / 1.000 / 1.000`, with 14 outputs in both
  cycles;
- table: cycle 2 `1.000 / 1.000 / 1.000`, with exact box, column, and row geometry retained by the
  versioned table-geometry payload;
- attached chart slide: cycle 3 `0.999 / 0.999 / 0.999`, with 79 native visuals, one attached
  element layer, 80 outputs, and unchanged raster area.
