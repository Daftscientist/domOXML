# domOXML Architecture

domOXML is a parity-first document compiler. It gives people and agents an authoring surface
they already understand - HTML and CSS - and translates that source through typed internal
primitives into editable document formats. PowerPoint is the first target to complete; image and
normalized HTML output already share the same pipeline, and DOCX, XLSX, PDF, and other adapters
can follow without making OOXML the centre of the system.

```text
HTML/CSS -------- browser capture -----------+
PPTX ------------ package/semantic reader ---+--> canonical IR
future inputs -------------------------------+          |
                                                        +--> normalized HTML/CSS
                                                        +--> PPTX
                                                        +--> PNG/image layers
                                                        +--> future PDF/DOCX/XLSX outputs
```

The architecture is defined by the invariants below. Current implementation status and the
ordered work needed to reach them are recorded in
[`implementation-roadmap.md`](implementation-roadmap.md). Schema and capability surfaces are in
the [`inventory-shared.md`](inventory-shared.md) and format-specific inventory documents.

## Product Invariants

1. **HTML/CSS is the primary authoring language.** It is ordinary browser HTML and CSS, including
   inline CSS, not a proprietary template dialect.
2. **The IR is canonical.** HTML and PPTX are import/export adapters. Neither format is the
   internal source of truth after ingestion.
3. **Visible content always has a parity path.** A conversion may become less semantically
   editable, but it must not become visibly absent merely because a native mapping is missing.
4. **Prefer the most editable parity-preserving representation.** Native primitives come first;
   decomposition, hybrid output, and minimal raster layers close the remaining gap.
5. **Forward and reverse are one capability.** A feature is incomplete until both adapters and
   repeated round trips use the same IR contract.
6. **Repeated conversion converges.** `HTML -> PPTX -> HTML -> PPTX` and the reverse sequence must
   not accumulate visible or structural degradation.
7. **No silent loss.** Every source visual has a representation record. Useful nonvisual data is
   mapped or preserved; intentionally ignored metadata is declared by policy.
8. **Shared means format-independent.** Packaging, DrawingML, styling, geometry, text, media,
   fidelity, and preservation do not belong in PPTX/DOCX/XLSX orchestration modules.
9. **The library remains usable during development.** Missing native coverage is engineering debt,
   not a reason to fail an otherwise renderable document.

## Resolved Input State

HTML can be dynamic while PPTX is a fixed-layout document. HTML ingestion therefore compiles one
resolved browser state. The capture contract includes:

- viewport and output page dimensions;
- loaded fonts and assets;
- computed styles, layout boxes, stacking contexts, clipping, and transforms;
- a selected animation time and interaction state when applicable;
- deterministic handling of pseudo-elements, generated content, SVG, canvas, and replaced media.

JavaScript behavior is not itself exported to PPTX. Its resolved visible state is. Nonstandard or
browser-specific CSS is acceptable when Chromium can resolve and paint it; the representation
planner may use layered output when there is no native Office equivalent.

PPTX ingestion similarly resolves package relationships and effective values across slide,
layout, master, theme, and extension parts before serialization to HTML or another output.

## Internal Model

A single universal layout model would incorrectly force presentations, flowing documents, and
spreadsheets into the same structure. domOXML instead has document-family roots built from shared
primitives:

| IR family | Primary formats | Layout model |
|---|---|---|
| Canvas IR | PPTX, slide HTML, images, PDF pages | fixed page, ordered positioned nodes |
| Flow IR | semantic HTML, DOCX, future paginated documents | sections, blocks, inline content, pagination constraints |
| Grid/data IR | XLSX, table/data imports | sheets, cells, formulas, tables, charts |

The Canvas IR contains one canonical ordered `contents` sequence. Legacy `shapes` and `nodes`
constructor arguments and filtered accessors remain compatibility views, but importers and
serializers operate on `contents` so heterogeneous nodes retain interleaved z-order. Every node
adopted by a slide has a stable slide-scoped ID; active HTML and PPTX adapters also retain typed
source provenance through normalized HTML metadata and a private OOXML extension. Exact
stacking/group ownership and preservation ownership beyond positioned nodes with capturable OPC
graphs still need to be completed in addition to the existing geometry and appearance. Both HTML
capture and PPTX ingestion emit a per-source-visual coverage report; normalized HTML carries the
report on its public presentation result alongside warnings and preserved source fragments.

