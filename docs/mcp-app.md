# domOXML MCP (spec v2)

Status: draft v2 for the user's approval, 2026-11-07. v1 was reviewed by a Claude subagent (20 findings) and Codex high
(19); they agreed on every blocker. v2 folds them in (triage at the end). File-type-agnostic: presentations first,
other Office formats later.

## 1. What it is
An MCP server for domOXML, then an MCP App view on top: you and the model work on the same file inside Claude, ChatGPT,
VS Code, Goose or any MCP host. Phase 1 is the tools alone (headless); phase 2 adds the interactive view for co-editing.

## 2. Ground rules
- **The model's language is HTML/CSS, any layout.** What's *stored* is not that HTML: every slide is **compiled** at a
  fixed size by Chromium into domOXML's canvas objects (IR) plus assets, with the model's HTML kept as provenance. The
  view, exports, lint and previews all use the compiled form. Visual edits (drag, resize, restyle) change compiled
  objects; a new whole-slide HTML from the model is an explicit replacement, reconciled against what's there (§4).
- **We don't store people's files.** Files are opened where they live (allowed folders, https URLs, uploads through the
  view); the server keeps a **working copy** with history (like an editor's autosave, on the local machine, under
  `$XDG_DATA_HOME/domoxml-mcp/`), and only writes back to the original when asked. Working copies survive restarts;
  retention and deletion are explicit.
- **Privacy, stated honestly.** Local mode does all processing on this machine, but whatever the tools return (text,
  HTML, previews) goes to the person's AI provider, like any tool output. A hosted mode is a separate, later decision.
- **Inert content.** Slide HTML is a strict profile: no scripts, event handlers, navigation, forms, embedded documents
  or executable SVG; styles scoped to the slide; no network (only `data:` resources, as domOXML's renderer already
  enforces). External pictures come in only through `add_asset` (server fetches https under size limits, no private
  addresses). Imported files are bounded (zip ratio, part count, bytes, pixels, nodes).

## 3. Identity, revisions, transactions
- **Documents and views are separate.** A `file` id is durable (survives restarts). A view (phase 2) is one rendering of
  a file in one tool result; there can be several; they attach to the file and can reattach. All model tools work
  with no view open.
- **Stable element ids at every depth.** The server stamps a short slide-scoped id (`e17`) on every stored element,
  returns them in reads, and never reuses one after deletion. Model HTML that echoes ids keeps them; new elements
  without ids are matched by tag, parent, text and nearest box, and are new only when nothing matches.
- **Internal payloads never reach the model.** Reads show a clean projection (only `data-domoxml-node-id` kept); the
  server reattaches payloads by id on write and **invalidates** any payload whose inputs changed (text changed → text
  payload dropped; box changed → geometry/group payloads dropped). This fixes today's silent revert of edited imported
  text, and is shared with Ream.
- **Revisions are opaque strings** (hash + parent). The server remembers the last revision each caller read, so
  `base_rev` is optional for the model.
- **Transactions**: every write has a `request_id`; the server stores `request_id → input hash → result` with the commit,
  so a retry returns the original result (never a duplicate). Edits to *different* elements than intervening changes
  rebase automatically; a conflict is reported only for the same element (or slide properties, or a whole-slide
  replacement over a changed slide), with that element's current HTML in the error so a retry needs no extra read.
  A batch is atomic by default; `atomic: "slide"` commits slide by slide so one bad id doesn't discard a 6-slide build.
  Each accepted transaction is persisted before it's acknowledged.
- **Undo is selective.** `file_undo(transaction)` applies the inverse of one transaction onto the current state (later
  work by anyone stays); overlapping later changes are reported. Whole-file restore is a separate, explicitly
  destructive tool.

## 4. Reconciliation (shared engine code, in domOXML)
Given the stored slide and new HTML: classify each object as unchanged, geometry-only, content-changed, inserted or
deleted; reuse untouched imported IR, patch geometry where valid, recapture only changed objects, invalidate dependent
payloads, and compare resolved styles where shared CSS can affect objects. Executable fixtures define the behaviour;
Ream's editor and AI use the same code (through its Pyodide worker), so there is one implementation.

