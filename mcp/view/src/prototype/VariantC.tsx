// PROTOTYPE — C, "Canvas": a shared board you and the assistant both work on. Slides are artboards laid out on a dotted
// canvas (the focused one large, its neighbours peeking), tools live in a floating dock, comments are sticky notes
// pinned beside the slide, and the assistant is a named cursor you can watch move to what it's changing. Co-editing
// made visible.
import { useState } from 'react'
import { useHost } from '../host'
import { Icon } from '../icons'
import { SAMPLE } from '../sample'
import { SlideCanvas } from '../SlideCanvas'
import { slideTitle } from './shared'
import './proto.css'

export function VariantC({ width, working, initialSlide, initialSelection }: { width: number; working: boolean; initialSlide: number; initialSelection: string[] }) {
  const host = useHost()
  const deck = SAMPLE
  const [i, setI] = useState(initialSlide)
  const [sel, setSel] = useState<string[]>(initialSelection)
  const wide = width >= 1024
  const narrow = width < 520
  const focusW = wide ? Math.min(width - 520, 900) : width - (narrow ? 64 : 140)
  const peekW = Math.round(focusW * 0.42)
  const go = (n: number) => { setI(Math.max(0, Math.min(deck.slides.length - 1, n))); setSel([]) }

  const board = (k: number, w: number, focus: boolean) => {
    const x = deck.slides[k]
    return (
      <div key={x.id} className="pc-board" data-focus={focus || undefined} onClick={() => !focus && go(k)}>
        <span className="pc-label"><b>{k + 1}</b> {slideTitle(x, k)}{x.hidden && <em>hidden</em>}</span>
        <div className="pc-art">
          <SlideCanvas html={x.html} width={w} selection={focus ? sel : []} changed={focus && working ? ['e6', 'e7'] : []} interactive={focus} onSelect={(ids) => setSel(ids)} label={`Slide ${k + 1}`} />
          {focus && working && (
            <span className="pc-cursor" style={{ left: w * 0.14, top: w * 0.25 }}>
              <svg width="18" height="18" viewBox="0 0 24 24"><path d="M3 2l7 19 2.5-7.5L20 11z" fill="#8b5cf6" stroke="#fff" strokeWidth="1.5" /></svg>
              <span className="pc-tag">Assistant · rewriting</span>
            </span>
          )}
          {focus && k === 1 && (
            <span className="pc-pin" style={{ left: w * 0.33, top: w * 0.15 }} aria-label="2 comments">2</span>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="pc" data-wide={wide || undefined} data-narrow={narrow || undefined}>
      <header className="pc-top">
        <span className="pc-title"><span className="pc-avatars"><i className="you">Y</i><i className="ai"><Icon name="sparkle" /></i></span><b>{deck.name.replace('.pptx', '')}</b></span>
        <span className="pc-spacer" />
        <button className="pc-pill"><Icon name="play" />{!narrow && 'Present'}</button>
        <button className="pc-pill ghost" aria-label="Download"><Icon name="download" /></button>
        {host.modes.includes('fullscreen') && <button className="pc-pill ghost" aria-label="Full view" onClick={() => host.requestMode(host.mode === 'fullscreen' ? 'inline' : 'fullscreen')}><Icon name={host.mode === 'fullscreen' ? 'collapse' : 'expand'} /></button>}
      </header>

      <div className="pc-canvas">
        {!narrow && (
          <nav className="pc-dock" aria-label="Tools">
            <button aria-pressed="true" aria-label="Select"><svg width="16" height="16" viewBox="0 0 24 24"><path d="M5 3l6 17 2-7 7-2z" fill="currentColor" /></svg></button>
            <button aria-label="Text"><Icon name="text" /></button>
            <button aria-label="Shape"><Icon name="shape" /></button>
            <button aria-label="Picture"><Icon name="image" /></button>
            <button aria-label="Table"><Icon name="table" /></button>
            <button aria-label="Chart"><Icon name="chart" /></button>
            <span className="pc-dock-sep" />
            <button aria-label="Comment"><Icon name="comment" /></button>
          </nav>
        )}

        <div className="pc-row">
          {!narrow && i > 0 && board(i - 1, peekW, false)}
          {board(i, focusW, true)}
          {!narrow && !wide && i < deck.slides.length - 1 && board(i + 1, peekW, false)}
        </div>

        {wide && (
          <div className="pc-stickies">
            <div className="pc-sticky" style={{ ['--rot' as string]: '-1.5deg' }}>
              <p className="pc-sby">You</p><p>Check +18% against the board pack?</p>
              <p className="pc-sby ai">Assistant</p><p>17.6% in the pack, rounded. One decimal?</p>
            </div>
            <div className="pc-sticky blue" style={{ ['--rot' as string]: '1.2deg' }}>
              <p className="pc-sby">Notes</p><p>{deck.slides[i].notes ?? 'Speak to the three numbers, left to right.'}</p>
            </div>
          </div>
        )}

        {sel.length > 0 && (
          <div className="pc-selbar">
            <span>Text</span><button className="b">B</button><button className="i">I</button><button>56</button><i className="pc-sw" /><button className="pc-ask"><Icon name="sparkle" />Ask about this</button>
          </div>
        )}
      </div>

      <footer className="pc-foot">
        <button aria-label="Previous" onClick={() => go(i - 1)}><Icon name="left" /></button>
        <span className="pc-mini">{deck.slides.map((x, k) => <i key={x.id} data-on={k === i || undefined} onClick={() => go(k)} />)}</span>
        <button aria-label="Next" onClick={() => go(i + 1)}><Icon name="right" /></button>
        {working && <span className="pc-live"><i />Assistant on slide 2</span>}
      </footer>
    </div>
  )
}
