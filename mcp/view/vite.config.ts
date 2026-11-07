import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// The view ships as one self-contained HTML file (the MCP Apps ui:// resource). `dev.html` is a harness that renders
// the view with any host context (theme, variables, display mode, size) for design work and screenshots.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  server: { host: '127.0.0.1', port: 5199, strictPort: true, allowedHosts: ['leovm.tail53f5e9.ts.net', 'localhost'] },
  build: { outDir: 'dist', rollupOptions: { input: 'mcp-app.html' } },
})
