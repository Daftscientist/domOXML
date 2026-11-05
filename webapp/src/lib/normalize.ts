// Detecting the normalised domOXML form.
//
// A normalised slide is the canonical fragment the serialiser emits
// (and the .pptx read path returns): one root element carrying the
// domoxml-slide class, every visual element absolutely positioned with
// inline styles and data-domoxml provenance, no stylesheets, scripts
// or class-driven styling. Such a fragment parses straight back to IR
// with no browser involved.
//
// Anything else — hand-authored HTML with flow layout, classes, deck
// CSS dependencies — is "foreign": it only means something once a
// browser has laid it out. The check is deliberately strict: a false
// negative costs one idempotent normalisation pass, while a false
// positive would leave foreign HTML claiming to be importable as-is.
export function isNormalisedFragment(html: string): boolean {
  if (!html.includes("domoxml-slide")) return false;
  const template = document.createElement("template");
  template.innerHTML = html;
  const roots = Array.from(template.content.children);
  if (roots.length !== 1) return false;
  const root = roots[0];
  if (!root.classList.contains("domoxml-slide")) return false;
  if (template.content.querySelector("style, script, link")) return false;
  return true;
}

/** Foreign = has real element content but is not the normalised form. */
export function isForeignFragment(html: string): boolean {
  if (!html.trim()) return false;
  if (isNormalisedFragment(html)) return false;
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content.querySelector("*") !== null;
}
