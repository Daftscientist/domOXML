# PPTX Coverage Matrix

The capability surface of **OOXML PresentationML + DrawingML** (ECMA-376), and where
domOXML stands on each feature — in **both** directions:

- **Forward** — HTML/CSS → editable `.pptx`
- **Reverse** — `.pptx` → typed IR → HTML/CSS (the round-trip / ingest direction)

This is the source of truth for the coverage roadmap and (later) the CI capability
fixtures. It is *not* a copy of the spec — see ECMA-376 §19 (PresentationML) and §20.1
(DrawingML) for the authoritative definitions: <https://ecma-international.org/publications-and-standards/standards/ecma-376/>.

## Legend

| Mark | Meaning |
|------|---------|
| ✅ | native & editable — mapped to native OOXML (fwd) / faithfully recovered (rev) |
| 🟡 | partial — some properties covered |
| 🖼️ | raster fallback — rendered correctly as a layered image, but not editable |
| ⬜ | planned — not implemented yet |
| ⛔ | out of scope — no clean HTML/CSS source (authored from a data/compile spec instead) |

CSS source = what authoring produces it on the forward path.

## Package / structure (PresentationML §19)

| Feature | OOXML | Fwd | Rev | Notes |
|---|---|:--:|:--:|---|
| OPC package (zip, content-types, rels) | OPC | ✅ | ⬜ | `domoxml/slides/pptx.py` |
| Presentation + slide size | `p:presentation`, `p:sldSz` | ✅ | ⬜ | one size per deck |
| Slide / layout / master | `p:sld`, `p:sldLayout`, `p:sldMaster` | ✅ | ⬜ | minimal blank master/layout emitted |
| Theme | `a:theme` (clr/font/fmt scheme) | 🟡 | ⬜ | minimal theme; full scheme resolution pending |
| Placeholder & inheritance | `p:ph`, layout→master→theme | ⬜ | ⬜ | **the hard part of reverse** — effective-style resolution |

## Geometry (DrawingML §20.1)

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Rectangle | `prstGeom prst="rect"` | box | ✅ | ⬜ | |
| Rounded rect | `prstGeom prst="roundRect"` | `border-radius` | ✅ | ⬜ | adj from radius |
| Ellipse / pill | `prstGeom prst="ellipse"` | `border-radius:50%` | ✅ | ⬜ | radius·2 ≥ short side |
| Other presets (187 total) | `ST_ShapeType` | `clip-path`/SVG | ⬜ | ⬜ | triangle, diamond, hexagon, star, arrows, callouts… |
| Custom geometry | `custGeom`/`a:path` | SVG path | ⬜ | ⬜ | |
| Connectors | `cxnSp` | `<hr>`/lines | ⬜ | ⬜ | straight/elbow/curved |

## Fills

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Solid fill (+ alpha) | `a:solidFill`/`a:srgbClr`/`a:alpha` | `background-color`, rgba | ✅ | ⬜ | opacity folded into alpha |
| No fill | `a:noFill` | transparent bg | ✅ | ⬜ | |
| Gradient (linear/radial) | `a:gradFill` | `linear/radial-gradient` | ✅ | ⬜ | conic/layered → raster |
| Picture fill | `a:blipFill` | `background-image:url()`, `<img>` | ✅ | ⬜ | data/web URLs; webp→png |
| Pattern fill | `a:pattFill` | repeating patterns | ⬜ | ⬜ | |
| Theme colour ref | `a:schemeClr` | (theme tokens) | ⬜ | ⬜ | fwd emits srgbClr; rev must resolve scheme |

## Line / stroke

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Solid border | `a:ln`/`a:solidFill` | `border` | ✅ | ⬜ | uniform border |
| Per-side borders | (4 lines) | `border-top` … | 🟡 | ⬜ | approximated by heaviest side + warn |
| Dash / cap / join | `a:prstDash`, `cap`, `a:round` | `border-style`, dashes | 🟡 | ⬜ | solid/dash/dot |
| Arrowheads | `a:headEnd`/`a:tailEnd` | — | ⬜ | ⬜ | |
| Gradient stroke | `a:gradFill` in `a:ln` | — | ⬜ | ⬜ | |

