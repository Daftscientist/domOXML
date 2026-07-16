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

The Canvas IR should contain one ordered node sequence. Every node needs a stable ID, source
provenance, geometry, transform, stacking/group ownership, semantic representation, resolved
appearance, preservation payloads, and representation status. Separate `shapes` and `nodes`
collections are a temporary implementation detail because they cannot represent interleaved
z-order reliably.

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
| Hybrid | semantic/native content plus rasterized effect or decoration layers | core content editable; visual layers movable |
| Layered | the smallest practical independent raster layers reproduce the source | layers independently movable and replaceable |
| Element layer | one rasterized source subtree when finer separation is not reliable | element movable as one object |

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
recover the richer IR.

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

Preservation is not visual support. A preserved chart XML fragment that disappears from HTML is
still a visual parity gap. Preservation must also be attached to the owning IR node or package
location so it can actually be re-emitted; storing detached fragments in a result object is only
an intermediate safeguard.

## Fidelity And Regression System

Fidelity is a multidimensional contract, not one whole-slide similarity number:

- global pixels and color distribution;
- worst-region similarity so small objects cannot disappear unnoticed;
- structural edges, geometry, text boxes, and stacking;
- semantic/native editability and fallback granularity;
- package validity, relationships, and source-extension preservation;
- stability over repeated conversions;
- direct visual review of changed evidence.

Reference conditions must pin viewport, fonts, asset state, DPI, renderer version, and target
platform. Chromium is the HTML reference renderer. LibreOffice supplies a fast CI signal but is
not a substitute for PowerPoint. Microsoft Graph or desktop PowerPoint baselines cover
renderer-sensitive behavior and release gates.

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