## 5. The presentation edit protocol
Typed operations, discriminated by `op`, small enough that a colour change doesn't echo HTML:
| Op | Fields |
|---|---|
| `insert_slides` | `after`: slide ref or `"start"`; `slides`: [{`ref?` (e.g. `"new-1"`, usable later in the batch), `html`, `notes?`, `name?`}] |
| `replace_slide` | `slide`, `html` (reconciled, §4) |
| `patch_element` | `slide`, `id`, any of `style` (CSS declarations merged), `text` (keeps run formatting where it can), `box` {x,y,w,h,rotate}, `html` (whole element) |
| `insert_elements` | `slide`, `after_id?`, `html` |
| `delete_elements` / `reorder_elements` | `slide`, `ids` (+ `to: "front"\|"back"\|"forward"\|"backward"`) |
| `delete_slides` / `move_slides` / `duplicate_slides` | `slides` (+ `after`) |
| `set_slide` | `slide`, any of `notes`, `transition`, `background`, `hidden`, `name` |
| `set_animation` | `slide`, `id`, effect, trigger, order |
| `set_deck` | any of `css`, `theme`, `name`, `size` |
| `add_asset` | `source`: {`path`} \| {`url`} \| {`data`, `media_type`} → `asset:<id>` (immutable, durable, usable in HTML) |

Slide refs: id (`s_ab`), number (resolved against the base revision, not mid-batch), or a `ref` from this batch.

## 6. Tools
Generic file tools (any kind; names use `_`, which model APIs require) plus one edit tool per kind. Read-only tools carry
`readOnlyHint`; anything that takes a URL carries `openWorldHint`; `file_restore` is marked destructive.

| Tool | Does | Returns |
|---|---|---|
| `files_find({query?, kind?, limit?, cursor?})` | Search allowed folders, working copies and recent files by name and extracted text | `file`, kind, name, location, modified, snippet |
| `file_list({open_only?, cursor?})` | Working copies (open/recent), with live-view status | ids, names, parts, rev |
| `file_open({source})` | `source`: {`path`} \| {`url`} \| {`upload_id`} \| {`file`}; imports into a working copy (once; re-opening returns the same file) | `file`, kind, rev, outline, import report (e.g. "2 elements will appear as placeholders") |
| `file_create({kind, name?, size?, theme?})` | New file: `kind: "presentation"` now | `file`, rev, outline |
| `file_read({file, parts?, elements?, query?, detail?, since_rev?, cursor?})` | `detail`: `outline` (per element: id, role, text excerpt, box, key style) / `html` / `html+notes`; paged by a token budget with an explicit truncation note | Parts and elements |
| `file_look({file, parts (≤6), element?, compare_rev?})` | Browser renders (labelled as such; not PowerPoint's) | JPEGs |
| `file_check({file, parts?})` | Overflow, overlap (clipping-aware), off-slide, contrast, what becomes a picture in Office, placeholders, missing fonts | Findings with ids and fixes |
| `presentation_edit({file, ops, request_id, base_rev?, atomic?, check?})` | Apply ops (§5); `check: "changed"` lints changed slides for free | `transaction`, `before_rev`, `rev`, created/changed ids, per-op results, diff per slide, fidelity notes, findings, or a conflict with current HTML |
| `file_history({file, cursor?})` | Read-only list of transactions (who: model/person, summary) | History |
| `file_undo({file, transaction, request_id})` | Selective undo of one transaction | new `rev`, or what blocked it |
| `file_restore({file, target_rev, expected_head, request_id})` | Destructive: the whole file back to an old revision | new `rev` |
| `file_export({file, format, parts?, to?})` | `.pptx` (PNG/HTML later); `to`: save back (explicit `overwrite`), save as a path, or download in the view when the host supports it | path or download, export report |
| `file_show({file, part?})` | (phase 2) A fresh view of an existing file | view |
| `file_close({file})` | Releases runtime resources; the working copy stays | — |

**Every model tool result begins with "since your last call"**: the person's changes (slide, element id, short label),
capped at ~12 lines with "+N more". `updateModelContext` (phase 2) carries only view state the server can't know
(current slide, selection), as a cumulative snapshot with `{file, view, rev}`.

**Resources and prompts**: `domoxml://guide` (authoring slides in HTML for domOXML, with examples), `domoxml://capabilities`
(CSS → Office table), `domoxml://limits`; prompts for "make a deck from notes", "restyle", "fix for PowerPoint".

## 7. Performance
One long-lived Chromium pool with fresh isolated contexts, health checks and restart; JS off in capture unless a slide
needs it; per-render timeout; captures cached by content, shared styles, assets, fonts and renderer version, and one
capture reused for preview, extraction and lint. Phase 2 acceptance numbers: warm capture < 400 ms per slide; tokens
per slide in `outline` and `html` measured on the real-deck corpus.

## 8. The view (phase 3)
- Renders the **compiled** slides (sanitised, each in a shadow root, fonts inlined as `data:` faces, so it matches what
  the server captured).
- **Polls committed state, not commands**: a long-poll (`app_sync`, ~30 s hold, short batching window, under the SDK
  timeout) that also reports the view's state; your edits go through `app_edit` (same ops, same transactions);
  pictures and uploads through `app_blob` (chunked). Three app-only tools, because some hosts ask approval per app tool.
- Only the most recently focused view edits; older ones show "open in the latest view". Offscreen views pause polling.
- Inline: one slide with a filmstrip; full editing tools in fullscreen when the host allows.
- Model edits land per transaction (models are told to send 1–3 slides per edit, so changes arrive in steps, not one
  30-second jump); the changed objects highlight briefly.
- Host capability matrix tested (UI negotiation, app-only calls, images, downloads, fullscreen, uploads, reconnects),
  with usable text-only behaviour when a host has no MCP Apps.

## 9. Evals (before tool shapes freeze)
40 real tasks, 30% held out: make a deck from notes; restyle; fix overflow; table → chart; edit an imported deck;
co-edit while a scripted "person" bot edits the same slides. Verifiers on domOXML's IR (required text present, no
overflow/off-slide findings, counts, export reopens and round-trips, untouched objects preserved, native chart data),
plus a visual rubric only for design quality. Pinned models and settings, repeated trials; metrics: success, tool
calls, tokens, conflicts, retries, errors, wall time. Baseline: Ream's current agent tools exposed over MCP.

