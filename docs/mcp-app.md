# domOXML MCP App (spec v4)

Status: draft v4, 2026-11-07. Decided by the user: lives in this repo (`mcp/`); a hosted MCP with OAuth plus an optional
local mode; no files stored on the server; the HTML tools are plain, standard HTML/DOM editing; files open straight
into the view (inline or full panel) and save as .pptx or .html; the model always knows the person's state without
bloat; the view looks native in whatever client it runs in. Earlier (v3), reshaped by the user: three tool layers (file /
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
- **The server stores no files, ever.** Hosted (OAuth) or local, it only relays: a model tool call is queued in memory
  for the person's live view (routed by the MCP session, so a call only ever reaches its own person's view), the view
  computes, and the result goes back. File contents pass through in transit and are never written down.
- **Files live in the host's runtime**: the person opens one by picking or dropping it into the view, from a URL, or
  (local mode only) by path; the working copy and its history live in the view's browser storage (a dedicated view
  origin, where the host supports one, keeps it across conversations); saving downloads `.pptx` or `.html` through the
  host (`ui/download-file`), or writes back to the path in local mode. The relay:
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
- **No server storage**: files open from the host's runtime and save back to it (§2).

## 3a. The person's state, without bloat
Every model tool result carries a typed `you_are_here` header with **only what changed since the model last saw it**
(the server keeps a hash of the last state it sent per caller):
`surface` (id + number), `selection` (up to 8 element ids with short labels, then a count), `caret` (element, offset and
~20 characters around it, when typing), `viewport` (zoom and the visible region in surface coordinates), `mode`
(edit / present / comment / idle), `open_panel`, plus `since_your_last_call` (edits and comments, capped). Unchanged
state costs nothing; `file_state` returns everything. Between turns the view also sends the same compact state through
`updateModelContext`, so a new message from the person already carries where they are.
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
- **The HTML layer is plain HTML/DOM, not opinionated**: operations mirror the DOM (`insertAdjacentHTML` positions
  `beforebegin`/`afterbegin`/`beforeend`/`afterend`, `setAttribute`, `removeAttribute`, `style.setProperty`, `textContent`,
  `replaceWith`, `remove`, move to a parent at an index), elements are addressed by id or CSS selector, styles are
  standard CSS property names and values (validated by a CSS parser). Nothing presentation-specific lives in this layer;
  each write still reports each CSS value's `Fidelity` for the target format.
- Every write carries `request_id` (idempotent retries) and an `activity` label (≤ 4 words, shown in the view).
- Resource templates (`office://files/{file}/…`) and completions for every id argument.

## 5. Tools
### Layer 1: `file_*` (any kind)
| Tool | Does |
|---|---|
| `file_find` | Search allowed folders, working copies and recent files by name and text |
| `file_list` | Working copies with live-view status |
| `file_open` | Open a file from a `FileSource` straight into the view (inline, or the full panel when the host allows) |
| `file_create` | New file of a `FileKind` (shows a view) |
| `file_show` | A fresh view of an open file (attaches the engine) |
| `file_look` | **Screenshots** of chosen surfaces or one element, at a chosen width; optional before/after vs a revision |
| `file_check` | Findings (`FindingCode`): overflow, overlap, off-canvas, contrast, fidelity (what becomes a picture), missing fonts, accessibility (alt text, reading order) |
| `file_changes` | The person's edits and comments since a revision (full list; results carry the short version) |
| `file_state` | The person's full current state (§3a) when the compact header isn't enough |
| `file_history` / `file_undo` / `file_restore` | Read-only history; selective undo of one transaction; destructive whole-file restore |
| `file_save` | Save as `.pptx` or `.html` (later pdf/png): download through the host, or write back to the path (local mode) |
| `file_close` | Release the engine; the working copy stays |

### Layer 2: `html_*` (any surface authored in HTML: slides now, pages later)
| Tool | Does |
|---|---|
| `html_read` | Normalized HTML of a surface or elements; or an element outline (id, role, text, box, key style); or resolved CSS |
| `html_find` | Elements by text, role, selector or region |
| `html_write` | Replace a surface's HTML (any layout); reconciled per element; returns normalized HTML + compile report |
| `html_patch` | Batch of DOM-standard ops: `insert_html` (position enum as in `insertAdjacentHTML`), `replace_with`, `remove`, `move` (to parent, index), `set_attribute` / `remove_attribute`, `set_style` / `remove_style` (standard CSS properties), `set_text`, `find_replace`; returns normalized HTML of changes + compile report |
| `html_asset` | Add (from `AssetSource`), list, replace, remove pictures and fonts (referenced by standard `src`/`url()`) |
| `html_measure` | Browser-resolved boxes and computed styles |

### Layer 3: `presentation_*` (only what's unique to decks)
| Tool | Does |
|---|---|
| `presentation_slides` | Add (blank, from layout, from HTML), duplicate, move, delete, hide/show slides |
| `presentation_arrange` | Stacking order (`ZMove`), group/ungroup, align/distribute (enums), on slide objects |
| `presentation_table` | Office table structure: rows, columns, merge/split, table styles and banding |
| `presentation_chart` | Native chart data and type (categories, series, type enum, axes, legend, labels) |
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

## 6. The view (UI and theming)
**Feels native in every client.** All chrome is styled from the host's own theme: `theme` (light/dark), the standard
MCP Apps CSS variables (`--color-background-*`, `--color-text-*`, `--color-border-*`, `--color-ring-*`, `--font-sans`,
type sizes, `--border-radius-*`, `--shadow-*`) and the host's font CSS, each with our fallback. So the same view looks
like Claude in Claude and like VS Code in VS Code. Slides themselves keep their own document colours (they're the
document, not chrome). It respects `platform`, `deviceCapabilities` (touch/hover sizes), `safeAreaInsets`,
`containerDimensions` and `locale`, and follows `onhostcontextchanged` live.

**Layouts by display mode**
- *Inline* (in the conversation, ~600–700px wide): the current slide large, a filmstrip under it, a slim toolbar
  (open/save, present, fullscreen), and selection + text editing directly on the slide; activity line when the model is
  working ("Making slide 4"), changed objects highlight briefly.
- *Full panel* (fullscreen, when the host offers it): slide rail, canvas, a contextual bar above the slide (as Ream's
  editor: acts on the selection), comments panel, notes drawer, present.
- *PiP* (where offered): presenter view or a live preview while the model works.
- Empty state: "Open a file" (pick or drop) and "New presentation".

**The UI gets designed properly** (same loop as Ream's office-ui skill): references (MCP Apps examples, host apps'
own visual language, Ream's editor), a UI spec per mode, Claude + Codex review, build, screenshots in each host and
theme, post-build review.

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
(Decided: lives in `mcp/` here; hosted with OAuth + optional local; no server storage; plain HTML tools.)
1. If a host blocks the engine in the view: fall back to a local server engine (Python + Playwright), or simply not
   support that host?

## Review triage (v1 → v2, still applies)
Accepted from both reviewers: compile boundary; stable ids at every depth; payloads hidden and invalidated (fixes a real
silent-revert of edited imported text); reconciliation as shared engine code; transactions with request ids,
auto-rebase, per-element conflicts, persisted before ack; selective undo and a separate destructive restore; typed small
ops; bounded reads; source contract and downloads by capability; durable working copies; document vs view identity;
"since your last call" in results; polling committed state; inert HTML profile; limits; honest privacy; concrete evals;
Ream as first client.
