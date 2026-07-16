# PPTX Coverage Matrix

The capability surface of **OOXML PresentationML + DrawingML** (ECMA-376), and where
domOXML stands on each feature — in **both** directions:

- **Forward** — HTML/CSS → editable `.pptx`
- **Reverse** — `.pptx` → typed canvas IR → HTML/CSS (the round-trip / ingest direction)

This is the source of truth for the coverage roadmap and CI capability fixtures. A feature is
bidirectional only when the capability runner executes both paths; manifest direction metadata by
itself is not proof. It is *not* a copy of the spec — see ECMA-376 §19 (PresentationML) and §20.1
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
| OPC package (zip, content-types, rels) | OPC | ✅ | ✅ | shared reader/writer primitives |
| Presentation + slide size | `p:presentation`, `p:sldSz` | ✅ | ✅ | one size per deck |
| Slide / layout / master | `p:sld`, `p:sldLayout`, `p:sldMaster` | ✅ | ✅ | rev resolves placeholder geometry/text through layout→master |
| Theme | `a:theme` (clr/font/fmt scheme) | 🟡 | ✅ | colour scheme + clrMap remap + font scheme (+mj-lt/+mn-lt) resolved |
| Placeholder & inheritance | `p:ph`, layout→master→theme | ⬜ | ✅ | effective-style resolution: xfrm/spPr chain, txStyles (title/body/other) per lvl, slide-level overrides |

## Geometry (DrawingML §20.1)

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Rectangle | `prstGeom prst="rect"` | box | ✅ | ✅ | |
| Rounded rect | `prstGeom prst="roundRect"` | `border-radius` | ✅ | ✅ | adj from radius |
| Ellipse / pill | `prstGeom prst="ellipse"` | `border-radius:50%` | ✅ | ✅ | radius·2 ≥ short side |
| Other presets (187 total) | `ST_ShapeType` | `clip-path`/SVG | 🟡 | 🟡 | 17 polygon-expressible presets covered: triangle, rtTriangle, diamond, pentagon, hexagon, octagon, parallelogram, trapezoid, chevron, rightArrow, leftArrow, upArrow, downArrow, plus, star4, star5, star8. Curved presets (arc, callout, gear, wave, funnel, …) pending. |
| Custom geometry | `custGeom`/`a:path` | SVG path | 🟡 | 🟡 | **Fwd**: inline `<svg>` with single `<path>`, M/L/C/Q/H/V/Z subset → `a:custGeom`; S/T/A bail to raster+warn; multi-path/complex SVG rasters. **Rev**: `a:custGeom` → inline `<svg><path d="..."/>`, fill+stroke applied; formula-driven `gdLst` paths preserved+warn. |
| Connectors | `cxnSp` | `<hr>`/lines | 🟡 | 🟡 | **Fwd**: `<hr>` and unfilled elements ≤2px tall & ≥40px wide (or vertical equiv) → `p:cxnSp prst="line"`. **Rev**: straight → SVG `<line>`; bent/curved → SVG `<path>`; arrowheads → SVG `<marker>` (triangle, scaled coarsely). |

## Fills

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Solid fill (+ alpha) | `a:solidFill`/`a:srgbClr`/`a:alpha` | `background-color`, rgba | ✅ | ✅ | opacity folded into alpha |
| No fill | `a:noFill` | transparent bg | ✅ | ✅ | |
| Gradient (linear/radial) | `a:gradFill` | `linear/radial-gradient` | ✅ | ✅ | shape gradients use aspect-corrected angles and subdivided sRGB stops to match PowerPoint's linear-light interpolation |
| Picture fill | `a:blipFill` | `background-image:url()`, `<img>` | ✅ | ✅ | shape fill and native `p:pic`; **shape blipFill crop done** — `background-size:cover` → `a:srcRect` (fwd), `a:srcRect` → `background-size`/`-position` % (rev). `contain`/explicit sizes stretch (no crop) |
| Pattern fill | `a:pattFill` | `repeating-linear-gradient` | 🟡 | 🟡 | **Fwd**: calibrated 2-colour hard-stop stripes at 0/45/90/135deg map to 6 native presets; noncanonical density, 3+ colours, soft stops, and off-axis patterns rasterise. **Rev**: those presets emit canonical CSS; other ECMA presets use an SVG-tile approximation + warning. Hatch density varies between PowerPoint and LibreOffice, so this family is portability-sensitive. |
| Theme colour ref | `a:schemeClr` | (theme tokens) | ⬜ | ✅ | clrScheme lookup + clrMap remap + lumMod/lumOff/shade/tint/alpha/satMod transforms |

