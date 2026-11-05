// DOM-path addressing and mutation for slide fragments.
//
// A path is a chain of element-child indices from the composed page's
// <body>: body is [], the fragment's top-level elements are [0], [1],
// and so on. The snapshot walk uses the same root, so paths from the
// derived IR, paths computed in the live preview document, and paths
// resolved against a parsed fragment all name the same element.
//
// Mutations are applied to a parsed copy of the fragment and the result
// is serialised back to HTML: the fragment stays the document model,
// and a visual edit is just another HTML edit (the previews morph, the
// autosave stores it, the export derives from it).

export type SlideMutation =
  | {
      type: "box";
      /** New CSS left/top in px; only the given fields are written. */
      left?: number;
      top?: number;
      width?: number;
      height?: number;
      /** Promote a static element to absolute positioning. */
      lift?: boolean;
    }
  | { type: "text"; text: string }
  | { type: "remove" };

export function resolvePath(scope: ParentNode, path: number[]): Element | null {
  let node: Element | null = null;
  let current: ParentNode = scope;
  for (const index of path) {
    const children = current.children;
    if (!children || index < 0 || index >= children.length) return null;
    node = children[index];
    current = node;
  }
  return node;
}

/** The path of an element in a live document, from its <body>. */
export function pathOf(el: Element): number[] | null {
  const path: number[] = [];
  let current: Element | null = el;
  while (current && current.tagName !== "BODY") {
    const parent: Element | null = current.parentElement;
    if (!parent) return null;
    path.unshift(Array.prototype.indexOf.call(parent.children, current));
    current = parent;
  }
  return current ? path : null;
}

const px = (v: number) => `${Math.round(v * 10) / 10}px`;

/**
 * Apply one mutation to the fragment element at `path`; returns the new
 * fragment, or null when the path does not resolve (the caller keeps the
 * old fragment in that case).
 */
export function mutateFragment(
  html: string,
  path: number[],
  mutation: SlideMutation,
): string | null {
  const template = document.createElement("template");
  template.innerHTML = html;
  const target = resolvePath(template.content, path);
  if (!target) return null;
  const el = target as HTMLElement;
  if (mutation.type === "remove") {
    el.remove();
  } else if (mutation.type === "text") {
    el.textContent = mutation.text;
  } else {
    const style = el.style;
    if (mutation.lift) style.position = "absolute";
    if (mutation.left !== undefined) {
      style.left = px(mutation.left);
      if (style.right) style.right = "auto";
    }
    if (mutation.top !== undefined) {
      style.top = px(mutation.top);
      if (style.bottom) style.bottom = "auto";
    }
    if (mutation.width !== undefined) style.width = px(mutation.width);
    if (mutation.height !== undefined) style.height = px(mutation.height);
  }
  return template.innerHTML;
}
