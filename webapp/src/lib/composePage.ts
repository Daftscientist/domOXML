// JS replica of domoxml.core.render.page.compose_page with the default
// Theme, so iframe previews show exactly the document the Python export
// path renders. Keep in sync with page.py: framework reset, :root
// theme tokens (Palette/Fonts defaults from domoxml.types), the fixed-size
// frame, then the deck stylesheet in its own <style> element.

const RESET = "*{margin:0;padding:0;box-sizing:border-box}";
const THEME =
  ":root{--background:#ffffff;--foreground:#0b0b0c;--accent:#4f46e5;" +
  "--muted:#6b7280;--font-heading:Inter;--font-body:Inter}";

export function composePage(html: string, opts: { width: number; height: number; css?: string }): string {
  const { width, height, css } = opts;
  const frame =
    `html,body{width:${width}px;height:${height}px;overflow:hidden;` +
    "background:var(--background);color:var(--foreground);" +
    "font-family:var(--font-body),sans-serif}";
  const framework = `${RESET}${THEME}${frame}`;
  const userStyle = css ? `<style>${css}</style>` : "";
  return (
    '<!doctype html><html><head><meta charset="utf-8">' +
    `<style>${framework}</style>${userStyle}</head><body>${html}</body></html>`
  );
}