## Line / stroke

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Solid border | `a:ln`/`a:solidFill` | `border` | ✅ | ✅ | uniform border |
| Per-side borders | 4 thin `p:sp` rects | `border-top` … | ✅ | ✅ | fwd: decomposed into per-side rects (radius+non-uniform → heaviest-side + warn); rev: n/a (they're just rects) |
| Dash / cap / join | `a:prstDash`, `cap`, `a:round`/`a:bevel`/`a:miter` | `border-style`, `--domoxml-cap/join` | ✅ | ✅ | fwd: dotted→sysDot, dashed→dash, double/3D→solid+warn; rev: full preset table + cap/join; CSS custom props carry cap/join for round-trip |
| Arrowheads | `a:headEnd`/`a:tailEnd` | `--domoxml-head/tail` | ⬜ | 🟡 | rev: type/w/len read into IR + CSS custom props; rendering deferred to connectors task; warning emitted |
| Gradient stroke | `a:gradFill` in `a:ln` | `border-image: linear-gradient(...) 1` | ⬜ | 🟡 | rev: gradient read into `Line.gradient`; HTML approx via `border-image` (border-radius not honoured); warning emitted |

## Effects (`a:effectLst` — 8 native)

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Outer shadow | `a:outerShdw` | `box-shadow` | 🟡 | ✅ | spread → sx/sy grow attrs; CSS blur is calibrated to DrawingML's different falloff; warns if spread >25% of short side |
| Inner shadow | `a:innerShdw` | `box-shadow inset` | 🖼️ | ✅ | authored CSS inset shadows rasterise because LibreOffice ignores `a:innerShdw`; native reverse/read-write support remains |
| Glow | `a:glow` | blurred halo | 🟡 | 🟡 | fwd: zero-offset box-shadow → calibrated `a:glow`; rev: box-shadow 0 0 rad rad/2 approximation |
| Blur | `a:blur` | `filter: blur()` | 🖼️ | 🟡 | `filter` → raster (warned); rev: filter:blur() + rasterise-on-forward warning |
| Soft edge | `a:softEdge` | — | 🖼️ | 🟡 | rev: mask-image radial-gradient feathering approximation |
| Reflection | `a:reflection` | — | 🖼️ | 🟡 | rev: -webkit-box-reflect + preserved fragment; fwd will rasterise; WebKit/Blink only |
| Preset shadow | `a:prstShdw` | — | 🖼️ | preserved | PreservedFragment + ConversionWarning; no CSS mapping |
| Fill overlay | `a:fillOverlay` | — | 🖼️ | preserved | PreservedFragment + ConversionWarning; no CSS mapping |

## Text (`a:txBody`)

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Run: family/size/bold/italic/colour | `a:rPr`, `a:latin`, `a:solidFill` | font-* / color | ✅ | ✅ | |
| Run: underline / strike | `u`, `strike` | `text-decoration` | ✅ | ✅ | both coexist; style tokens kept on rev |
| Run: caps / letter-spacing | `cap`, `spc` | `text-transform`, `letter-spacing` | ✅ | ✅ | raw text + cap attr (not pre-cased); spc in 1/100 pt |
| Run: hyperlink | `a:hlinkClick` (+ rel) | `<a href>` | ✅ | ✅ | external rel; `#slide-N` → in-deck slide jump |
| Paragraph align | `a:pPr algn` | `text-align` | ✅ | ✅ | start/end normalised |
| Vertical anchor + text insets | `a:bodyPr anchor`, `lIns`/`tIns`/`rIns`/`bIns` | block flow + padding | ✅ | ✅ | fwd: flex column containers map vertical alignment to t/ctr/b and container padding to text-body insets; rev restores flex alignment and padding |
| Line spacing / indent | `a:lnSpc`, `marL` | `line-height`, indent | ✅ | ✅ | percent (spcPct) and points (spcPts); marL/indent in EMU |
| Bullets / numbering | `a:buChar`/`a:buAutoNum` | `<ul>`/`<ol>` | ✅ | ✅ | char bullets (disc/circle/square) + autonumber (arabic/alpha/roman); nested levels; fwd+rev |
| Multi-column | `a:bodyPr numCol` | `column-count` + `column-fill:auto` | ✅ | ✅ | PowerPoint fills columns sequentially; fwd maps column-count/column-gap and warns when balanced CSS columns are approximated; rev emits sequential-fill CSS |
| Autofit | `a:normAutofit`/`a:spAutoFit` | (overflow) | 🟡 | 🟡 | fwd: overflow:hidden + fixed height → normAutofit; white-space:nowrap → spAutoFit; default → normAutofit. rev: spAutoFit/noAutofit carried in IR; autofit != "normal" → data-domoxml-autofit metadata attribute; normAutofit fontScale/lnSpcReduction: not mapped to CSS (no fontScale in IR), emitted as metadata only when present on reverse path |
| Text warp (WordArt) | `a:prstTxWarp` | — | ⬜ | ⬜ | |
| **Font embedding** | `p:embeddedFontLst` | `@font-face`/`<link>` | ✅ | ✅ | Fwd: web+system; woff2/OTF→TTF; warns if unembeddable. Rev: ODTTF deobfuscation; OS/2 fsType restricted-license check; `@font-face` + `HtmlAsset` per slot. NB: Office-online PDF service (Graph) 406s on any custom embed — desktop/LibreOffice honour it |

## Pictures & media

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Image | `a:blipFill` | `<img>` | ✅ | ✅ | embedded as native picture fill |
| SVG (vector preserved) | `a:blip` + `asvg:svgBlip` | `<img src="*.svg">` / inline `<svg>` | ✅ | ✅ | PNG raster fallback + SVG svgBlip ext; reverse picks SVG over PNG |
| Picture crop | `a:srcRect` | `object-fit:cover` | ✅ | ✅ | forward: cover\_crop math → srcRect; reverse: wrapper+img CSS via srcrect\_to\_css |
| Video / audio | `p:videoFile`/`p:audioFile` | `<video>`/`<audio>` | 🖼️ | ✅ | rev: embedded or external media → `<video controls>` / `<audio controls>`; play settings preserved |
| Decorative raster layer | `a:blipFill` `cNvPr descr` marker | un-mappable flourish | 🖼️ | ✅ | forward writes `domoxml-raster:<role>` marker; reverse restores `<img data-domoxml-raster>` |

## Transforms and groups

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Rotation | `a:xfrm rot` | `transform:rotate(Ndeg)` | ✅ | ✅ | CSS degrees = OOXML 60000ths-of-degree (both clockwise-positive). Pre-transform layout dimensions are recovered before emitting rotation. Non-center origins rasterise with a warning. |
| Horizontal flip | `a:xfrm flipH="1"` | `transform:scaleX(-1)` | 🟡 | 🟡 | Native for shapes without text; CSS flips text while PowerPoint keeps shape text readable, so forward text-bearing flips rasterise rather than silently changing semantics. |
| Vertical flip | `a:xfrm flipV="1"` | `transform:scaleY(-1)` | 🟡 | 🟡 | Same text-portability constraint as horizontal flips. |
| Complex transforms (shear, perspective) | — | `skewX/Y`, `perspective`, `matrix` with shear | 🖼️ | — | Still rasterised with ConversionWarning; not expressible via `a:xfrm`. |
| Group shapes | `p:grpSp` | (flat div layout) | ⬜ | ✅ | **Fwd**: children emitted as flat siblings (no `p:grpSp` authored). **Rev**: child coordinates remapped from group-child-space to absolute slide EMUs (`child_slide_x = grp_off_x + (child_x − grp_chOff_x) × scale_x`); flattened to flat positioned divs. Group transform (rot/flip on the group itself) preserved via `Transform` IR node. |

## Tables, charts, transitions, animation

| Feature | OOXML | CSS source | Fwd | Rev | Notes |
|---|---|---|:--:|:--:|---|
| Table | `a:tbl` (graphicFrame) | `<table>` | ✅ | ✅ | native rows/cells/merges; col/row spans; cell fill, borders, margins; text bodies |
| Chart | `c:chartSpace` | `<table data-chart>` / spec | ⛔ | ⛔ | data spec, not pixels |
| Transitions | `p:transition` (~17) | `data-transition` | ✅ | ✅ | compile-time |
| Animations | `p:timing` | `@keyframes` / spec | ⛔ | 🗃️ | rev preserved as fragment + warning |
| SmartArt / OLE / 3D | `dgm:`/`p:oleObj`/`a:sp3d` | — | ⛔ | 🗃️ | rev preserved as fragment + warning |

## Round-trip methodology

Reverse coverage is validated the same way as forward — by **measured fidelity**
(`core/fidelity`): `pptx → HTML → re-render → compare to the original pptx render`. Each
feature should land with a round-trip fixture so the score is tracked, not eyeballed.

HTML/CSS is the public web format, not a claim that CSS can losslessly encode every PowerPoint
feature. See [`architecture.md`](architecture.md) for the preservation and fallback rules.
