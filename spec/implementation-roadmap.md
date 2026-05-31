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
pptx_to_html_min_similarity = 0.98
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
6. [ ] Expand relationship, theme, shape, picture, and text readers incrementally.
7. Run external adapters as comparative benchmarks, not runtime dependencies.