Shared primitives include:

- units, page boxes, points, transforms, paths, clips, and stacking;
- colors, theme references and transforms, fills, strokes, and effects;
- fonts, runs, paragraphs, lists, text boxes, and text measurement;
- images, SVG, audio, video, charts, tables, and reusable assets;
- warnings, provenance, preservation payloads, and capability records;
- OPC packages, relationships, content types, XML namespaces, and extension handling;
- renderer-independent fidelity evidence and structural comparison.

Each IR may retain both author intent and resolved paint data. HTML import naturally starts with
CSS rules and computed layout; PPTX import often starts with positioned semantic objects. Keeping
both avoids discarding semantics merely to obtain pixels.

## Representation Planner

Every visible source subtree is lowered using the first level that meets the fidelity contract:

| Level | Meaning | Editability |
|---|---|---|
| Native | one target primitive represents the feature | semantic and object editable |
| Decomposed | several native primitives reproduce it | components editable; source relation retained |
| Hybrid | semantic/native content plus rasterized effect, decoration, or renderer-selective fallback layers | core content editable; visible layers movable where simultaneously emitted |
| Layered | the smallest practical independent raster layers reproduce the source | layers independently movable and replaceable |
| Element layer | one rasterized source subtree when finer separation is not reliable | element movable as one object |
| Rasterized | source pixels remain visible but independent ownership cannot be proved | noneditable; source payload may still be retained |

The runtime coverage record keeps representation separate from editability and preservation. Each
source visual records its representation level, strongest retained editing model, source-retention
state, emitted object count, raster area, and a reason for every non-native choice. `Approximated`
and `Failed` are explicit diagnostic outcomes rather than planner levels: approximation requires a
reviewed reason, while failure records a visible-output defect and cannot count as editable output.
`Rasterized` is not failure: it records visible source pixels whose crop may contain inseparable
surrounding pixels and therefore cannot claim layer editability.

Approximation is not the default escape hatch. It is allowed only as a deliberate, documented
portability mode or when the user selects it. If a native PowerPoint gradient, shadow, glow, path,
or text capability can match the source, implementation should keep improving that native mapping
rather than labelling the feature inherently approximate.

Rasterization is a compatibility backend, not an error. It must:

- select the smallest reliable paint boundary;
- preserve alpha, overflow, clipping, and exact placement;
- preserve original stacking and grouping;
- avoid duplicating content retained natively;
- label layer role and source ownership for stable re-ingestion;
- report semantic editability debt independently of visual fidelity.

Renderer-selective hybrids use markup compatibility when a native Office effect is editable and
available in PowerPoint but not painted by another supported renderer. The semantic choice remains
authoritative; an isolated paint-bound fallback is emitted above it for exact output and as the sole
branch for incompatible renderers, measured as raster area, and recovered beside the native node on
re-ingestion. Blur, conservative below-shape CSS reflection, and the strict two-axis CSS soft-edge
mask use a PowerPoint 2015 choice containing the native effect plus its portable layer, with the
same picture selected alone by LibreOffice. Solid fill overlays using multiply, screen, darken, or
lighten use the exact native effect alone in the PowerPoint choice and the portable picture only in
the LibreOffice fallback branch; stacking both caused visible one-pixel edges on non-pixel-aligned
geometry. Blur and reflection bounds include their full overflow; soft edge and fill overlay use
the shape paint box, expanded to its axis-aligned painted bounds after rotation. Normalized
rectangles use the same two-axis mask, while normalized ellipses
use a boundary-following closest-side radial mask. Nondefault authored mask geometry does not enter
this hybrid path and remains visible through the general element-layer fallback.
DrawingML's `over` fill-overlay mode is not treated as CSS `normal`: direct Graph inspection proves
that mapping false. An isolated opaque rectangle can use a geometry-masked owned crop; the exact
source shape and isolated fallback then travel together through `AlternateContent`, avoiding
repeated screenshot resampling. Crops that cannot prove isolation remain visible with attached
source payload but report `rasterized` and noneditable rather than falsely claiming a movable
element layer. The admitted path's payload, rotated paint bounds, coverage, fallback bytes, and
pixels remain stable through two normalized HTML rebuild cycles.
Normalized fill-overlay recovery requires exact RGB and blend tokens while admitting at most one
8-bit alpha quantum, matching Chromium computed-color serialization without accepting a visibly
different overlay. The admitted overlay layer must cover the whole shape using the default
background origin and clip. Partial background geometry or stale encoded effect metadata takes the
owned visible element-layer path rather than producing a different native composition.

