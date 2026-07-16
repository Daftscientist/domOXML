# Bidirectional Implementation Roadmap

This roadmap turns the architecture in [`architecture.md`](architecture.md) into incremental
work. PowerPoint is first. Each milestone must leave a working end-to-end pipeline and add
capability fixtures for every supported behavior.

## Principles

1. Keep HTML/CSS as the public web format and typed IR as the internal contract.
2. Implement narrow vertical slices in both directions before expanding breadth.
3. Preserve unsupported constructs explicitly; never silently drop them.
4. Separate fidelity from editability: pixels can match while native Office structure regresses.
5. Reuse external projects as references, benchmarks, and attributed donors only when their
   licenses and runtime boundaries fit the MIT library.

## Current Position

Phases 0-3 now have working end-to-end baselines. Phase 4 is active: the library has broad
forward and reverse primitives, 15 capability fixtures, and a nine-case visual corpus. The
remaining risk is proof depth rather than raw file count:

- the capability runner now executes both paths for six fixtures, but the remaining nine fixtures
  must gain reverse contracts before their behavior is bidirectional;
- the visual corpus is authored from isolated HTML examples rather than representative external
  PowerPoint decks;
- several useful families remain partial in one direction, especially themes, placeholders,
  groups, connectors, curved geometry, strokes, and advanced text behavior;
- unsupported constructs have preservation models, but external-deck tests must prove there are
  no silent drops across realistic packages.

Do not count a capability as bidirectional until the runner executes and asserts both directions.

## Phase 0: Make The Contract Executable

Before broadening conversion coverage:

- Finish `RenderResult.save()`.
- Add `HtmlPresentation`, `HtmlSlide`, asset, and preservation-metadata result types.
- Replace the single optional HTML string result with per-slide HTML plus shared CSS and assets.
- Add a `Presentation.from_pptx(...)` entry point and async variant.
- Define reader, writer, HTML serializer, and backend protocols.
- Add an executable README smoke test.
- Convert the PPTX coverage matrix into machine-readable capability fixtures.

Each fixture should declare:

```toml
id = "text-rich-runs"
direction = "both"
html = "fixtures/text-rich-runs.html"

[expected]
disposition = "native"
warnings = []
ir = "fixtures/text-rich-runs.ir.json"
html = "fixtures/text-rich-runs.reverse.html"

[[expected.xml]]
xpath = "//a:txBody/a:p/a:r"
count = 3

[visual]
source_to_pptx_min_similarity = 0.98
source_to_pptx_min_regional_similarity = 0.96
pptx_to_html_min_similarity = 0.98
pptx_to_html_min_regional_similarity = 0.96
```

## Phase 1: Repair The Shared Canvas IR

The current canvas IR proves generation but is too small for round trips. Add:

- paragraph and ordered text-run models;
- explicit node IDs, stacking order, groups, pictures, and raster-fallback nodes;
- resolved style values plus optional theme/source references;
- hyperlinks and basic list metadata;
- preservation metadata for unsupported OOXML fragments;
- typed coverage records with `native`, `partial`, `raster`, `preserved`, and `unsupported`.

Keep PPTX canvas IR separate from future DOCX flow IR. Share primitives, not layout assumptions.

## Phase 2: Stabilize HTML/CSS -> PPTX

Refactor the current forward path around the expanded canvas IR:

- capture nested inline text in document order;
- capture stacking context and effective z-order;
- centralize native-versus-raster decisions in resolvers;
- serialize the new IR to deterministic per-slide HTML/CSS;
- improve raster crop bounds so blur, shadow, and transformed overflow are not clipped;
- add XML assertions and regional visual assertions alongside whole-slide fidelity scores.

Exit condition: authored HTML can round trip through `HTML -> IR -> HTML`, and current editable
PPTX behavior remains green.

## Phase 3: PPTX -> HTML/CSS Baseline

Build a native Python reader with the same internal standards as the writer:

```text
OPC reader -> relationships -> PresentationML reader
           -> inheritance resolver -> canvas IR -> HTML/CSS serializer
```

Start with:

- package parts, relationships, slide order, and assets;
- slide dimensions;
- slide -> layout -> master -> theme resolution;
- shapes, transforms, stacking, solid fills, lines, and simple geometry;
- pictures;
- text bodies, paragraphs, runs, alignment, and basic inheritance;
- fallback rendering and preservation records for unsupported nodes.

Exit condition: a generated baseline deck and a representative external deck can complete:

```text
PPTX -> IR -> HTML/CSS -> Chromium render
```

with structural assertions and visual scoring.

## Phase 4: Coverage Expansion

Expand by capability family, not by file:

1. Rich text: decorations, spacing, bullets, numbering, hyperlinks, autofit.
2. Geometry: preset shapes, connectors, custom paths, groups, rotation.
3. Fills and effects: theme colors, pattern fills, crop modes, shadows, glow, blur.
4. Tables.
5. Charts and chart data.
6. Layouts, placeholders, notes, transitions, and animation metadata.
7. SmartArt, OLE, media, and unsupported-extension preservation.

Every forward feature must specify reverse behavior, and every reverse feature must specify
what happens when emitted HTML is compiled forward again.

## Coverage Acceleration Program

Speed comes from repeatable vertical slices and shared test infrastructure, not larger pull
requests. A capability slice is complete only when it includes:

1. Forward proof: HTML/CSS -> typed IR -> PPTX, with coverage disposition and OOXML assertions.
2. Reverse proof: PPTX -> typed IR -> deterministic HTML/CSS, with structural assertions.
3. Round-trip proof: the feature survives both `HTML -> PPTX -> HTML` and
   `PPTX -> HTML -> PPTX`, or has an explicit preserved/raster/unsupported contract.
4. Visual proof: source, LibreOffice, and regional diff evidence; Graph/PowerPoint evidence for
   renderer-sensitive behavior and release baselines.
5. Contract proof: capability manifest, coverage matrix, warnings, and preservation metadata all
   describe the same behavior.
6. Regression proof: focused unit tests plus the smallest useful integration fixture.

Keep feature PRs narrow enough to review independently. Shared enablers land first; capability
families can then progress independently without weakening the common gates.

### Ordered Delivery Lanes

1. **Make bidirectional claims executable (complete)**: the capability schema and runner now cover
   reverse inputs, HTML assertions, round-trip assertions, and global/regional visual gates.
2. **Establish a real-deck corpus**: sanitized Microsoft-authored and representative external
   decks covering masters, themes, placeholders, groups, media, and unsupported extensions.
3. **Close core editable asymmetries**: forward theme references/placeholders, group authoring,
   connector arrowheads, gradient strokes, and the highest-use curved preset geometry.
4. **Deepen text and layout**: autofit parameters, inherited paragraph fields, WordArt fallback,
   and multi-column edge cases.
5. **Deepen fills and effects**: remaining pattern presets, renderer-calibrated effects, and
   explicit native-versus-raster portability rules.
6. **Prove preservation**: animation, SmartArt, OLE, charts, 3D, and extension lists must survive
   ingest/re-emission or report a precise unsupported disposition without silent data loss.

### PPTX Readiness Gate

PPTX is ready for a stable release when:

- every core editable family has executable forward and reverse fixtures;
- the real-deck corpus has no crashes, unsafe output, or silent drops;
- package/relationship assertions and schema validation pass for generated decks;
- LibreOffice global and regional fidelity are merge-blocking;
- Graph/PowerPoint baselines pass for renderer-sensitive cases before release;
- partial, raster, preserved, and unsupported behavior is accurately surfaced to callers.

## Phase 5: DOCX Seams

Do not implement DOCX by positioning boxes scraped from Chromium. Add a flow IR and semantic
HTML adapters:

```text
HTML <-> flow IR <-> WordprocessingML
```

Reuse OPC, relationships, assets, fonts, themes, shared DrawingML primitives, charts, warnings,
coverage, fidelity infrastructure, and preservation metadata. Keep paragraphs, tables, sections,
pagination, headers, footers, fields, and tracked changes in the DOCX-specific model.

## Validation Stack

Use layered validation:

| Layer | Purpose |
|---|---|
| Unit tests | Pure parser, resolver, and XML-snippet behavior |
| Capability fixtures | Per-feature native/editable/preserved behavior in both directions |
| Package validation | OPC relationships, required parts, XML structure, Open XML validation |
| Browser fidelity | Emitted HTML/CSS renders as expected |
| LibreOffice fidelity | Fast approximate OOXML rendering gate |
| Graph or desktop PowerPoint | Real PowerPoint spot checks and regression baselines |
| External benchmark adapters | Compare behavior with independent implementations |

Whole-slide similarity remains useful but is not sufficient. Track regional metrics and
structural assertions so a small editable object cannot regress unnoticed.

## External Projects

External code should be evaluated feature-by-feature:

| Project | License | Use |
|---|---|---|
| [`pptx-renderer`](https://github.com/aiden0z/pptx-renderer) | Apache-2.0 | Primary reverse-reader architecture and fidelity-test reference |
| [`dom-to-pptx`](https://github.com/atharva9167j/dom-to-pptx) | MIT | Forward HTML algorithms and benchmark adapter |
| [`PptxGenJS`](https://github.com/gitbrent/PptxGenJS) | MIT | OOXML-generation reference and benchmark adapter |
| [`Presenton`](https://github.com/presenton/presenton) | Apache-2.0 | Product integration reference, HTML/Tailwind corpus, external runtime benchmark |
| [`presenton-export`](https://github.com/presenton/presenton-export) | release runtime | Benchmark only unless source and compatible licensing are available |
| [`office-website`](https://github.com/baotlake/office-website) | AGPL-3.0 | Isolated manual QA environment only |

When code is adapted from a compatible project, retain required notices, document the source
commit and file, mark modifications, and add tests proving the behavior. Do not copy AGPL code
into the MIT library. Do not treat opaque release binaries as implementation sources.

## Immediate Work Queue

1. [x] Add machine-readable capability fixture models and a minimal fixture runner.
2. [x] Expand text IR to paragraphs and ordered runs; fix nested inline text capture.
3. [x] Add deterministic `canvas IR -> HtmlPresentation` serialization.
4. [x] Add shared OPC reading primitives.
5. [x] Implement `Presentation.from_pptx(...)` for one baseline deck.
6. [x] Expand relationship, theme, shape, picture, and text readers incrementally.
7. [x] Make the capability fixture runner execute both declared directions.
8. [ ] Add representative external PPTX round-trip fixtures and preservation assertions.
9. [ ] Add package/schema validation for generated and re-emitted decks.
10. [ ] Run external adapters as comparative benchmarks, not runtime dependencies.
