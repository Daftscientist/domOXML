// The domOXML view (spec: docs/mcp-app-ui.md). Two surfaces, calm and minimal: a clean background, hairline borders,
// quiet type, no filled bars or wells.
// - Preview (inline in the conversation): the slide, one line of details, Present and Open editor.
// - Editor (the full panel; or inside the card when the host has no fullscreen): slides, the slide, a quiet toolbar,
//   notes, comments. "Done" goes back to the preview.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useHost } from './host'
import { SAMPLE, type Slide } from './sample'
import { SlideCanvas, SLIDE_H, SLIDE_W } from './SlideCanvas'
import { Icon } from './icons'
import './view.css'

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.round(e.contentRect.width), h: Math.round(e.contentRect.height) }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

export function View() {
  const host = useHost()
  const q = new URLSearchParams(location.search)
  const deck = SAMPLE
  const [current, setCurrent] = useState(Number(q.get('slide') ?? 1) - 1)
  const [inCardEditor, setInCardEditor] = useState(false)
  const working = q.get('activity') === '1'
  const changes = q.get('changes') === '1' ? 2 : 0
  const canFull = host.modes.includes('fullscreen')
  const editing = host.mode === 'fullscreen' || inCardEditor

  const openEditor = () => (canFull ? host.requestMode('fullscreen') : setInCardEditor(true))
  const closeEditor = () => (host.mode === 'fullscreen' ? host.requestMode('inline') : setInCardEditor(false))
  const go = (n: number) => setCurrent(Math.max(0, Math.min(deck.slides.length - 1, n)))

  if (editing) return <Editor deck={deck} current={current} onGo={go} onDone={closeEditor} working={working} />
  return <Preview deck={deck} current={current} onGo={go} onEdit={openEditor} working={working} changes={changes} />
}

// ---------- Preview ----------

function Preview({ deck, current, onGo, onEdit, working, changes }: { deck: typeof SAMPLE; current: number; onGo: (n: number) => void; onEdit: () => void; working: boolean; changes: number }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const slide = deck.slides[current]
  const narrow = w > 0 && w < 440
  const slideW = Math.max(0, w)
  return (
    <div ref={ref} className="preview">
      <div className="preview-slide" onDoubleClick={onEdit}>
        {slideW > 0 && <SlideCanvas html={slide.html} width={slideW} selection={[]} changed={working ? ['e6', 'e7'] : []} interactive={false} label={`Slide ${current + 1} of ${deck.slides.length}: ${deck.name}`} />}
        <button className="edge prev" aria-label="Previous slide" disabled={current === 0} onClick={() => onGo(current - 1)}><Icon name="left" /></button>
        <button className="edge next" aria-label="Next slide" disabled={current === deck.slides.length - 1} onClick={() => onGo(current + 1)}><Icon name="right" /></button>
      </div>
      <div className="preview-meta">
        <span className="name" title={deck.name}>{deck.name.replace(/\.pptx$/, '')}</span>
        {working
          ? <span className="quiet live"><i className="dot-live" />{narrow ? 'Editing slide 2' : 'Assistant is editing slide 2'}</span>
          : changes
            ? <span className="quiet">{narrow ? `${changes} changes` : `${changes} changes by the assistant`} · <button className="link">Review</button></span>
            : <span className="quiet">{current + 1} of {deck.slides.length}</span>}
        <span className="grow" />
        <button className="text-btn"><Icon name="play" />{!narrow && 'Present'}</button>
        <button className="text-btn strong" onClick={onEdit}>{narrow ? 'Edit' : 'Open editor'}</button>
      </div>
    </div>
  )
}

// ---------- Editor ----------

