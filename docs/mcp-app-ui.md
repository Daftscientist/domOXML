# domOXML MCP App: the view (UI spec v1)

Status: draft for review, 2026-11-07. Companion to `mcp-app.md` (tools, protocol, engine). Covers every display mode the
MCP Apps spec defines (`inline`, `fullscreen`, `pip`), every container sizing mode, theming from the host, and every
state. Copy never names a model or a host: the AI is "the assistant".

## References (take / leave)
| Reference | Take | Leave |
|---|---|---|
| ext-apps `pdf-server` | Toolbar on top of the document; document on a neutral well; download + fullscreen in the bar | Dense numeric page field and zoom % inline (too much chrome for a 440px card) |
| ext-apps `scenario-modeler` | Calm, compact controls; sections with small caps labels; host-neutral blue accents | Charts-as-chrome |
| ext-apps `transcript-server` | Neutral secondary buttons, one primary action | — |
| Ream deck editor v3 | Contextual bar above the slide acting on the selection; rail; notes drawer; Present | Ream's own brand (here the host's look wins) |
| Google Slides / Keynote | Filmstrip, selection frame, double-click to type | Ribbons |

## Principles
1. **The document is paper; the chrome is the host's.** Slides render in their own colours on a neutral well. Everything
   around them (bars, buttons, panels, menus, focus rings) uses the host's theme and standard variables, so the view
   looks like part of Claude in Claude and part of VS Code in VS Code.
2. **Inline is a live document card, not a squeezed editor.** It shows the deck, lets you click, type and nudge, and
   shows the assistant's work; heavy editing happens in the full panel.
3. **The assistant's work is always visible and never steals control.** It never moves your selection or scroll; its
   changes land with a brief highlight; you can keep working while it works.
4. **Nothing on the slide is covered by chrome.** Bars sit above/below the slide, never over it.

## Theming (host → view tokens)
The view defines its own tokens and fills each from the host's standard variable, falling back to its own default:
| View token | Host variable | Fallback (light / dark) |
|---|---|---|
| `--bg` (bars, panels) | `--color-background-primary` | #ffffff / #1f1f1f |
| `--bg-2` (rail, inactive) | `--color-background-secondary` | #f6f6f6 / #262626 |
| `--well` (behind the slide) | `--color-background-tertiary` | #ececec / #161616 |
| `--text`, `--text-2`, `--text-3` | `--color-text-primary/secondary/tertiary` | #111 #555 #888 / #eee #aaa #777 |
| `--border`, `--border-2` | `--color-border-primary/secondary` | rgba(0,0,0,.12) / rgba(255,255,255,.14) |
| `--ring` (focus, selection) | `--color-ring-primary` | #2563eb / #60a5fa |
| `--info`, `--danger`, `--success`, `--warning` (text/bg/border) | `--color-*-info/danger/success/warning` | standard |
| `--font` | `--font-sans` (+ host font CSS) | system-ui |
| text sizes and line heights | `--font-text-xs/sm/md-size`, `--font-text-*-line-height` | 12/13/14px |
| radii | `--border-radius-sm/md/lg/full` | 6/8/12/999px |
| shadows | `--shadow-hairline/sm/md` | standard |
- `theme` sets `color-scheme` and `[data-theme]`; `onhostcontextchanged` re-applies live (no reload, no flash).
- The selection frame and handles use `--ring`; the assistant's change highlight uses `--info` border; comment pins use
  `--warning`. Slides are never themed or dimmed.
- `platform: mobile` or `deviceCapabilities.touch` → touch layout (§6); `hover: false` → no hover-only affordances.
- `safeAreaInsets` pad the outermost container; `locale` formats numbers and dates.

## Sizing
- **Inline**: width from the container (fixed `width` or up to `maxWidth`; design range 360–760px); height is ours,
  reported through size-change notifications, capped by `maxHeight`. Height = top bar + slide (16:9 of the width minus
  gutters) + filmstrip (+ context strip when something is selected). If `maxHeight` is smaller, the slide scales down
  and centres; the filmstrip stays.
- **Fullscreen**: fill the container (fixed dimensions); layout by width: ≥ 1024 full layout; 640–1023 rail collapses to
  a filmstrip and the comments panel becomes a sheet; < 640 the touch layout.
- **PiP**: fill the small container (typically ~320×180+): the slide only, with minimal controls on hover/tap.
- Resizes are smooth: the slide scales, controls never jump; no layout loop with the host (debounced size reports).

