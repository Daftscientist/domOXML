# domOXML Implementation Roadmap

This roadmap turns the invariants in [`architecture.md`](architecture.md) into a parity-first
delivery programme. PowerPoint is the first complete format. Work is ordered so every milestone
leaves the library usable: native coverage expands behind a layered fallback instead of exposing
new unsupported visual states.

## Current Baseline

Snapshot audited on **2026-07-18** against the repository, executable manifests, and tests:

- HTML/CSS can produce PPTX, PNG, and normalized per-slide HTML.
- PPTX can be ingested into Canvas IR and emitted as normalized HTML/CSS.
- 729 tests are collected.
- 21 atomic PPTX capability fixtures exist; 20 are bidirectional and one is a reverse-first chart
  preservation fixture.
- 9 authored HTML fidelity cases exist.
- 5 pinned external PPTX cases cover tables, image crop, embedded-font diagnostics, attached
  chart-graph re-emission, and ellipse soft-edge radii with PPTX and normalized-HTML visual gates.
- LibreOffice global, regional, focused, and structural scores are merge-blocking for configured
  cases.
- Microsoft Graph rendering exists as an opt-in backend, not a normal CI gate.

The baseline is useful but not yet the product invariant:

- Canvas IR uses one canonical ordered node sequence with compatibility views for legacy callers;
- adopted nodes have slide-scoped stable IDs and active HTML/PPTX adapters retain typed source
  provenance; chart payloads are attached and re-emitted, while exact group reconstruction and
  general preservation ownership remain incomplete;
- forward raster fallback exists, but its granularity and semantic debt are not comprehensively
  asserted;
- positioned reverse PPTX visuals can own caller-supplied renderer crops; capturable OPC graphs
  remain attached, while malformed graphs retain the visual as a stable picture layer and report
  detached-source debt. The chart fixture proves the attached path; unpositioned nodes, missing
  renders, and preservation families without owned graphs remain nonvisual/detached debt;
- detached preserved fragments are not generally re-emitted by `render_html_roundtrip()`; charts
  use an owned node payload, retain their dependency graph and ambient theme, display an element
  layer when a source render is supplied, and recover both through normalized HTML;
- complex/adversarial HTML and real-PPTX corpora remain small;
- HTML capture and PPTX ingest both emit typed per-visual representation, editability, source
  retention, output-count, and raster-area records. All 21 atomic fixtures and 5 real decks pin
  exact initial reverse-ingest bounds; broader unknown and adversarial families still need corpus
  coverage;
- generated and re-emitted PPTX output is blocked on shared OPC and core PresentationML structural
  validation; full ECMA/Open XML XSD, Strict-package, AlternateContent, and extension-schema
  validation are not yet enforced.

## Completion Contract

A capability is complete only when all applicable gates pass:

1. HTML/CSS imports into the canonical IR.
2. PPTX imports into the same IR representation.
3. IR exports to native/decomposed/hybrid/layered PPTX with no visible omission.
4. IR exports to deterministic browser-renderable HTML/CSS with no visible omission.
5. Semantic and object editability are measured independently of pixels.
6. Package structure and target-format semantics are asserted.
7. Forward and reverse visual floors include global, regional, focused, and structural metrics
   where the applicable corpus contract exposes them.
8. Evidence is inspected directly when the capability changes.
9. Repeated round trips converge within the declared tolerance.
10. Unknown, malformed, extension, and adversarial combinations have explicit behavior.

No capability is labelled bidirectional merely because both code paths return successfully.

## Milestone 0: Make The Contract Accurate

**Status: implemented for the active HTML and PPTX adapters, capability registry, and current
atomic/real-deck corpus.**

- Keep architecture, roadmap, and inventories authoritative and nonduplicated.
- Generate schema appendices from pinned official ECMA-376 XSDs.
- Replace element-name coverage percentages with capability-level evidence.
- Replace `unsupported` as a visual disposition with representation and scope policies.
- Add representation statuses: native, decomposed, hybrid, layered, element-layer, preserved, and
  intentionally ignored.
- Record semantic editability, visual parity, preservation, and verification as separate fields.
- Make inventory rows point to executable capability IDs as coverage grows.

**Exit gate:** runtime status and documentation cannot claim more coverage than executable evidence.

## Milestone 1: Canonical Canvas IR

This is the highest-leverage engineering change because all directions currently meet here.

- Keep every top-level visual in the canonical ordered `SlideIR.contents` sequence. (Implemented.)
- Add stable node IDs and source ownership/provenance. (Implemented for adopted nodes and active
  HTML/PPTX visual adapters; group reconstruction remains pending.)
- Preserve group and stacking relationships rather than flattening by default.
- Attach source extensions and preservation payloads to their owning node/part. (Implemented for
  chart graphic frames and their transitive OPC dependencies; other preserved families remain.)
- Model native, decomposed, hybrid, and layer relationships explicitly.
- Separate semantic/style intent from resolved paint/layout data where both are available.
- Centralize normalization so HTML and PPTX adapters do not invent different canonical forms.
- Make warnings and capability records describe each lowering decision.

