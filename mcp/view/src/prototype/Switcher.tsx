// PROTOTYPE switcher (dev only): ← / → or the arrows cycle variants; the URL keeps ?variant= so it's shareable.
import { useEffect } from 'react'

const NAMES: Record<string, string> = { '': 'First pass', A: 'A — Paper', B: 'B — Stage', C: 'C — Canvas' }
const ORDER = ['A', 'B', 'C', '']

export function Switcher({ current }: { current: string }) {
  const go = (d: number) => {
    const i = (ORDER.indexOf(current) + d + ORDER.length) % ORDER.length
    const q = new URLSearchParams(location.search)
    if (ORDER[i]) q.set('variant', ORDER[i]); else q.delete('variant')
    location.search = q.toString()
  }
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, [contenteditable]')) return
      if (e.key === 'ArrowLeft' && e.altKey) go(-1)
      if (e.key === 'ArrowRight' && e.altKey) go(1)
    }
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  })
  return (
    <div style={{ position: 'fixed', left: '50%', bottom: 14, transform: 'translateX(-50%)', zIndex: 9999, display: 'flex', alignItems: 'center', gap: 4, padding: 4, borderRadius: 999, background: '#111', color: '#fff', font: '600 12px system-ui', boxShadow: '0 6px 24px rgba(0,0,0,.35)' }}>
      <button onClick={() => go(-1)} style={{ color: '#fff', width: 28, height: 28, borderRadius: 999 }} aria-label="Previous variant">←</button>
      <span style={{ padding: '0 8px', minWidth: 110, textAlign: 'center' }}>{NAMES[current] ?? current} <span style={{ opacity: .5 }}>⌥←/→</span></span>
      <button onClick={() => go(1)} style={{ color: '#fff', width: 28, height: 28, borderRadius: 999 }} aria-label="Next variant">→</button>
    </div>
  )
}
