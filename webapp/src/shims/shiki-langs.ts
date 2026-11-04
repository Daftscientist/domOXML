// @pierre/diffs resolves languages through `import("shiki/langs")`, whose
// registry lazy-loads every Shiki grammar (250+ chunks, ~9 MB). This app
// only ever highlights HTML and CSS (plus JavaScript embedded in HTML), so
// Vite aliases `shiki/langs` to this trimmed registry.
const html = () => import("../../node_modules/shiki/dist/langs/html.mjs");
const css = () => import("../../node_modules/shiki/dist/langs/css.mjs");
const javascript = () => import("../../node_modules/shiki/dist/langs/javascript.mjs");

export const bundledLanguages = { html, css, javascript };