## 1. Inline
```
┌────────────────────────────────────────────────────────┐
│ ▣ Q3 review.pptx  · Saved in this chat   ▷  ⤓▾  ⤢      │  top bar, 40px
├────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐  │
│  │                    slide 4                        │  │  slide, 16:9, on the well
│  └──────────────────────────────────────────────────┘  │
│  [Text ▾]  A− A+  B I U  ■  ⋯                          │  context strip (only with a selection)
│  ▭ ▭ ▭ [▭] ▭ ▭ ▭ ▭ ▭  +                     4 / 12     │  filmstrip, 56px
└────────────────────────────────────────────────────────┘
```
**Top bar** (40px, `--bg`, hairline below)
- *Left*: file icon (kind), file name (13px semibold; click → rename inline, Enter/blur saves, Esc reverts), then a quiet
  status: "Saved in this chat" / "Unsaved changes" / while the assistant works: a pulsing `--info` dot + "Editing slide
  4…" (the activity label from its tool call). Status truncates first when narrow.
- *Right* (icon buttons, 32px, tooltips, keyboard reachable): **Present** (▷), **Download** (⤓ ▾: PowerPoint (.pptx) /
  Web page (.html)), **Expand** (⤢, only if the host offers `fullscreen`). Below 420px: Present and Download fold into a
  ⋯ menu.
**Slide**
- 12px gutters on the well. Click selects (frame + 8 handles in `--ring`); shift-click adds; click empty deselects;
  drag moves (smart guides as Ream); handles resize; double-click edits text in place; Delete removes; arrows nudge
  (shift ×10); Esc deselects. Changes save as transactions (Undo ⌘Z / Redo ⌘⇧Z, your own only).
- The assistant's changed objects get a 2px `--info` outline that fades over 1.2s; a slide it's editing shows a thin
  `--info` progress hairline along the top of the slide.
- Comment pins (`--warning` dots) sit on objects with open comments; clicking one opens the thread as a popover.
**Context strip** (appears under the slide only while something is selected; 40px; slides down 120ms, reduced motion:
fade)
- Leading chip names the selection ("Text box", "Picture", "3 objects") and opens a menu of everything for it
  (arrange, align, duplicate, delete, comment, alt text…).
- Essentials by type: text → font size −/+, B I U, colour, align ▾; shape → fill, border; picture → replace, crop (full
  panel); table/chart → "Edit in full view". Always ends with ⋯ and, if available, "Open in full view" (⤢).
**Filmstrip** (56px)
- Thumbnails (64px wide, 16:9) scroll horizontally; current one ringed; slides the assistant changed get a small `--info`
  dot until viewed; hidden slides dimmed with an icon; drag to reorder; right-click/long-press: duplicate, hide, delete,
  add after. Trailing **+** adds a blank slide after the current one. Right: "4 / 12" (←/→ when the filmstrip or slide
  is focused). Wheel scrolls horizontally.
**Inline states**
- *Empty* (opened with no file): a dashed drop zone filling the slide area: "Drop a PowerPoint file here, or choose one"
  (button) and "New presentation" (secondary). Dragging a file over: the zone highlights `--ring`.
- *Opening/importing*: the slide area shows the file name and a determinate progress line ("Reading slides 3 of 12");
  first start of the engine: "Starting the editor…" with real progress (download bytes), never an endless spinner.
- *Error*: inline message in the slide area with the reason and **Try again**; for unsupported files, what isn't
  supported.
- *Superseded* (the same file is open in a newer view lower in the conversation): the view dims chrome, shows the last
  state read-only with a bar: "This presentation continues in a newer view below" (button scrolls/announces). Editing is
  only ever in the newest-focused view.
- *Disconnected* (lost its link to the server): a slim `--warning` bar: "Reconnecting…"; edits keep locally and sync on
  reconnect.

## 2. Fullscreen (the full panel)
```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ ▣ Q3 review.pptx · Saved      ↶ ↷        💬 3   ▷ Present  ⤓ Download ▾   ⤡ Collapse  │ top bar 48px
├──────────┬──────────────────────────────────────────────────────────────┬─────────────┤
│ ▭ 1      │ [Text box ▾] Font ▾  24  ■  B I U  Align ▾  •  1. │ Arrange ▾ ⋯  │ Comments    │
│ ▭ 2      │                                                              │  threads…   │
│ ▭ 3      │            ┌──────────── slide ────────────┐                 │             │
│ ▭ 4      │            └───────────────────────────────┘     [− Fit +]   │             │
│          ├──────────────────────────────────────────────────────────────┤             │
│ + Slide  │ ▴ Notes  first line of the speaker notes…                    │             │
└──────────┴──────────────────────────────────────────────────────────────┴─────────────┘
```
- **Top bar**: name + status (as inline), Undo/Redo, **Comments** toggle with count, **Present**, **Download ▾**,
  **Collapse** (back to inline). Labels shown at ≥ 1024px, icons below.
