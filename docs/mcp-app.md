# domOXML MCP App (spec v3)

Status: draft v3, 2026-11-07. v2 (after Claude + Codex review) reshaped by the user: three tool layers (file /
HTML-CSS / per-kind), strong typing everywhere, the engine running in the MCP App view, screenshots on demand, the
person's edits and comments reaching the model as soon as it acts, and normalized HTML always returned. The v2 review
triage still applies (end of file); v3 needs its own review round before building.

## 1. What it is
You and the model work on the same file inside any MCP host with MCP Apps (Claude, ChatGPT, VS Code, Goose…). The view
shows the file and lets you edit, comment and present; the model works through typed tools; both see each other's
changes. Presentations first; documents and workbooks later use the same file and HTML layers.

## 2. Architecture: the engine lives in the view
- **The view is the engine.** It runs domOXML in the browser (Pyodide in a worker, as Ream does), lays out HTML with the
  host's browser, captures and compiles it, renders slides, takes screenshots (SVG `foreignObject` → canvas), checks,
  and builds `.pptx` files. All computation happens there.
- **The server is thin**: file I/O (opening from allowed folders/URLs, saving back), durable storage of working copies
  and history (the view uploads each committed revision; the server persists it before acknowledging), and a relay:
  a model tool call is queued, the live view picks it up (long-poll), computes, and posts the result back through an
  app-only tool, and the server returns it to the model.
- **A live view is required.** Model tools that need the engine return `VIEW_REQUIRED` with what to do ("call
  `file_show`") when no view is attached. Optional fallback, decided after the spike: a server-side engine (local Python
  domOXML + Playwright) for hosts where the view's engine can't start.
- **Day-one spike (go/no-go for this architecture)**: on Claude Desktop, claude.ai, ChatGPT and VS Code, does the view's
  sandbox allow WebAssembly compilation (the MCP Apps reference CSP has no `wasm-unsafe-eval`), workers (`worker-src`
  falls back to `script-src`), loading the engine (from `resourceDomains`, ~13 MB today; the startup-speed work matters
  even more now), nested frames for capture (`frame-src 'none'` unless declared; capture can move to a shadow root),
  storage, and long-poll timing while the view is visible or scrolled away? Results become the host capability matrix.

## 3. Ground rules
- **HTML/CSS is the authoring language, any layout.** Every surface is compiled at its fixed size into domOXML's canvas
  objects; what's stored is the compiled form plus the author's HTML as provenance.
