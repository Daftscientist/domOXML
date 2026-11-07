// One slide, rendered as the document it is (its own colours, never themed), scaled to fit, inside a shadow root so its
// styles can't leak into the view's chrome (and the view's can't leak in). Selection frames and the assistant's change
// highlights are drawn in an overlay above it, in slide coordinates.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export const SLIDE_W = 1280, SLIDE_H = 720

type Box = { id: string; x: number; y: number; w: number; h: number }

export function SlideCanvas({ html, width, selection, changed, interactive, onSelect, label }: {
  html: string
  width: number
  selection: string[]
  /** Element ids the assistant just changed (briefly outlined). */
  changed: string[]
  interactive: boolean
  onSelect?: (ids: string[], additive: boolean) => void
  label: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const [boxes, setBoxes] = useState<Box[]>([])
  const scale = width / SLIDE_W

  useLayoutEffect(() => {
    const el = host.current
    if (!el) return
    const root = el.shadowRoot ?? el.attachShadow({ mode: 'open' })
    root.innerHTML = `<style>:host{all:initial;display:block}*{box-sizing:border-box}</style>${html}`
    // Element boxes in slide coordinates (for the overlay).
    const out: Box[] = []
    root.querySelectorAll<HTMLElement>('[data-id]').forEach((n) => {
      out.push({ id: n.dataset.id!, x: n.offsetLeft, y: n.offsetTop, w: n.offsetWidth, h: n.offsetHeight })
    })
    setBoxes(out)
  }, [html])

  useEffect(() => {
    const el = host.current
    if (!el?.shadowRoot || !interactive) return
    const root = el.shadowRoot
    const click = (e: Event) => {
      const t = (e.composedPath()[0] as HTMLElement | undefined)?.closest?.('[data-id]') as HTMLElement | null
      onSelect?.(t ? [t.dataset.id!] : [], (e as MouseEvent).shiftKey)
    }
    root.addEventListener('click', click)
    return () => root.removeEventListener('click', click)
  }, [interactive, onSelect, html])

  return (
    <div className="slide" style={{ width, height: SLIDE_H * scale }} role="img" aria-label={label}>
      <div ref={host} style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${scale})`, transformOrigin: '0 0' }} />
      <div className="slide-overlay" style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${scale})` }} aria-hidden>
        {boxes.filter((b) => changed.includes(b.id)).map((b) => <div key={`c${b.id}`} className="changed" style={{ left: b.x, top: b.y, width: b.w, height: b.h }} />)}
        {boxes.filter((b) => selection.includes(b.id)).map((b) => (
          <div key={b.id} className="frame" style={{ left: b.x, top: b.y, width: b.w, height: b.h, ['--inv' as string]: 1 / scale }}>
            {interactive && ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].map((h) => <i key={h} className={`handle ${h}`} />)}
          </div>
        ))}
      </div>
    </div>
  )
}