- **Rail** (180px, `--bg-2`): vertical thumbnails with numbers, sections as small headers, drag to reorder, context menu
  (duplicate, hide, delete, new section), **+ Slide** (blank / from layout).
- **Context bar** (44px, above the slide, acts on the selection, as Ream's v3 editor): nothing selected → Background,
  Transition ▾ (effect, direction, duration, apply to all), Layout ▾, Theme ▾; text → font, size, colour, B I U, align,
  lists, spacing; shape/picture/table/chart/line → their sections; several → align/distribute/group. Popovers are
  solid (`--bg`, `--shadow-md`), never glass.
- **Canvas**: the slide fit to the well, zoom − Fit + bottom right, same direct manipulation as inline plus crop, table
  cell editing and chart data editing (a grid dialog).
- **Comments panel** (320px, toggle): threads by slide; each shows the element it's on (hover highlights it), author
  ("You" / "Assistant"), time, replies, Resolve; composer at the bottom ("Comment on Text box…" when something's
  selected). New comments from the assistant show an `--info` dot on the toggle.
- **Notes drawer**: as Ream's: 32px strip with the first line; opens to a 160px editor.
- **Narrow fullscreen** (640–1023): rail becomes a bottom filmstrip; comments open as a right sheet over the canvas.

## 3. Present
- From either mode: the slide fills the view (in fullscreen when available; inline presents within the card, offering
  "Present full screen" if the host allows). Click/→/space next, ←/backspace previous, number + Enter jumps, Esc ends.
  Transitions and animations play as authored (domOXML's player). A small counter fades in on mouse move.
- If the host offers `pip`, "Presenter view" puts the next slide + notes in PiP while presenting.

## 4. PiP
- The current slide only, fitted; on hover/tap: ← → and "Back" (to the previous mode). While the assistant works, PiP
  shows its activity line under the slide. No editing in PiP.

## 5. Shared overlays
- **Menus/popovers**: solid `--bg`, `--border`, `--shadow-md`, `--border-radius-md`; keyboard navigable; Esc closes;
  never cover the selection when avoidable.
- **Toasts** (bottom centre inside the view): "Downloaded Q3 review.pptx", "Undone", errors with Retry.
- **Download**: uses the host's download (`ui/download-file`) when offered; otherwise a link in a small sheet the person
  clicks. The file name follows the deck name.

## 6. Touch and mobile
- Inline on touch: view, filmstrip navigation, tap to select and see details, Present, Download; editing opens the full
  panel (tap "Edit" in the top bar). Targets ≥ 44px; long-press for context menus; no hover affordances.
- Fullscreen on phones: one column: top bar, slide, a bottom toolbar (context actions for the selection), filmstrip;
  comments and notes as sheets.

## 7. Keyboard and accessibility
- Every control reachable; visible focus ring `--ring` (2px, offset). ⌘Z/⌘⇧Z, Delete, arrows, Enter (edit text), Esc,
  ⌘D duplicate, ⌘G group, ⌘/ comments, F5 present, ←/→ slides when the filmstrip/rail is focused.
- Slides expose their content in reading order to screen readers; the assistant's edits are announced politely ("The
  assistant changed slide 4: title, chart"); status changes announced; no announcement storms during streaming.
- Reduced motion: no slides/fades beyond 150ms cross-fades; the change highlight becomes a static outline for 1.2s.

## 8. What the view sends (the person's state)
On every relevant change, debounced: current slide, selection (ids), caret (when typing), viewport (zoom, visible
region), mode (edit/present/comment), open panel; plus edits and comments as they happen (see `mcp-app.md` §3a).

## 9. Build and review
React + Vite single-file bundle (the ext-apps pattern), `@modelcontextprotocol/ext-apps` App class. A dev page renders
the view with chosen host context (theme, variables, display mode, size) so every mode × theme × width can be
screenshotted; then tested in the ext-apps `basic-host` against the real server. Reviews: this spec (Claude + Codex)
before building; screenshots (Codex) after.
