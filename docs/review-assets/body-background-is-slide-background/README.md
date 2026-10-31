# Body Background Is The Slide Background Evidence

For ordinary HTML (no `.domoxml-slide` opt-in) the `<body>` background was emitted as a full-slide
*shape*, so every deck carried a giant rectangle at the bottom of the z-order. An authored
full-slide container repeating the same colour (here `<main>`) then added a second identical
rectangle on top. Both are selectable and draggable in PowerPoint, and neither is a real slide
background.

Browsers paint the body's background over the whole canvas, so it is the slide background. When
the body spans the slide and paints nothing but a fill, it now becomes the native slide
background (`p:bg`). A full-slide element that only repeats that exact opaque colour and is
drawn before anything else adds nothing the background does not already paint, so it is folded
in too. Anything that paints more (border, radius, shadow, filter, transform, opacity, text, a
different colour) or that sits over other content is left alone.

| Source (Chrome) | Before (`main`, LibreOffice) | After (this PR, LibreOffice) |
|---|---|---|
| ![Source](source.png) | ![Before](before-main.png) | ![After](after.png) |

## Evidence

| | Before | After |
|---|---:|---:|
| `p:bg` on the slide | none | solid `F2F1EA` |
| Shapes in the PPTX | 43 | 41 (both full-slide rectangles gone) |
| LibreOffice render vs before | - | pixel-identical (mean abs diff 0.0, 0 pixels > 2) |

Real-Chromium tests (all fail on `main`): body background becomes the slide background; a
same-colour full-slide container is folded in; a different colour stays a shape; a same-colour
shape drawn over other content stays; a rounded full-slide shape stays; a gradient body becomes a
native gradient background.

## Capability fixture floors

The capability fixtures pin exact element counts (min = max). Several were calibrated when the
body, and an authored full-slide `.slide` container, were each counted as a native *shape*. They
are now the native slide background, so those elements no longer exist as shapes.

26 fixtures move, and the movement is purely a count. Measured against `capability_check.py`
before editing: 313 failing bounds, all `count N < expected minimum M` (291 off by one, 22 off by
two for fixtures with two stacked full-slide rectangles), **0** similarity failures, **0**
structural failures, **0** "too many". Each bound was lowered to the measured value by script;
real ranges (min < max) are untouched. After the update `capability_check.py`,
`real_deck_check.py` and `fidelity_check.py` all pass with the CI flags.

## Expected lossy behaviour (not part of this change)

The glass card is still a flat image and native PowerPoint text is still ~4px offset in
LibreOffice; neither is changed here.
