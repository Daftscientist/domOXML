// PROTOTYPE — B, "Stage": the deck is something you watch and step through. The slide fills the card edge to edge
// (no wells, no bars), with story-style progress segments, a title overlay on a scrim, tap left/right to flip, and the
// assistant as a live caption, like subtitles. Wide: cinema mode, the slide on a blurred, enlarged copy of itself.
import { useState } from 'react'
import { useHost } from '../host'
import { Icon } from '../icons'
import { SAMPLE } from '../sample'
import { SlideCanvas } from '../SlideCanvas'
import { slideTitle } from './shared'
import './proto.css'

export function VariantB({ width, working, initialSlide }: { width: number; working: boolean; initialSlide: number }) {
  const host = useHost()
  const deck = SAMPLE
  const [i, setI] = useState(initialSlide)
  const [grid, setGrid] = useState(false)
  const [editing, setEditing] = useState(false)
  const s = deck.slides[i]
  const wide = width >= 1024
  const go = (n: number) => setI(Math.max(0, Math.min(deck.slides.length - 1, n)))
  const slideW = wide ? Math.min(width - 160, 1180) : width

  const stage = (
    <div className="pb-stage" style={{ width: slideW }}>
      <SlideCanvas html={s.html} width={slideW} selection={[]} changed={working ? ['e6', 'e7'] : []} interactive={editing} label={`Slide ${i + 1}`} />
      {!editing && <><button className="pb-tap left" aria-label="Previous slide" onClick={() => go(i - 1)} /><button className="pb-tap right" aria-label="Next slide" onClick={() => go(i + 1)} /></>}
      <div className="pb-scrim top">
        <div className="pb-segments">{deck.slides.map((x, k) => <i key={x.id} data-done={k < i || undefined} data-on={k === i || undefined} />)}</div>
        <div className="pb-row">
          <b className="pb-name">{deck.name.replace('.pptx', '')}</b>
          <span className="pb-spacer" />
          <button className="pb-btn" onClick={() => setEditing(!editing)}>{editing ? <><Icon name="check" />Done</> : <>Edit</>}</button>
          <button className="pb-icon" aria-label="All slides" onClick={() => setGrid(true)}><Icon name="more" /></button>
          {host.modes.includes('fullscreen') && <button className="pb-icon" aria-label="Full view" onClick={() => host.requestMode(host.mode === 'fullscreen' ? 'inline' : 'fullscreen')}><Icon name={host.mode === 'fullscreen' ? 'collapse' : 'expand'} /></button>}
        </div>
      </div>
      <div className="pb-scrim bottom">
        {working
          ? <p className="pb-caption"><span className="pb-who"><Icon name="sparkle" />Assistant</span>rewriting “What moved the number”<span className="pb-caret" /></p>
          : <p className="pb-caption"><span className="pb-num">{i + 1}</span>{slideTitle(s, i)}</p>}
        <div className="pb-row">
          <button className="pb-chip"><Icon name="play" />Present</button>
          <button className="pb-chip"><Icon name="comment" />3</button>
          <button className="pb-chip"><Icon name="download" />.pptx</button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="pb" data-wide={wide || undefined}>
      {wide && <div className="pb-blur" aria-hidden><SlideCanvas html={s.html} width={width * 1.2} selection={[]} changed={[]} interactive={false} label="" /></div>}
      {stage}
      {wide && (
        <div className="pb-strip">
          {deck.slides.map((x, k) => (
            <button key={x.id} aria-current={k === i || undefined} onClick={() => go(k)}><SlideCanvas html={x.html} width={120} selection={[]} changed={[]} interactive={false} label={`Slide ${k + 1}`} /></button>
          ))}
        </div>
      )}
      {grid && (
        <div className="pb-grid" role="dialog" aria-label="All slides">
          <div className="pb-grid-head"><b>{deck.slides.length} slides</b><button className="pb-icon dark" aria-label="Close" onClick={() => setGrid(false)}><Icon name="x" /></button></div>
          <div className="pb-grid-body">
            {deck.slides.map((x, k) => (
              <button key={x.id} onClick={() => { go(k); setGrid(false) }} aria-current={k === i || undefined}>
                <SlideCanvas html={x.html} width={Math.max(120, (width - 64) / 2 - 8)} selection={[]} changed={[]} interactive={false} label={`Slide ${k + 1}`} />
                <span>{k + 1} · {slideTitle(x, k)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
