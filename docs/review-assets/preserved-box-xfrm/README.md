# Preserved object lands at its box

`real-decks/pptx/external-chart-preservation` slide 2, its chart (a `PreservedNode`) moved right by
2,000,000 EMU and down by 600,000 EMU and halved in size, then built with `build_pptx` and rendered
with LibreOffice.

- `before.png` (main): the chart is written at its original position and size; the box is ignored.
- `after.png` (this branch): the chart is written at its box, still a native chart part.