**Exit gate:** mixed shapes, tables, groups, connectors, media, and fallback layers preserve exact
z-order through both round-trip sequences.

## Milestone 2: Universal Parity Fallback

The fallback closes visual gaps while native mappings are developed.

- Build a representation planner that selects native, decomposed, hybrid, or layered output.
- Capture paint bounds including filters, shadows, transformed overflow, masks, and clips.
- Split semantic content from difficult decoration where that produces a smaller raster layer.
- Preserve independently movable layers, original stacking, group ownership, and alpha.
- Define deterministic fallback behavior for SVG, canvas, pseudo-elements, blend modes, filters,
  complex clipping, browser-specific CSS, and unsupported PowerPoint visuals.
- Give PPTX reverse ingest a renderer-backed layer path for unknown visual nodes.
- Re-emit attached source payloads when targeting the source format.
- Add coverage gates that reject coarser rasterization or increased layer area without an explicit
  reviewed reason.

**Exit gate:** every corpus visual is present in HTML and PPTX even when semantic/native coverage is
incomplete; repeated conversion does not repeatedly rasterize or duplicate the same content.

## Milestone 3: Finish Shared Primitives Needed By PPTX

Work by vertical capability family, implementing both adapters and every active serializer.

1. **Geometry and ordering**: full preset geometry, SVG paths including arcs and shorthand,
   formula-driven custom geometry, connection sites, connectors, group authoring, clips, and exact
   transforms.
2. **Paint**: complete theme/style-matrix references, every DrawingML color transform, gradient
   variants, image tile/stretch/crop modes, pattern presets, gradient strokes, compound lines,
   arrowheads, caps, joins, and per-side rounded borders.
3. **Effects**: renderer-calibrated outer/inner shadow, glow, blur, soft edge, reflection, preset
   shadow, fill overlay, effect containers, and effect ordering.
4. **Text**: inherited run/paragraph properties, bullet fonts/colors/sizes, numbering variants,
   tabs, baseline/superscript/subscript, language/script fonts, RTL/vertical text, autofit
   parameters, overflow, columns, text warp/WordArt, and measurement parity.
5. **Tables and charts**: full cell/table styling and inheritance, borders/merges, chart model,
   chart data/workbook links, labels, axes, legends, and chart style/color parts.
6. **Assets and media**: SVG vector re-emission, image effects, linked assets, audio/video authoring,
   posters, playback metadata, and font portability.
7. **Packaging and preservation**: deterministic relationship allocation, content types, extension
   lists, alternate content, strict/transitional handling, and schema validation.

**Exit gate:** each shared family has bidirectional capability fixtures, adversarial combinations,
and at least one representative real-deck case where applicable.

## Milestone 4: Finish PresentationML

- Author and ingest themes without prematurely flattening theme references.
- Author slide masters, layouts, placeholders, and inheritance chains.
- Preserve and round-trip slide-level ordering, IDs, sections, and useful deck metadata.
- Add speaker notes as a first-class slide property and public API argument.
- Complete transitions and define animation/timing input beyond visual CSS state.
- Map or layer SmartArt, OLE, embedded objects, and presentation-specific graphic frames.
- Support audio/video insertion and playback settings.
- Define accessibility metadata, hyperlinks, slide jumps, and alternative text.
- Explicitly ignore comments/review history unless product scope changes.
- Handle Microsoft extensions, alternate content, malformed-but-accepted relationships, and
  nonstandard producer output.

**Exit gate:** the PPTX inventory has no unclassified visible family; nonvisual families are mapped,
preserved/re-emitted, or intentionally ignored by policy.

## Milestone 5: Convergence And Release Corpus

- Grow atomic fixtures from 16 to one executable case per meaningful capability family.
- Add pairwise and adversarial combinations rather than relying on isolated examples.
- Add complex authored HTML decks with nested stacking, effects, SVG/canvas, web fonts, and
  nonstandard CSS.
- Add representative Microsoft-authored PPTX decks covering masters, layouts, placeholders,
  groups, charts, media, notes, animation, SmartArt, OLE, extensions, and accessibility.
- Add malformed-but-tolerated and nonstandard-producer decks.
- Run repeated conversion sequences, not only one round trip.
- Track native/decomposed/hybrid/layer area and semantic retention as monotonic metrics.
- Store per-object/region evidence so a high whole-slide score cannot hide a broken table or text
  block.
- Require Graph or desktop PowerPoint baselines for renderer-sensitive release cases.
- Require human/vision review of changed reference pairs in conversion PRs.

**PPTX stable-release gate:**

- no crashes, unsafe packages, silent visual omissions, or detached preservation loss in the
  release corpus;
- every in-scope visual uses native, decomposed, hybrid, or layered output in both directions;
- repeated round trips meet convergence thresholds;
- package, relationship, schema, and source-extension assertions pass;
- configured Chromium, LibreOffice, and PowerPoint evidence passes;
- no visual, semantic, native-coverage, or fallback-granularity regression from the baseline.

## Milestone 6: DOCX

Begin only after shared primitives and the representation planner are stable enough to reuse.