## Effects (`a:effectLst` — 8 native)

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Outer shadow | `a:outerShdw` | `box-shadow` | ✅ | ⬜ | native; spread dropped |
| Inner shadow | `a:innerShdw` | `box-shadow inset` | ✅ | ⬜ | native |
| Glow | `a:glow` | blurred halo | 🖼️ | ⬜ | |
| Blur | `a:blur` | `filter: blur()` | 🖼️ | ⬜ | `filter` → raster (warned) |
| Soft edge | `a:softEdge` | — | 🖼️ | ⬜ | |
| Reflection | `a:reflection` | — | 🖼️ | ⬜ | |
| Preset / fill-overlay | `a:prstShdw`, `a:fillOverlay` | — | 🖼️ | ⬜ | |

## Text (`a:txBody`)

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Run: family/size/bold/italic/colour | `a:rPr`, `a:latin`, `a:solidFill` | font-* / color | ✅ | ⬜ | |
| Run: underline / strike | `u`, `strike` | `text-decoration` | ⬜ | ⬜ | |
| Run: caps / letter-spacing | `cap`, `spc` | `text-transform`, `letter-spacing` | ⬜ | ⬜ | |
| Paragraph align | `a:pPr algn` | `text-align` | ✅ | ⬜ | start/end normalised |
| Vertical anchor | `a:bodyPr anchor` | (block flow) | 🟡 | ⬜ | top default; flex/align mapping pending |
| Line spacing / indent | `a:lnSpc`, `marL` | `line-height`, indent | ⬜ | ⬜ | |
| Bullets / numbering | `a:buChar`/`a:buAutoNum` | `<ul>`/`<ol>` | ⬜ | ⬜ | |
| Multi-column | `a:bodyPr numCol` | `column-count` | ⬜ | ⬜ | |
| Autofit | `a:normAutofit`/`a:spAutoFit` | (overflow) | 🟡 | ⬜ | normAutofit emitted |
| Text warp (WordArt) | `a:prstTxWarp` | — | ⬜ | ⬜ | |
| **Font embedding** | `p:embeddedFontLst` | `@font-face`/`<link>` | ✅ | ⬜ | web+system; woff2/OTF→TTF; warns if unembeddable. NB: Office-online PDF service (Graph) 406s on any custom embed — desktop/LibreOffice honour it |

## Pictures & media

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Image | `a:blipFill` | `<img>` | ✅ | ⬜ | embedded as native picture fill |
| SVG | `a:blip` + svgBlip | inline `<svg>` | 🖼️ | ⬜ | rasterised (warned); svgBlip later |
| Video / audio | `a:videoFile`/`audioFile` | `<video>`/`<audio>` | 🖼️ | ⬜ | poster frame rasterised |
| Decorative raster layer | `a:blipFill` | un-mappable flourish | ✅ | ⬜ | per-element raster; subtree-consuming + warned |

## Tables, charts, transitions, animation

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Table | `a:tbl` (graphicFrame) | `<table>` | ⬜ | ⬜ | native rows/cells/merges |
| Chart | `c:chartSpace` | `<table data-chart>` / spec | ⛔ | ⛔ | data spec, not pixels |
| Transitions | `p:transition` (~17) | `data-transition` | ⬜ | ⬜ | compile-time |
| Animations | `p:timing` | `@keyframes` / spec | ⛔ | ⬜ | compile-time spec |
| SmartArt / OLE / 3D | `dgm:`/`p:oleObj`/`a:sp3d` | — | ⛔ | 🖼️ | rev may rasterise to preserve looks |

## Round-trip methodology

Reverse coverage is validated the same way as forward — by **measured fidelity**
(`core/fidelity`): `pptx → HTML → re-render → compare to the original pptx render`. Each
feature should land with a round-trip fixture so the score is tracked, not eyeballed.
