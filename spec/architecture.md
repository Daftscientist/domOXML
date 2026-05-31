# domOXML Architecture

domOXML converts between web authoring formats and editable Office Open XML:

```text
HTML/CSS -> typed IR -> OOXML
OOXML    -> typed IR -> HTML/CSS
```

PowerPoint (`.pptx`) is the first format. Word (`.docx`) follows the same overall
conversion model with a flow-oriented document IR. Excel (`.xlsx`) shares the OOXML
infrastructure but uses a grid/data model rather than HTML layout as its primary model.

## HTML/CSS Is The Public Web Format

Callers author each slide as an HTML fragment. A presentation can apply shared CSS, and
fragments can also contain inline styles. The forward path accepts ordinary browser-rendered
HTML/CSS rather than a restricted template language.

The reverse path emits ordinary HTML/CSS that a browser can render and a caller can edit.
For slides, the emitted HTML is per-slide and may be accompanied by shared CSS and deck-level
metadata. For documents, emitted HTML should use semantic flow elements such as paragraphs,
headings, lists, and tables rather than absolute-positioned boxes.

The library may normalize emitted HTML to make output stable and easy to process. In this
context, normalization means deterministic serialization: equivalent resolved input produces
stable element ordering, styles, units, and metadata. It does **not** mean callers must author
HTML in a proprietary domOXML dialect.

## Fidelity And Preservation

HTML/CSS and OOXML overlap substantially, but neither can losslessly express every feature of
the other:

- Arbitrary HTML/CSS can always be rendered, but some effects must remain layered raster
  fallbacks rather than editable native Office objects.
- Arbitrary OOXML can always be ingested, but some Office-specific behavior has no plain
  HTML/CSS equivalent.

The library therefore has two responsibilities:

1. Emit the best editable native representation available.
2. Preserve unsupported constructs explicitly rather than silently dropping them.

Reverse HTML may include narrowly scoped `data-domoxml-*` metadata and deck-level metadata
for Office concepts that CSS cannot represent faithfully. The visible HTML/CSS remains usable
without that metadata. Raster fallbacks remain layered and carry a reason in the coverage
report.

Round-trip fidelity means preserving appearance and editability where a native mapping exists,
while retaining unsupported source information where practical. It does not mean pretending
that every Office feature is a CSS feature.

## IR Families

There is no single universal layout IR. The typed internal models share primitives but retain
format-appropriate structure:

| IR family | Used by | Layout model |
|---|---|---|
| Canvas IR | PowerPoint | fixed-size slides, positioned objects, stacking order |
| Flow IR | Word | sections, paragraphs, runs, lists, tables, pagination hints |
| Grid/data IR | Excel | sheets, cells, formulas, tables, charts |

Shared primitives include colors, fills, strokes, effects, images, fonts, relationships,
themes, DrawingML geometry, charts, units, warnings, coverage records, and preservation
metadata.

## Adapter Boundaries

Each direction is an adapter around a typed IR:

```text
HTML/CSS --Chromium capture--> canvas IR --PresentationML writer--> PPTX
PPTX --OPC + PresentationML reader--> canvas IR --HTML writer--> HTML/CSS

HTML --semantic parser--> flow IR --WordprocessingML writer--> DOCX
DOCX --OPC + WordprocessingML reader--> flow IR --HTML writer--> HTML/CSS
```

The PowerPoint reverse reader must resolve relationships and effective values across slide,
layout, master, and theme parts. The HTML writer serializes resolved appearance while retaining
the metadata needed to preserve Office-specific constructs across a later round trip.

## Capability Contract

Coverage is measured in both directions. Each capability fixture should declare:

- expected native, partial, raster, preserved, or unsupported disposition;
- expected warnings;
- expected IR and relevant OOXML structure;
- expected emitted HTML/CSS and preservation metadata;
- visual fidelity thresholds for forward and reverse round trips.

The schema inventories describe the possible OOXML surface. The capability fixtures describe
the supported conversion behavior.

See [`implementation-roadmap.md`](implementation-roadmap.md) for the incremental build order.
