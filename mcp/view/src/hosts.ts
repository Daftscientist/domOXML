// Sample host contexts for the dev harness: approximations of how real clients theme an MCP App (the standard
// McpUiStyleVariableKey names). Real hosts send their own values; these only exist to design and screenshot against.
import type { McpUiHostContext } from '@modelcontextprotocol/ext-apps'

type Vars = NonNullable<NonNullable<McpUiHostContext['styles']>['variables']>
const base = (v: Partial<Record<string, string>>): Vars => v as Vars

export const HOSTS: Record<string, { label: string; theme: 'light' | 'dark'; variables: Vars }> = {
  'claude-light': { label: 'Claude-like, light', theme: 'light', variables: base({
    '--color-background-primary': '#faf9f5', '--color-background-secondary': '#f0eee6', '--color-background-tertiary': '#e8e6dc',
    '--color-text-primary': '#141413', '--color-text-secondary': '#5e5d59', '--color-text-tertiary': '#87867f',
    '--color-border-primary': 'rgba(31,30,29,0.15)', '--color-border-secondary': 'rgba(31,30,29,0.08)',
    '--color-ring-primary': '#2c84db', '--color-text-info': '#2c84db', '--color-border-info': '#2c84db', '--color-background-info': '#e6f0fb',
    '--font-sans': 'ui-sans-serif, system-ui, sans-serif', '--border-radius-sm': '6px', '--border-radius-md': '8px', '--border-radius-lg': '12px',
  }) },
  'claude-dark': { label: 'Claude-like, dark', theme: 'dark', variables: base({
    '--color-background-primary': '#262624', '--color-background-secondary': '#1f1e1d', '--color-background-tertiary': '#191918',
    '--color-text-primary': '#faf9f5', '--color-text-secondary': '#c2c0b6', '--color-text-tertiary': '#9c9a92',
    '--color-border-primary': 'rgba(222,220,209,0.15)', '--color-border-secondary': 'rgba(222,220,209,0.08)',
    '--color-ring-primary': '#5aa5f0', '--color-text-info': '#7cb8f2', '--color-border-info': '#5aa5f0', '--color-background-info': '#1d2a38',
    '--font-sans': 'ui-sans-serif, system-ui, sans-serif', '--border-radius-sm': '6px', '--border-radius-md': '8px', '--border-radius-lg': '12px',
  }) },
  'chatgpt-light': { label: 'ChatGPT-like, light', theme: 'light', variables: base({
    '--color-background-primary': '#ffffff', '--color-background-secondary': '#f9f9f9', '--color-background-tertiary': '#ececec',
    '--color-text-primary': '#0d0d0d', '--color-text-secondary': '#5d5d5d', '--color-text-tertiary': '#8f8f8f',
    '--color-border-primary': 'rgba(13,13,13,0.15)', '--color-border-secondary': 'rgba(13,13,13,0.05)',
    '--color-ring-primary': '#0285ff', '--color-text-info': '#0285ff', '--color-border-info': '#0285ff', '--color-background-info': '#e5f3ff',
    '--font-sans': 'ui-sans-serif, -apple-system, system-ui, "Segoe UI", sans-serif', '--border-radius-sm': '8px', '--border-radius-md': '12px', '--border-radius-lg': '16px',
  }) },
  'vscode-dark': { label: 'VS Code-like, dark', theme: 'dark', variables: base({
    '--color-background-primary': '#1f1f1f', '--color-background-secondary': '#181818', '--color-background-tertiary': '#141414',
    '--color-text-primary': '#cccccc', '--color-text-secondary': '#9d9d9d', '--color-text-tertiary': '#767676',
    '--color-border-primary': '#3c3c3c', '--color-border-secondary': '#2b2b2b',
    '--color-ring-primary': '#0078d4', '--color-text-info': '#4daafc', '--color-border-info': '#0078d4', '--color-background-info': '#0d2a42',
    '--font-sans': '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif', '--border-radius-sm': '2px', '--border-radius-md': '4px', '--border-radius-lg': '6px',
  }) },
  'none': { label: 'No host variables (fallbacks)', theme: 'light', variables: base({}) },
}