function Editor({ deck, current, onGo, onDone, working }: { deck: typeof SAMPLE; current: number; onGo: (n: number) => void; onDone: () => void; working: boolean }) {
  const q = new URLSearchParams(location.search)
  const [stageRef, stage] = useSize<HTMLDivElement>()
  const [selection, setSelection] = useState<string[]>(q.get('select')?.split(',') ?? [])
  const [comments, setComments] = useState(q.get('comments') === '1')
  const [notesOpen, setNotesOpen] = useState(false)
  const slide = deck.slides[current]
  const select = useCallback((ids: string[], additive: boolean) => setSelection((s) => (additive ? [...new Set([...s, ...ids])] : ids)), [])
  useEffect(() => { if (!q.get('select')) setSelection([]) }, [current]) // eslint-disable-line react-hooks/exhaustive-deps
  const fit = Math.max(0, Math.min(stage.w - 96, (stage.h - 80) * (SLIDE_W / SLIDE_H)))

  return (
    <div className="editor">
      <header className="ed-top">
        <span className="name">{deck.name.replace(/\.pptx$/, '')}</span>
        <span className="quiet">{working ? <><i className="dot-live" />Assistant is editing slide 2</> : 'Saved in this browser'}</span>
        <span className="grow" />
        <button className="icon-btn" aria-label="Undo"><Icon name="undo" /></button>
        <button className="icon-btn" aria-label="Redo"><Icon name="redo" /></button>
        <span className="rule" />
        <button className="text-btn" aria-pressed={comments} onClick={() => setComments(!comments)}><Icon name="comment" />Comments<span className="count">3</span></button>
        <button className="text-btn"><Icon name="play" />Present</button>
        <button className="text-btn"><Icon name="download" />Download</button>
        <button className="text-btn strong" onClick={onDone}>Done</button>
      </header>

      <Toolbar selection={selection} />

      <div className="ed-body">
        <nav className="ed-slides" aria-label="Slides">
          {deck.slides.map((s, i) => <Thumb key={s.id} slide={s} n={i} active={i === current} onClick={() => onGo(i)} changed={working && i === 1} />)}
          <button className="add">+ New slide</button>
        </nav>

        <main className="ed-stage" ref={stageRef}>
          {fit > 0 && <SlideCanvas html={slide.html} width={fit} selection={selection} changed={working ? ['e6', 'e7'] : []} interactive onSelect={select} label={`Slide ${current + 1} of ${deck.slides.length}`} />}
          <span className="zoom quiet">Fit</span>
        </main>

        {comments && (
          <aside className="ed-comments" aria-label="Comments">
            <div className="thread">
              <p className="who">You <span className="quiet">on “+18%” · 2m</span></p>
              <p>Can we check this against the board pack figure?</p>
              <p className="who">Assistant <span className="quiet">just now</span></p>
              <p>The board pack says 17.6%, rounded to 18%. Want one decimal?</p>
              <p className="actions"><button className="link">Reply</button><button className="link">Resolve</button></p>
            </div>
            <div className="thread">
              <p className="who">Assistant <span className="quiet">on slide 3 · 5m</span></p>
              <p>Q4 is a forecast. Should the bar show that?</p>
              <p className="actions"><button className="link">Reply</button><button className="link">Resolve</button></p>
            </div>
            <textarea className="compose" placeholder="Add a comment…" rows={2} />
          </aside>
        )}
      </div>

      <footer className="ed-notes">
        {notesOpen
          ? <textarea autoFocus defaultValue={slide.notes ?? ''} placeholder="Speaker notes" aria-label="Speaker notes" onBlur={() => setNotesOpen(false)} />
          : <button onClick={() => setNotesOpen(true)}>{slide.notes ?? <span className="quiet">Add speaker notes…</span>}</button>}
      </footer>
    </div>
  )
}

function Toolbar({ selection }: { selection: string[] }) {
  if (!selection.length) {
    return (
      <div className="ed-tools" role="toolbar" aria-label="Insert and slide">
        <button className="tool"><Icon name="text" />Text</button>
        <button className="tool"><Icon name="shape" />Shape</button>
        <button className="tool"><Icon name="image" />Image</button>
        <button className="tool"><Icon name="table" />Table</button>
        <button className="tool"><Icon name="chart" />Chart</button>
        <span className="rule" />
        <button className="tool">Background</button>
        <button className="tool">Transition</button>
        <button className="tool">Layout</button>
      </div>
    )
  }
  return (
    <div className="ed-tools" role="toolbar" aria-label="Format">
      <button className="tool field">Inter<Icon name="caret" small /></button>
      <button className="tool field num">56</button>
      <span className="rule" />
      <button className="tool sq b" aria-label="Bold">B</button>
      <button className="tool sq i" aria-label="Italic">I</button>
      <button className="tool sq u" aria-label="Underline">U</button>
      <button className="tool sq" aria-label="Colour"><i className="swatch" /></button>
      <span className="rule" />
      <button className="tool">Align</button>
      <button className="tool">Arrange</button>
      <button className="tool">Animate</button>
      <span className="grow" />
      <button className="tool"><Icon name="sparkle" />Ask the assistant</button>
    </div>
  )
}

function Thumb({ slide, n, active, onClick, changed }: { slide: Slide; n: number; active: boolean; onClick: () => void; changed: boolean }) {
  return (
    <button className="thumb" aria-current={active || undefined} data-hidden={slide.hidden || undefined} onClick={onClick} aria-label={`Slide ${n + 1}`}>
      <span className="num">{n + 1}</span>
      <span className="frame"><SlideCanvas html={slide.html} width={148} selection={[]} changed={[]} interactive={false} label="" /></span>
      {changed && <i className="dot-live corner" aria-label="Changed by the assistant" />}
    </button>
  )
}
