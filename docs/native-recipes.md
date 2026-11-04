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
| shape `scene3d` `perspectiveFront` + `rot lon=20°` with `fov` 0 / 20 / 40 / 60 / 80 / 100° (re-probed after the 3-D container work) | foreshortening is invisible at `fov` ≤ 40° and CSS-like at ≥ 60° (left edge ~1.4× the right at 100°); the fill warps as a quad and the width follows cos(lon); text stays readable at a 20° turn | ignored | a native carrier for *text* inside perspective containers is possible, but needs a calibrated `fov`↔`perspective()` map and a `Transform3D` in the IR; until then such text keeps its isolated raster (boxes are native quads, #107) |
| `custGeom` polygon in the box's own coordinate space | exact for `clip-path` circle/ellipse/inset/polygon, skew and perspective quads, and ancestor `overflow` cropping; fills still map to the whole box | exact | geometry batch (**shipped**) |
| `bodyPr` 3-D `lon=180` plus swapped left/right paragraph alignment | mirrored text lands where CSS `scaleX(-1)` puts it | ignores the mirror (text reads normally) | flipped text (**shipped**) |
| `backdrop-filter: blur() saturate()` as a recoloured sharp backdrop picture under a live `a:blur` | matches Chrome (glass keeps its saturation, blur stays editable) | fallback picture | backdrop colour maths (**shipped**) |
| `a:reflection` from `-webkit-box-reflect` with implicit 0-100% stops | matches Chrome | fallback picture | box reflection (**shipped**) |
| SVG `feGaussianBlur` on a path as `a:blur` scaled by the viewBox factor | matches | ignored (fallback picture) | SVG blur (**shipped**) |
| `a:blip` + `asvg:svgBlip` extension (PNG fallback) | **draws the SVG as vector**: gradients, `stroke-dasharray`, paths all exact | uses the PNG fallback | canvas/SVG interim, vector embeds |
| `p:pic` with `a:videoFile r:link` to an external URL (online video) | accepted; shows the poster | poster | `<iframe>` to YouTube/Vimeo |
| 3-D model part (`am3d:model3d`, GLB) with PNG fallback | accepted; server render shows the raster at the frame's box | fallback | 3-D content; implemented as `MediaNode(kind="model")` both ways: `<model-viewer src="data:model/gltf-binary…" poster>` ↔ the model frame (the camera, transform and lights PowerPoint saved ride along in `play_settings_xml`) |
| Web extension frame (`we:webextensionref`, Web Viewer `WA104295837`) | accepted; renders its snapshot image (the add-in itself only runs in desktop PowerPoint) | ignored | `<iframe src="https://…">` to a web page (live only in desktop PowerPoint); implemented as `MediaNode(kind="web")` both ways |
| `p:pic` + `a:videoFile r:link` + `p14:media r:embed` (embedded clip), or `a:videoFile` to a YouTube/Vimeo embed URL (online video) | accepted and drawn as the poster picture; plays in PowerPoint | poster | `<video>`, `<audio>`, `<iframe>` player (**shipped**) |
| SVG filters inside `svgBlip`: `feGaussianBlur`, `feTurbulence`, `mask` | **drawn** (blur, procedural noise, alpha mask) | wrong: 0.84 and 0.06 similarity vs Chrome | not shipped: LibreOffice would show junk, so filter SVGs keep their raster |
| `feDropShadow` inside `svgBlip` | **not drawn at all** | n/a | avoid; use blur + offset + merge |

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
