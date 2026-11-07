// Dev harness: renders the view as a host would, with a chosen host theme, display mode and container size.
// URL: ?host=claude-light&mode=inline&w=440   (hosts in hosts.ts; mode inline|fullscreen|pip; w/h in px)
import { createRoot } from 'react-dom/client'
import { useState } from 'react'
import { HOSTS } from './hosts'
import { StaticHostProvider, type DisplayMode } from './host'
import { View } from './View'
import './tokens.css'

function Harness() {
  const q = new URLSearchParams(location.search)
  const host = HOSTS[q.get('host') ?? 'claude-light'] ?? HOSTS['claude-light']
  const [mode, setMode] = useState<DisplayMode>((q.get('mode') as DisplayMode) ?? 'inline')
  const w = mode === 'inline' ? Number(q.get('w') ?? 680) : mode === 'pip' ? Number(q.get('w') ?? 360) : innerWidth
  const h = mode === 'fullscreen' ? innerHeight : mode === 'pip' ? Number(q.get('h') ?? 220) : undefined
  const context = {
    theme: host.theme, styles: { variables: host.variables }, displayMode: mode,
    availableDisplayModes: q.get('nofs') ? ['inline'] : ['inline', 'fullscreen', 'pip'],
    containerDimensions: h ? { width: w, height: h } : { width: w, maxHeight: 900 },
    platform: (q.get('platform') as 'web' | 'desktop' | 'mobile') ?? 'web',
    deviceCapabilities: { touch: q.get('touch') === '1', hover: q.get('touch') !== '1' },
  }
  // The page around the view stands in for the host's conversation surface.
  document.body.style.background = host.variables['--color-background-primary'] ?? (host.theme === 'dark' ? '#1f1f1f' : '#fff')
  return (
    <div style={{ padding: mode === 'inline' ? 24 : 0 }}>
      <div style={{ width: w, height: h, margin: mode === 'pip' ? 24 : 0, overflow: 'hidden', borderRadius: mode === 'inline' ? 12 : 0, boxShadow: mode === 'fullscreen' ? 'none' : '0 0 0 1px var(--border)' }}>
        <StaticHostProvider context={context as never} onMode={setMode}><View /></StaticHostProvider>
      </div>
    </div>
  )
}
createRoot(document.getElementById('root')!).render(<Harness />)
