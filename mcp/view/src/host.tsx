// The view's connection to its host. In a real MCP host it uses the ext-apps App (handshake, theme, size reports,
// display modes). In the dev harness it takes a host context from the URL, so every theme × mode × size can be shown.
import { App, applyDocumentTheme, applyHostFonts, applyHostStyleVariables, type McpUiHostContext } from '@modelcontextprotocol/ext-apps'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type DisplayMode = 'inline' | 'fullscreen' | 'pip'
export type Host = {
  context: McpUiHostContext
  mode: DisplayMode
  /** Modes the host offers (Expand shows only when fullscreen is among them). */
  modes: DisplayMode[]
  requestMode: (m: DisplayMode) => void
  app: App | null
}

const Ctx = createContext<Host | null>(null)
export const useHost = () => { const h = useContext(Ctx); if (!h) throw new Error('useHost outside HostProvider'); return h }

function applyContext(ctx: McpUiHostContext) {
  if (ctx.theme) applyDocumentTheme(ctx.theme)
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables)
  if (ctx.styles?.css?.fonts) applyHostFonts(ctx.styles.css.fonts)
}

/** Real host: connect, apply theme and styles, follow changes. */
export function HostProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ app: App; context: McpUiHostContext } | null>(null)
  useEffect(() => {
    const app = new App({ name: 'domOXML', version: '0.0.0' }, {}, { autoResize: true })
    app.onhostcontextchanged = (change) => setState((s) => {
      const context = { ...(s?.context ?? {}), ...change } as McpUiHostContext
      applyContext(context)
      return { app, context }
    })
    void app.connect().then(() => { const context = app.getHostContext() ?? {}; applyContext(context); setState({ app, context }) })
    return () => { void app.close() }
  }, [])
  if (!state) return null
  const { app, context } = state
  const host: Host = {
    app, context,
    mode: (context.displayMode as DisplayMode) ?? 'inline',
    modes: ((context.availableDisplayModes as DisplayMode[] | undefined) ?? ['inline']),
    requestMode: (m) => { void app.requestDisplayMode({ mode: m }) },
  }
  return <Ctx.Provider value={host}>{children}</Ctx.Provider>
}

/** Dev harness: a fixed context. */
export function StaticHostProvider({ context, onMode, children }: { context: McpUiHostContext; onMode: (m: DisplayMode) => void; children: ReactNode }) {
  useEffect(() => { applyContext(context) }, [context])
  const host: Host = {
    app: null, context,
    mode: (context.displayMode as DisplayMode) ?? 'inline',
    modes: (context.availableDisplayModes as DisplayMode[] | undefined) ?? ['inline', 'fullscreen'],
    requestMode: onMode,
  }
  return <Ctx.Provider value={host}>{children}</Ctx.Provider>
}