- **Normalized HTML always comes back.** Every read returns normalized HTML (domOXML's canonical form, payloads
  stripped, stable ids); every write returns the normalized HTML of what it changed, plus a **compile report**: what was
  transformed (e.g. "flex row → 4 absolutely positioned boxes", "font 'Inter Display' → 'Inter'", "box-shadow
  approximated", "backdrop blur → picture in PowerPoint"). The model may author freely and always learns exactly how its
  HTML exists after processing, so its next edit starts from the truth.
- **The person comes first.** Every model tool result begins with `since_your_last_call`: the person's edits and new
  comments since the model last acted (typed list, capped, `+N more`). Writes are checked per element against those
  changes: touching an element the person changed since the model read it returns `CONFLICT` with that element's current
  normalized HTML, never a silent overwrite. Comments are first-class (threads on a surface or element) and the model
  can read, reply to and resolve them.
- **We don't store people's files**: files open where they live; working copies and history persist locally (server)
  so nothing is lost on restart; saving back is explicit.
- **Inert content, bounded input, honest privacy** (as v2: strict HTML profile, no network from slides, limits on
  imports; tool results go to the person's AI provider).

## 4. Types (one registry, strongly typed)
- One Pydantic registry is the single source: it generates every tool's input JSON Schema **and `outputSchema`**
  (results are typed `structuredContent`, with a short text summary in `content`), the TypeScript types used by the view
  and by Ream, and the API reference (as the earlier office plugin did).
- **Enums for every closed set**: `FileKind` (presentation; later document, workbook), `Detail`, `InsertPosition`
  (before/after/prepend/append), `ZMove` (front/back/forward/backward), `Align`/`Distribute`, `TransitionEffect` (+
  `TransitionDirection`), `AnimationEffect`, `AnimationTrigger`, `AnimationCategory` (entrance/emphasis/exit/path),
  `SlideSizePreset`, `Unit` (px/pt/in/cm/emu), `ExportFormat`, `FindingCode`, `Fidelity`
  (native/approximated/raster/dropped), `ChangeKind`, `Actor` (person/model), `ErrorCode` (VIEW_REQUIRED, CONFLICT,
  NOT_FOUND, INVALID_HTML, LIMIT_EXCEEDED, UNSUPPORTED…).
- **Tagged unions with `type`** for every choice: `FileSource` (path/url/upload/file), `ElementRef` (id/name/selector),
  `SurfaceRef` (id/number/batch_ref), `AssetSource` (path/url/data).
- **Prefixed ids with patterns**: `fl_` file, `sf_` surface (slide/page), `el_` element, `tx_` transaction, `as_` asset,
  `cm_` comment, `rv_` revision, `vw_` view.
- **Typed styles**: `set_style` takes a `Style` object (`fill`, `color`, `font_family`, `font_size` {value, unit},
  `font_weight` enum, `italic`, `underline`, `text_align` enum, `vertical_align` enum, `line_height`, `letter_spacing`,
  `border` {width, style enum, color}, `radius`, `shadow`, `opacity`, `rotate`, `padding`…), with raw `css` declarations
  as a checked escape hatch (each value gets a `Fidelity`).
- Every write carries `request_id` (idempotent retries) and an `activity` label (≤ 4 words, shown in the view).
- Resource templates (`office://files/{file}/…`) and completions for every id argument.

## 5. Tools
### Layer 1: `file_*` (any kind)
| Tool | Does |
|---|---|
| `file_find` | Search allowed folders, working copies and recent files by name and text |
| `file_list` | Working copies with live-view status |
| `file_open` | Import from a `FileSource` into a working copy (shows a view) |
| `file_create` | New file of a `FileKind` (shows a view) |
| `file_show` | A fresh view of an open file (attaches the engine) |
| `file_look` | **Screenshots** of chosen surfaces or one element, at a chosen width; optional before/after vs a revision |
| `file_check` | Findings (`FindingCode`): overflow, overlap, off-canvas, contrast, fidelity (what becomes a picture), missing fonts, accessibility (alt text, reading order) |
| `file_changes` | The person's edits and comments since a revision (full list; results carry the short version) |
| `file_history` / `file_undo` / `file_restore` | Read-only history; selective undo of one transaction; destructive whole-file restore |
| `file_export` | `ExportFormat` (pptx, pdf, png, html); save back, save as, or download in the view |
| `file_close` | Release the engine; the working copy stays |

### Layer 2: `html_*` (any surface authored in HTML: slides now, pages later)
| Tool | Does |
|---|---|
| `html_read` | Normalized HTML of a surface or elements; or an element outline (id, role, text, box, key style); or resolved CSS |
| `html_find` | Elements by text, role, selector or region |
| `html_write` | Replace a surface's HTML (any layout); reconciled per element; returns normalized HTML + compile report |
| `html_patch` | Batch of typed ops: `set_style`, `set_text` (keeps runs), `set_attrs`, `insert` (`InsertPosition`), `replace`, `remove`, `move` (box with units), `reorder` (`ZMove`), `group`/`ungroup`, `align`/`distribute`, `link` (hyperlink), `alt_text`, `find_replace`; returns normalized HTML of changes + compile report |
| `html_table` | Table structure: add/remove/move rows and columns, merge/split cells, cell styles, banding |
| `html_chart` | Chart data and type: categories, series, type enum, axes, legend, labels (exports as a native chart) |
| `html_asset` | Add (from `AssetSource`), list, replace, remove pictures and fonts |
| `html_measure` | Browser-resolved boxes and computed styles |

### Layer 3: `presentation_*` (only what's unique to decks)
| Tool | Does |
|---|---|
| `presentation_slides` | Add (blank, from layout, from HTML), duplicate, move, delete, hide/show slides |
| `presentation_notes` | Read and write speaker notes |
| `presentation_transition` | `TransitionEffect`, direction, duration (ms), advance on click / after time; per slide or all |
| `presentation_animate` | Animations on elements: effect, category, trigger, delay, duration, order; list and remove |
| `presentation_theme` | Deck colours, fonts, background; slide size (preset or custom with units) |
| `presentation_layouts` | Masters, layouts and placeholders: list, apply, edit |
| `presentation_sections` | Named sections: add, rename, move, delete |
| `presentation_comments` | Comment threads on slides or elements: read, add, reply, resolve (shared with the person in the view) |
| `presentation_present` | Start presenting in the view from a slide (the person drives) |

Later: `document_*` (sections, headers/footers, styles, page setup) and `workbook_*` (sheets, ranges, formulas, charts),
reusing layers 1 and 2.

## 6. The view
The editor and the engine: rail + slide (fullscreen when the host allows; inline shows one slide with a filmstrip);
select, move, resize, type, restyle with the same typed ops; comments; present; download. Shows the model's activity
("Making slide 4"), highlights what it changed, and sends the person's edits and comments to the server as they happen
(so `since_your_last_call` is always current). `updateModelContext` carries only what's on screen (current slide,
selection) as a cumulative snapshot.

## 7. Evals and phases
Evals as v2 (40 tasks, 30% held out, scripted person editing during runs, verifiers on the IR, Ream's tools as baseline),
plus checks that the model uses returned normalized HTML and compile reports correctly.
1. **Spike**: the host capability matrix (§2). Go/no-go for the engine-in-view architecture, or the server-engine
   fallback.
2. **Shared engine work in domOXML** (reconciliation, stable ids, payload projection, compile report, inert profile) with
   Ream as the first client.
3. **The registry, the server, the view with the engine**, layers 1–3 for presentations, evals.
4. Hosted transport; Rust for what measures slow; documents and workbooks.

## 8. Open questions for the user
1. Where it lives: `mcp/` in the domOXML repo, or the `agent-plugins` repo next to the earlier office plugin?
2. If a host blocks the engine in the view: fall back to a local server engine (Python + Playwright), or simply not
   support that host?

## Review triage (v1 → v2, still applies)
Accepted from both reviewers: compile boundary; stable ids at every depth; payloads hidden and invalidated (fixes a real
silent-revert of edited imported text); reconciliation as shared engine code; transactions with request ids,
auto-rebase, per-element conflicts, persisted before ack; selective undo and a separate destructive restore; typed small
ops; bounded reads; source contract and downloads by capability; durable working copies; document vs view identity;
"since your last call" in results; polling committed state; inert HTML profile; limits; honest privacy; concrete evals;
Ream as first client.