## Direction Contract

A shared capability normally implements five operations:

```text
HTML/CSS -> semantic/resolved IR
PPTX     -> semantic/resolved IR
IR       -> PPTX
IR       -> normalized HTML/CSS
IR       -> image/layer output
```

Import and export are not mirror-image XML functions. Each adapter may lower one semantic object
into several target objects, and each format contains private extensions. The shared capability
contract therefore includes:

- canonical IR representation and normalization rules;
- import mapping from every active source format;
- export mapping to every active target format;
- native/decomposed/hybrid/layered selection rules;
- preservation and re-emission rules for source-only data;
- structural, semantic, visual, and repeated-round-trip fixtures.

Normalized HTML is deterministic browser-renderable output. Narrow `data-domoxml-*` metadata is
allowed where CSS cannot carry editability, source grouping, or an Office semantic. The visible
document must remain useful without proprietary metadata, while metadata-aware re-ingestion should
recover the richer IR. Metadata currently retains source provenance; versioned typed payloads retain
attached preservation graphs, effects, text-body semantics, and exact table geometry. Typed
connector JSON retains the canonical route beside renderer-facing HTML; current PPTX ingestion
derives that route and its endpoints from the connector transform box, so coverage reports the
result as approximated with source detail lost. Geometry emitted to Chromium is
normalized to its 1/64-pixel layout grid so repeated ingestion cannot accumulate subpixel drift.

## Shared And Format-Specific Ownership

| Shared ownership | PPTX-specific ownership |
|---|---|
| canonical Canvas primitives and representation planner | presentation and slide ordering |
| browser capture, layout, paint, and layer extraction | slide masters, layouts, and placeholders |
| DrawingML geometry, text, fills, lines, effects, tables, charts, and media | slide notes and presentation metadata |
| themes, fonts, colors, assets, and relationships | transitions, timing, and presentation playback |
| OPC package reading/writing and extension preservation | PresentationML part traversal and inheritance |
| HTML/CSS and image serializers | mapping PresentationML parts to/from shared IR |
| fidelity, corpus, and round-trip infrastructure | PPTX-specific validation and Microsoft-render baselines |

PPTX orchestration modules allocate parts and relationships, preserve ordering, resolve
presentation inheritance, and dispatch to shared feature adapters. They must not become alternate
implementations of text, geometry, effects, media, or tables.

Every generated or re-emitted PPTX is validated before it leaves the package builder. The shared
OPC gate checks content-type coverage, relationship-part ownership, duplicate relationship IDs,
internal targets, XML parseability, and every namespaced relationship reference. The PPTX gate then
checks the office-document root, presentation/slide/master/layout/theme graph, positive slide size,
required PresentationML roots and shape trees, slide reachability, and unique nonvisual shape IDs.
Capability and real-deck runners assert the same gate independently so validation cannot be bypassed
silently by a future output path. This is a deterministic structural contract, not a claim of full
ECMA-376 XSD validation; Strict packages, AlternateContent, extension schemas, and tolerated
producer deviations remain corpus and schema work.

DOCX will add flow-specific sections, styles, headers/footers, fields, pagination, footnotes, and
WordprocessingML bindings. XLSX will add workbooks, sheets, cells, formulas, conditional formats,
and SpreadsheetML bindings. Their difficulty is not zero, but neither should recreate shared OOXML
or rendering primitives already proven by PPTX.

