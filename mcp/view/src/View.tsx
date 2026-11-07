// The domOXML view: one responsive layout (spec: docs/mcp-app-ui.md). Width decides how much editing is offered:
// narrow (< 520px) view + select + type; medium (520–1023) adds the context strip and filmstrip editing; wide (≥ 1024,
// usually the full panel) is the full editor. Display mode only changes the expand/collapse control.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useHost } from './host'
import { SAMPLE } from './sample'
import { SlideCanvas, SLIDE_H, SLIDE_W } from './SlideCanvas'
import { Icon } from './icons'
import './view.css'

type Tier = 'narrow' | 'medium' | 'wide'
const tierOf = (w: number): Tier => (w < 520 ? 'narrow' : w < 1024 ? 'medium' : 'wide')

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

export function View() {
  const host = useHost()
  const q = new URLSearchParams(location.search)
  const [root, width] = useWidth<HTMLDivElement>()
  const tier = tierOf(width)
  const deck = SAMPLE
  const [current, setCurrent] = useState(Number(q.get('slide') ?? 1) - 1)
  const [selection, setSelection] = useState<string[]>(q.get('select')?.split(',') ?? [])
  const [comments, setComments] = useState(q.get('comments') === '1')
  const [notes, setNotes] = useState(q.get('notes') === '1')
  const working = q.get('activity') === '1'
  const changed = working ? ['e6', 'e7'] : []
  const slide = deck.slides[current]
  const fullscreen = host.mode === 'fullscreen'
  const canExpand = host.modes.includes('fullscreen')

  const select = useCallback((ids: string[], additive: boolean) => setSelection((s) => (additive ? [...new Set([...s, ...ids])] : ids)), [])
  useEffect(() => setSelection((s) => (q.get('select') ? s : [])), [current]) // eslint-disable-line react-hooks/exhaustive-deps

  if (host.mode === 'pip') return <Pip ref={root} width={width} height={(host.context.containerDimensions as { height?: number } | undefined)?.height ?? 220} slide={slide} n={current} total={deck.slides.length} onNav={setCurrent} working={working} />

  const touch = !!host.context.deviceCapabilities?.touch && host.context.deviceCapabilities?.hover === false
  const reviewing = q.get('changes') === '1'
  const status = working
    ? <span className="status working"><i className="pulse" />Assistant: editing slide 2</span>
    : <span className="status">Kept in this browser</span>
  // The assistant's changes stay visible until reviewed (the card may be far up the conversation when they land).
  const changesChip = reviewing && !working && (
    <span className="changes" role="status">{tier === 'narrow' ? '2 changes' : '2 changes on slide 2'}<button>Review</button>{tier !== 'narrow' && <button>Undo</button>}</span>
  )

  const topBar = (
    <header className="topbar">
      <span className="file"><Icon name="deck" /><b title={deck.name}>{deck.name}</b>{tier === 'wide' && <Icon name="caret" small />}</span>
      {changesChip || (tier !== 'narrow' && status)}
      <span className="spacer" />
      <IconButton icon="undo" label="Undo" />
      {tier === 'wide' && <IconButton icon="redo" label="Redo" />}
      <IconButton icon="comment" label={comments ? 'Hide comments' : 'Comments'} badge={3} pressed={comments} onClick={() => setComments(!comments)} />
      {tier !== 'narrow' && <IconButton icon="play" label="Present" text={tier === 'wide' ? 'Present' : undefined} />}
      {tier !== 'narrow' ? <IconButton icon="download" label="Download" text={tier === 'wide' ? 'Download' : undefined} menu /> : <IconButton icon="more" label="Present, download and more" />}
      {canExpand && (fullscreen
        ? <IconButton icon="collapse" label="Back to the conversation" onClick={() => host.requestMode('inline')} />
        : <IconButton icon="expand" label="Open full view" onClick={() => host.requestMode('fullscreen')} />)}
    </header>
  )

  if (tier === 'wide') {
    const compactRail = comments && width < 1280
    const stageW = width - (compactRail ? 64 : 180) - (comments ? 320 : 0) - 96
    const slideW = Math.max(320, Math.min(stageW, ((fullscreen ? innerHeight : 720) - 48 - 44 - 32 - 80) * (SLIDE_W / SLIDE_H)))
    return (
      <div ref={root} className="view wide" data-fullscreen={fullscreen || undefined} data-touch={touch || undefined}>
        {topBar}
        <div className="body">
          <nav className="rail" aria-label="Slides" data-compact={compactRail || undefined}>
            {deck.slides.map((s, i) => (
              <button key={s.id} className="rail-item" aria-current={i === current || undefined} data-hidden={s.hidden || undefined} onClick={() => setCurrent(i)}>
                <span className="num">{i + 1}</span>
                {!compactRail && <span className="thumb"><SlideCanvas html={s.html} width={132} selection={[]} changed={[]} interactive={false} label={`Slide ${i + 1}`} /></span>}
                {working && i === 1 && <i className="dot" aria-label="Changed by the assistant" />}
              </button>
            ))}
            {!compactRail && <button className="add-slide"><Icon name="plus" />Slide</button>}
          </nav>
          <main className="stage">
            <ContextBar selection={selection} insert={!compactRail || !comments} />
            <div className="canvas">
              <SlideCanvas html={slide.html} width={slideW} selection={selection} changed={changed} interactive onSelect={select} label={`Slide ${current + 1} of ${deck.slides.length}`} />
              <div className="zoom"><button aria-label="Zoom out">−</button><span>Fit</span><button aria-label="Zoom in">+</button></div>
            </div>
            <button className="notes" aria-expanded={notes} onClick={() => setNotes(!notes)}>
              <Icon name={notes ? 'down' : 'up'} /><b>Notes</b><span>{slide.notes ?? 'Click to add speaker notes'}</span>
            </button>
            {notes && <textarea className="notes-editor" defaultValue={slide.notes ?? ''} placeholder="Speaker notes" aria-label="Speaker notes" />}
          </main>
          {comments && <Comments />}
        </div>
      </div>
    )
  }

  // Narrow and medium: the card.
  const slideW = Math.max(200, width - 24)
  return (
    <div ref={root} className={`view ${tier}`} data-touch={touch || undefined}>
      {topBar}
      <div className="card-slide">
        {width > 0 && <SlideCanvas html={slide.html} width={slideW} selection={selection} changed={changed} interactive onSelect={select} label={`Slide ${current + 1} of ${deck.slides.length}`} />}
        {working && <i className="progress" aria-hidden />}
      </div>
      <Strip tier={tier} selection={selection} working={working && tier === 'narrow'} />
      <div className="filmstrip" aria-label="Slides">
        <div className="film">
          {deck.slides.map((s, i) => (
            <button key={s.id} className="film-item" aria-current={i === current || undefined} aria-label={`Slide ${i + 1}`} data-hidden={s.hidden || undefined} onClick={() => setCurrent(i)}>
              <SlideCanvas html={s.html} width={tier === 'narrow' ? 56 : 64} selection={[]} changed={[]} interactive={false} label="" />
              {working && i === 1 && <i className="dot" />}
            </button>
          ))}
          {tier === 'medium' && <button className="film-add" aria-label="Add a slide after this one"><Icon name="plus" /></button>}
        </div>
        <span className="count">{current + 1} / {deck.slides.length}</span>
      </div>
    </div>
  )
}