## 10. Phases
1. **Shared engine work in domOXML** (reconciliation, stable ids, payload projection and invalidation, inert profile)
   with fixtures, and **Ream as the first client** of it (its AI and editor go through it) in one vertical slice:
   import a deck, edit text, move an imported chart, export, reopen, undo while keeping another actor's work.
2. **Headless MCP** (stdio): durable working copies, the tools above, assets, previews, export, evals.
3. **The interactive view** (co-editing in hosts with MCP Apps).
4. Hosted transport (decision: privacy, session affinity, render sandbox, cost).
5. Rust for whatever the measurements say is slow.

## 11. Open questions for the user
1. Phase order: shared engine work + Ream first (recommended by both reviewers), then the headless MCP, then the view?
2. Working copies: kept locally until deleted, or expire after N days unless saved?

## Review triage (v1 → v2)
Accepted from both: compile boundary (stored = compiled objects, HTML as provenance); stable ids at every depth with
matching; payloads hidden and invalidated (fixes a real silent-revert bug); reconciliation as shared engine code with
fixtures; one transaction contract with request ids, auto-rebase, per-element conflicts, persisted before ack;
selective undo and a separate destructive restore; typed small ops incl. patch_element, insert/reorder elements,
animations, deck CSS, assets with an asset registry; bounded reads with per-element outlines and token paging; source
contract (path/url/upload/file) and downloads by capability; durable working copies and file/view identities; "since
your last call" in results instead of relying on updateModelContext; polling committed state, not a command queue;
inert HTML profile, scoped styles, fonts inlined, shadow roots; Chromium pool, caching and limits; honest privacy
statement; concrete evals with a person bot and Ream's tools as baseline; headless first and Ream as the first client.
Rejected: none. Deferred: an "edit card" view that streams slides while the model writes them; hosted mode.