## Nonvisual Data Policy

Parity applies to visible document output and useful authoring semantics. It does not require a
public API for every enterprise collaboration feature.

| Policy | Examples |
|---|---|
| First-class model | speaker notes, hyperlinks, accessibility text, useful document metadata |
| Preserve and re-emit | unknown extensions and useful source features awaiting a native adapter |
| Intentionally ignore | comments/review history or obscure collaboration state explicitly excluded from product scope |

Preservation is not visual support. A positioned preserved node may now carry both its transitive
OPC graph and a renderer-derived element crop: normalized HTML displays the crop, while
metadata-aware re-ingestion retains the original source object for PPTX re-emission. The chart
fixture proves this path with an authoritative caller-supplied slide render. The crop is not folded
into the opaque source payload, so visual and source ownership remain independently measurable.
When a positioned node has a render but its OPC graph cannot be attached safely, the crop remains a
stable picture layer and the source fragment stays explicitly detached. Preserved families without
a positioned node or render remain nonvisual debt; storing fragments only in a result object is an
intermediate safeguard, not parity.

## Fidelity And Regression System

Fidelity is a multidimensional contract, not one whole-slide similarity number:

- global pixels and color distribution;
- worst-region similarity so small objects cannot disappear unnoticed;
- fine-grid focused similarity over the worst two percent of regions so local typography and
  compact-object drift cannot be diluted by nearby matching fill or whitespace;
- structural edges, geometry, text boxes, and stacking;
- semantic/native editability and fallback granularity;
- package validity, relationships, and source-extension preservation;
- stability over repeated conversions;
- direct visual review of changed evidence.

Reference conditions must pin viewport, fonts, asset state, DPI, renderer version, and target
platform. Chromium is the HTML reference renderer. LibreOffice supplies a fast CI signal but is
not a substitute for PowerPoint. Microsoft Graph or desktop PowerPoint baselines cover
renderer-sensitive behavior and release gates. Fidelity artifacts retain the untouched renderer
PNG beside any candidate resized onto the reference canvas, so review can distinguish real framing
and resolution from comparison normalization.

The test estate has complementary tiers:

| Tier | Purpose |
|---|---|
| Unit tests | parser, resolver, layout, XML, and serializer behavior |
| Atomic capability fixtures | one shared feature in both directions with structural and visual gates |
| Adversarial fixtures | interactions among effects, transforms, clipping, text, groups, and stacking |
| Authored HTML corpus | representative HTML/CSS designs, including nonstandard browser behavior |
| Real PPTX corpus | complex Microsoft and third-party decks, extensions, and malformed-but-tolerated files |
| Repeated round trips | convergence, preservation, native coverage, and layer-granularity ratchets |

Incomplete complex cases remain in the corpus with explicit baselines. CI should reject any
regression while allowing metrics and native coverage to improve monotonically. A score alone
cannot approve parity evidence that is visibly wrong.

Each atomic capability manifest independently bounds the forward and regenerated-PPTX boundaries.
Reverse-capable manifests additionally bound the initial PPTX-ingest boundary. All bounds cover
representation, editability, source retention, emitted object count, and raster area. These
fixtures also declare the number of rebuild/re-ingest cycles and global, regional, and structural
convergence floors. Slide scoping must be explicit when one fixture owns only part of a
multi-feature source deck; unscoped slides are not thereby claimed as covered.

## Documentation Authority

- This document owns product invariants, boundaries, and the target architecture.
- [`implementation-roadmap.md`](implementation-roadmap.md) owns current state, sequencing, and
  measurable exit gates.
- [`inventory-shared.md`](inventory-shared.md) owns shared capability status and the exhaustive
  shared schema surface.
- [`inventory-pptx.md`](inventory-pptx.md) owns PresentationML-specific status and schema surface.
- DOCX and XLSX inventories remain schema references until those adapters become active.
- Executable fixtures and verified tests override stale prose when implementation claims conflict.

The schema inventories are generated from a pinned official ECMA-376 Transitional XSD archive.
They are discovery checklists, not implementation percentages: element counts do not correspond
one-to-one with user-facing capabilities.