function IconButton({ icon, label, text, badge, pressed, menu, onClick }: { icon: Parameters<typeof Icon>[0]['name']; label: string; text?: string; badge?: number; pressed?: boolean; menu?: boolean; onClick?: () => void }) {
  return (
    <button className="ib" data-text={text ? '' : undefined} aria-label={label} title={label} aria-pressed={pressed} aria-haspopup={menu ? 'menu' : undefined} onClick={onClick}>
      <Icon name={icon} />{text && <span>{text}</span>}{menu && <Icon name="caret" small />}{!!badge && <em>{badge}</em>}
    </button>
  )
}

/** The card's strip: always present (the card never changes height on select). Shows the assistant's activity, the
 *  selection's essentials (medium), or slide-level actions. */
function Strip({ tier, selection, working }: { tier: Tier; selection: string[]; working: boolean }) {
  if (working) return <div className="strip" role="status"><span className="activity"><i className="pulse" />Assistant: editing slide 2</span></div>
  if (!selection.length) {
    return (
      <div className="strip" role="toolbar" aria-label="Slide">
        <button className="chip">Slide<Icon name="caret" small /></button>
        {tier === 'medium' && <><button className="tb"><Icon name="plus" />Insert<Icon name="caret" small /></button><button className="tb">Layout<Icon name="caret" small /></button></>}
        <span className="spacer" />
        <button className="tb"><Icon name="sparkle" />Ask about this slide</button>
      </div>
    )
  }
  const label = selection.length > 1 ? `${selection.length} objects` : 'Text box'
  return (
    <div className="strip" role="toolbar" aria-label={`Format ${label}`}>
      <button className="chip">{label}<Icon name="caret" small /></button>
      {tier === 'medium' && <>
        <span className="sep" />
        <button className="ib b" aria-label="Bold">B</button><button className="ib i" aria-label="Italic">I</button><button className="ib u" aria-label="Underline">U</button>
        <button className="tb num" aria-label="Font size">56</button>
        <button className="ib" aria-label="Text colour"><i className="swatch" /></button>
      </>}
      <span className="spacer" />
      <button className="tb"><Icon name="sparkle" />{tier === 'narrow' ? 'Ask' : 'Ask about this'}</button>
      <button className="ib" aria-label="More"><Icon name="more" /></button>
    </div>
  )
}

