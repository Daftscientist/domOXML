# Native recipes

A CSS feature that has no one-to-one DrawingML equivalent used to mean a raster. Most of them
have a native recipe: a combination of effects, fills and layers that PowerPoint draws itself.
Whether a recipe works is a question about real PowerPoint, not about the spec, so each one is
**probed first** with `scripts/native_lab.py`, which renders a candidate in LibreOffice and real
PowerPoint side by side, and only then built. This page records what has been measured.

Run a probe:

```bash
source .local/graph.env                      # real PowerPoint (optional; see below)
python scripts/native_lab.py colour scene3d gradients blur-edges blur-scale
python scripts/native_lab.py gradients --no-graph     # LibreOffice only
```

Output lands in `out/native-lab/` (`sheet-<probe>.png`: LibreOffice left, real PowerPoint right).

## Real PowerPoint

`.local/graph_render.py` (git-ignored, your own credentials) uploads a deck to your OneDrive,
converts it with the real Office engine and deletes it. Two things to know:

- Office's PDF export **rejects decks with embedded fonts** (`PPTCannotInstallFonts`), so the tool
  strips them first. Text then renders in a fallback font: judge shapes, fills and effects, not
  text widths or wrapping (use LibreOffice for those).
- Invalid markup fails with `PPTCannotOpenFileMetroFileCorruption`. The lab prints the code, which
  is a free schema check (it caught an out-of-range `a:hsl` and a misspelled camera preset).

## Measured

| Feature | Real PowerPoint | LibreOffice | Used for |
|---|---|---|---|
| Gradient with 40 hard stops / 121 smooth stops | exact | exact | `repeating-linear-gradient` (**shipped**) |
| Gradient with alpha stops | exact | exact | `mask-image` fades (next) |
| `a:blur` on a picture, `grow="0"`, rotated and rounded | blurs inside the outline, edge stays crisp | ignored | `backdrop-filter` (**shipped**) |
| `a:blur grow="1"` | blur bleeds past the edge | ignored | not used |
| `a:blur rad` vs CSS blur sigma | best scale **3x** at sigma 4, 8, 16 px | n/a | `DRAWINGML_BLUR_RADIUS_PER_CSS_SIGMA` |
| `a14:artisticBlur` (Artistic Effects) | **not rendered**; only the UI recomputes it | not rendered | dead end |
| `a:blip` blur child | the picture **vanishes** | ignored | dead end |
| `a:blip` `grayscl`, `lum`, `duotone`, `alphaModFix`, `clrChange` | exact | exact | CSS `filter` on images |
| `a:blip` `biLevel` | works, different threshold | works | approximate only |
| `a:blip` `hsl` | takes **absolute** h/s/l (colourizes), so no hue-rotate | ignored | dead end |
| `bodyPr` 3-D `rot lon=180` | mirrors only the text | different | "CSS flip mirrors text" |
| `scene3d` `perspectiveLeft` / `perspectiveRelaxed` | distorts shape and text | different | 3-D / perspective transforms |

## What is not possible

Nothing in OOXML links one object's rendering to another's. A backdrop blur is therefore a
snapshot of what was behind the glass when the deck was written: the blur radius is a real,
editable setting and the glass moves and edits natively, but moving the card underneath does not
recompute the blur in PowerPoint.

## Adding a recipe

1. Add a probe to `scripts/native_lab.py` for the candidate markup and read the sheet.
2. If real PowerPoint honours it, build it behind the extractor's single raster decision, with an
   owned fallback for renderers that ignore it, and make the reverse path recognise it.
3. Prove it with a test that fails without the change, and put the before/after renders in
   `docs/review-assets/<name>/` for the PR.