```text
semantic HTML <-> Flow IR <-> WordprocessingML
```

Reuse OPC, relationships, assets, themes, fonts, DrawingML, charts, warnings, preservation,
normalized HTML, fidelity infrastructure, and the fallback planner. Add DOCX-specific sections,
styles, lists, tables, headers/footers, fields, footnotes/endnotes, pagination, tracked revisions,
and compatibility settings.

DOCX is expected to reuse substantial work, but flowing pagination and Word style inheritance are
independent hard problems and must not be treated as trivial Canvas IR variants.

## Milestone 7: XLSX And Additional Adapters

Use a Grid/data IR for workbook semantics while reusing shared text, style, drawing, chart, media,
package, and fidelity infrastructure. Evaluate PDF, additional image formats, normalized HTML
profiles, and other import/export adapters according to demand after PPTX stability.

## Continuous CI Ratchets

Every conversion PR should add or update the smallest representative examples and include direct
source/target evidence. CI should enforce:

| Gate | Required behavior |
|---|---|
| Unit | parsers, resolvers, lowerers, and serializers pass |
| Capability | forward, reverse, structural, semantic, and visual contracts pass |
| Authored corpus | no score or layer-granularity regression |
| Real decks | valid relationships, preservation, and renderer floors pass |
| Convergence | repeated round-trip drift stays within the fixture contract |
| PR evidence | changed HTML and PPTX examples are embedded and directly reviewable |

Incomplete complex fixtures should remain committed with an explicit baseline and failure
classification. Improvement moves the baseline forward; CI must never normalize a regression by
silently lowering the expected score.

## Immediate Work Queue

1. [x] Replace `Disposition.UNSUPPORTED` and the coarse coverage report with the representation
   contract.
2. [x] Add stable node IDs and provenance; the ordered `SlideIR.contents` sequence is implemented.
3. [x] Attach preserved source payloads and prove real re-emission for the chart case; expand the
   same contract to remaining preserved visual families under items 5 and 7.
4. [x] Make every forward-authored atomic capability fixture genuinely bidirectional. SVG vector
   pictures retain their original asset and `asvg:svgBlip` extension through the full loop;
   custom paths retain solid SVG fill/stroke and exact connector IR; effects and text-body semantics
   use versioned typed normalized-HTML payloads and converge exactly across the tested PPTX loop.
5. [ ] Add reverse visual layers for unknown PPTX nodes instead of HTML omission plus detached XML.
   The renderer-backed contract, EMU-accurate crop, HTML asset, attached source recovery, and
   slide-scoped visual gate are implemented for positioned owned nodes and proven on the external
   chart. Automatic renderer policy and coverage of SmartArt, OLE, 3D, groups, and malformed nodes
   remain before this item is complete.
6. [x] Add package/schema validation for generated and re-emitted decks. The package builder and
   capability/real-deck gates now enforce content types, relationship ownership/IDs/targets,
   namespaced relationship references, XML parseability, and the core presentation -> slide ->
   layout -> master -> theme structure. Full ECMA XSD and Strict/extension schemas remain under
   items 7 and 10 rather than being implied by this structural gate.
7. [ ] Add groups, media, masters/layouts/placeholders, notes, and extensions to the real-deck
   corpus.
8. [ ] Expand effects beyond the bidirectional offset-shadow/inset-layer/glow baseline using
   PowerPoint/Graph-calibrated evidence for blur, soft edge, reflection, preset shadow, fill overlay,
   compound ordering, and effect-bearing custom geometry. CSS blur and the conservative
   `below <px> linear-gradient(...)` reflection subset, and strict two-axis intersecting soft-edge
   mask now have bidirectional atomic fixtures. PowerPoint retains native `a:blur`, `a:reflection`,
   or `a:softEdge` beneath an isolated layer; LibreOffice selects the same fallback alone; both
   branches recover into one hybrid IR node; and two-cycle convergence is exact. Native reflection
   blur uses an owned mirrored CSS layer and transform-aware isolated bounds on reverse output.
   Soft-edge mask sizing, position, repeat, origin, clip, and mode are admitted only at their exact
   default geometry; other masks take the visible element-layer path. Normalized ellipses use a
   geometry-aware radial feather, proven against an external OfficeCLI deck whose exact zero/8pt/
   20pt radii survive re-emission; its baseline also records the separate ellipse internal-text-
   rectangle debt. Reflection directions other than `below`, non-pixel gaps, preset shadow, fill
   overlay, compound ordering, and effect-bearing custom geometry remain open.
9. [x] Add capability-registry fields for semantic editability, representation level, layer area,
   source preservation, output count, and repeated-round-trip count. Every reverse-capable atomic
   fixture now rebuilds and re-ingests at least twice, validates each package and quality boundary,
   and applies global/regional/structural convergence floors. The initial PPTX-ingest boundary now
   emits first-class per-visual coverage and every atomic fixture plus real-deck case pins exact
   representation, editability, retention, output-count, and raster-area bounds.
10. [ ] Add strict OOXML and malformed/nonstandard producer cases after Transitional package
    preservation is reliable.