function ContextBar({ selection, insert }: { selection: string[]; insert: boolean }) {
  const ins = insert && (
    <span className="insert" role="group" aria-label="Insert">
      <span className="sep" />
      <button className="ib" aria-label="Text box" title="Text box"><Icon name="text" /></button>
      <button className="ib" aria-label="Shapes" title="Shapes"><Icon name="shape" /></button>
      <button className="ib" aria-label="Picture" title="Picture"><Icon name="image" /></button>
      <button className="ib" aria-label="Table" title="Table"><Icon name="table" /></button>
      <button className="ib" aria-label="Chart" title="Chart"><Icon name="chart" /></button>
    </span>
  )
  if (!selection.length) {
    return (
      <div className="context-bar" role="toolbar" aria-label="Slide">
        <button className="chip">Slide<Icon name="caret" small /></button><span className="sep" />
        <button className="tb">Background<Icon name="caret" small /></button>
        <button className="tb">Transition<Icon name="caret" small /></button>
        <button className="tb">Layout<Icon name="caret" small /></button>
        <span className="spacer" />{ins}
      </div>
    )
  }
  return (
    <div className="context-bar" role="toolbar" aria-label="Format selection">
      <button className="chip">{selection.length > 1 ? `${selection.length} objects` : 'Text box'}<Icon name="caret" small /></button><span className="sep" />
      <button className="tb font">Inter<Icon name="caret" small /></button><button className="tb num">56</button>
      <button className="ib" aria-label="Text colour"><i className="swatch" /></button>
      <button className="ib b" aria-label="Bold">B</button><button className="ib i" aria-label="Italic">I</button><button className="ib u" aria-label="Underline">U</button>
      <button className="tb">Align<Icon name="caret" small /></button><span className="sep" />
      <button className="tb">Fill<Icon name="caret" small /></button><button className="tb">Arrange<Icon name="caret" small /></button><button className="tb">Animate<Icon name="caret" small /></button>
      <span className="spacer" /><button className="ib" aria-label="More"><Icon name="more" /></button>{ins}
    </div>
  )
}

function Comments() {
  return (
    <aside className="comments" aria-label="Comments">
      <header><b>Comments</b><span>3 open</span></header>
      <div className="threads">
        <article className="thread">
          <p className="meta"><b>You</b> · on “+18%” · 2m</p>
          <p>Can we check this against the board pack figure?</p>
          <div className="reply"><p className="meta"><b>Assistant</b> · just now</p><p>The board pack says 17.6%, rounded to 18%. Want me to show one decimal?</p></div>
          <div className="actions"><button>Reply</button><button>Resolve</button><button className="ask">Ask the assistant</button></div>
        </article>
        <article className="thread">
          <p className="meta"><b>Assistant</b> · on slide 3 · 5m</p>
          <p>Q4 is a forecast. Should the bar be hatched to show that?</p>
          <div className="actions"><button>Reply</button><button>Resolve</button></div>
        </article>
      </div>
      <div className="composer"><textarea placeholder="Comment on this slide…" aria-label="New comment" rows={2} /></div>
    </aside>
  )
}

function Pip({ ref, width, height, slide, n, total, onNav, working }: { ref: React.RefObject<HTMLDivElement | null>; width: number; height: number; slide: { html: string }; n: number; total: number; onNav: (i: number) => void; working: boolean }) {
  return (
    <div ref={ref} className="view pip">
      <div className="pip-stage">{width > 0 && <SlideCanvas html={slide.html} width={Math.min(width, Math.max(80, (height - 36) * (SLIDE_W / SLIDE_H)))} selection={[]} changed={[]} interactive={false} label={`Slide ${n + 1} of ${total}`} />}</div>
      <div className="pip-bar">
        <button className="ib" aria-label="Previous slide" onClick={() => onNav(Math.max(0, n - 1))}><Icon name="left" /></button>
        <span>{working ? 'Assistant: editing slide 2' : `${n + 1} / ${total}`}</span>
        <button className="ib" aria-label="Next slide" onClick={() => onNav(Math.min(total - 1, n + 1))}><Icon name="right" /></button>
      </div>
    </div>
  )
}
