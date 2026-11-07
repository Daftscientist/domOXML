// PROTOTYPE — A, "Paper": the deck is a physical object. The slide is a sheet of paper lying on a stack (the next
// pages peek out under it), on an ambient backdrop tinted by the slide's own colour. Tools are glass, floating, and
// only appear when there's something to do. Chrome takes the host's text, ring and font; the atmosphere comes from the
// document itself.
import { useState } from 'react'
import { useHost } from '../host'
import { Icon } from '../icons'
import { SAMPLE } from '../sample'
import { SlideCanvas } from '../SlideCanvas'
import { slideColour, slideTitle } from './shared'
import './proto.css'

export function VariantA({ width, working, initialSlide, initialSelection }: { width: number; working: boolean; initialSlide: number; initialSelection: string[] }) {
  const host = useHost()
  const deck = SAMPLE
  const [i, setI] = useState(initialSlide)
  const [sel, setSel] = useState<string[]>(initialSelection)
  const s = deck.slides[i]
  const wide = width >= 1024
  const narrow = width < 520
  const tint = slideColour(s)
  const slideW = wide ? Math.min(width - 420, 1000) : width - (narrow ? 44 : 72)
  const go = (n: number) => { setI(Math.max(0, Math.min(deck.slides.length - 1, n))); setSel([]) }

  return (
    <div className="pa" data-wide={wide || undefined} style={{ ['--tint' as string]: tint }}>
      <div className="pa-ambient" aria-hidden />
      <header className="pa-top">
        <span className="pa-file glass"><Icon name="deck" /><b>{deck.name.replace('.pptx', '')}</b><i className={working ? 'pa-dot live' : 'pa-dot'} /></span>
        <span className="pa-actions glass">
          <button aria-label="Comments"><Icon name="comment" /><em>3</em></button>
          <button aria-label="Present"><Icon name="play" /></button>
          <button aria-label="Download"><Icon name="download" /></button>
          {host.modes.includes('fullscreen') && <button aria-label={host.mode === 'fullscreen' ? 'Back to chat' : 'Open full view'} onClick={() => host.requestMode(host.mode === 'fullscreen' ? 'inline' : 'fullscreen')}><Icon name={host.mode === 'fullscreen' ? 'collapse' : 'expand'} /></button>}
        </span>
      </header>

      <div className="pa-body">
        {wide && (
          <nav className="pa-pile" aria-label="Slides">
            {deck.slides.map((x, k) => (
              <button key={x.id} className="pa-sheet" aria-current={k === i || undefined} onClick={() => go(k)} style={{ ['--r' as string]: `${((k * 37) % 5) - 2}deg` }}>
                <SlideCanvas html={x.html} width={150} selection={[]} changed={[]} interactive={false} label={`Slide ${k + 1}`} />
                <span>{k + 1}</span>
              </button>
            ))}
          </nav>
        )}

        <main className="pa-desk">
          {sel.length > 0 && !narrow && (
            <div className="pa-float glass" role="toolbar" aria-label="Format">
              <span className="pa-what">Text</span>
              <button className="b">B</button><button className="i">I</button><button className="u">U</button>
              <button className="pa-size">56</button>
              <button aria-label="Colour"><i className="pa-swatch" /></button>
              <span className="pa-gap" />
              <button className="pa-ask"><Icon name="sparkle" />Ask</button>
            </div>
          )}
          <div className="pa-stack" style={{ width: slideW }}>
            <i className="pa-under two" /><i className="pa-under one" />
            <div className="pa-paper" data-working={working || undefined}>
              <SlideCanvas html={s.html} width={slideW} selection={sel} changed={working ? ['e6', 'e7'] : []} interactive onSelect={(ids) => setSel(ids)} label={`Slide ${i + 1}`} />
            </div>
            {working && <span className="pa-whisper glass"><Icon name="sparkle" />Assistant is rewriting the headline</span>}
          </div>

          <div className="pa-dock glass">
            <button aria-label="Previous slide" onClick={() => go(i - 1)}><Icon name="left" /></button>
            {!wide && (
              <span className="pa-dots" aria-hidden>
                {deck.slides.map((x, k) => <i key={x.id} data-on={k === i || undefined} data-hidden={x.hidden || undefined} onClick={() => go(k)} />)}
              </span>
            )}
            <span className="pa-count">{wide ? slideTitle(s, i) : `${i + 1} of ${deck.slides.length}`}</span>
            <button aria-label="Next slide" onClick={() => go(i + 1)}><Icon name="right" /></button>
            {!narrow && <><span className="pa-sep" /><button aria-label="Add slide"><Icon name="plus" /></button></>}
          </div>
        </main>

        {wide && (
          <aside className="pa-notes" aria-label="Comments and notes">
            <article className="pa-note">
              <p className="pa-by">You · on “+18%”</p>
              <p>Can we check this against the board pack figure?</p>
              <p className="pa-reply"><b>Assistant</b> The board pack says 17.6%, rounded to 18%. Show one decimal?</p>
            </article>
            <article className="pa-note yellow">
              <p className="pa-by">Speaker notes</p>
              <p>{deck.slides[i].notes ?? 'Nothing yet. Click to write what you’ll say.'}</p>
            </article>
          </aside>
        )}
      </div>
    </div>
  )
}
