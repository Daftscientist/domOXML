"""Headless-Chromium rendering via Playwright: rasterise a page and capture its layout."""

from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Callable, Collection
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

from playwright.async_api import Browser, Page, Playwright, Route, async_playwright
from pydantic import BaseModel, ConfigDict, Field

from domoxml.core.images import apply_alpha_mask, crop_png
from domoxml.core.ir.parse import parse_shadows
from domoxml.core.units import emu_to_px

# Walks the rendered DOM and, per element, captures its box, direct text, ordered inline
# text runs, the computed styles the extractor needs, and enough structure (index/parent)
# to let the extractor rasterise an element together with its subtree. This is the raw material.
_SNAPSHOT_JS = """
() => {
  const pick = (cs) => ({
    color: cs.color, backgroundColor: cs.backgroundColor, backgroundImage: cs.backgroundImage,
    backgroundSize: cs.backgroundSize, backgroundPosition: cs.backgroundPosition,
    backgroundRepeat: cs.backgroundRepeat, backgroundBlendMode: cs.backgroundBlendMode,
    backgroundOrigin: cs.backgroundOrigin, backgroundClip: cs.backgroundClip,
    fontSize: cs.fontSize, fontFamily: cs.fontFamily,
    fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
    textDecorationLine: cs.textDecorationLine, textTransform: cs.textTransform,
    fontVariantCaps: cs.fontVariantCaps, letterSpacing: cs.letterSpacing,
    textAlign: cs.textAlign, lineHeight: cs.lineHeight,
    borderRadius: cs.borderRadius, opacity: cs.opacity,
    boxShadow: cs.boxShadow, filter: cs.filter, webkitBoxReflect: cs.webkitBoxReflect,
    maskImage: cs.maskImage, maskComposite: cs.maskComposite,
    maskRepeat: cs.maskRepeat, maskPosition: cs.maskPosition, maskSize: cs.maskSize,
    maskOrigin: cs.maskOrigin, maskClip: cs.maskClip, maskMode: cs.maskMode,
    mixBlendMode: cs.mixBlendMode, backdropFilter: cs.backdropFilter,
    clipPath: cs.clipPath, transform: cs.transform, transformOrigin: cs.transformOrigin,
    borderTopWidth: cs.borderTopWidth, borderTopStyle: cs.borderTopStyle,
    borderTopColor: cs.borderTopColor,
    borderRightWidth: cs.borderRightWidth, borderRightStyle: cs.borderRightStyle,
    borderRightColor: cs.borderRightColor,
    borderBottomWidth: cs.borderBottomWidth, borderBottomStyle: cs.borderBottomStyle,
    borderBottomColor: cs.borderBottomColor,
    borderLeftWidth: cs.borderLeftWidth, borderLeftStyle: cs.borderLeftStyle,
    borderLeftColor: cs.borderLeftColor,
    display: cs.display, flexDirection: cs.flexDirection,
    justifyContent: cs.justifyContent, alignItems: cs.alignItems,
    overflow: cs.overflow, whiteSpace: cs.whiteSpace,
    columnCount: cs.columnCount, columnGap: cs.columnGap, columnFill: cs.columnFill,
    marginTop: cs.marginTop, marginBottom: cs.marginBottom,
    textIndent: cs.textIndent, paddingLeft: cs.paddingLeft, paddingTop: cs.paddingTop,
    paddingRight: cs.paddingRight, paddingBottom: cs.paddingBottom,
    listStyleType: cs.listStyleType, listStylePosition: cs.listStylePosition,
    objectFit: cs.objectFit, objectPosition: cs.objectPosition,
    fill: cs.fill, stroke: cs.stroke, strokeWidth: cs.strokeWidth,
    strokeDasharray: cs.strokeDasharray, strokeLinecap: cs.strokeLinecap,
    strokeLinejoin: cs.strokeLinejoin,
  });
  // The nearest enclosing <a href> for the run, captured as a synthetic style key so the
  // extractor can recover a:hlinkClick without a separate channel. textContent (not innerText)
  // keeps the run text raw, so text-transform stays a cap attr rather than baked-in glyphs.
  const linkHref = (el) => {
    const anchor = el.closest && el.closest('a[href]');
    return anchor ? anchor.getAttribute('href') : '';
  };
  // Count nesting depth and list type for <li> elements.
  const listContext = (el) => {
    let depth = 0;
    let listType = '';
    let ordinal = null;
    let node = el.parentElement;
    while (node) {
      const tag = node.tagName && node.tagName.toLowerCase();
      if (tag === 'ul' || tag === 'ol') {
        depth++;
        if (!listType) listType = getComputedStyle(node).listStyleType;
        if (tag === 'ol' && !listType) listType = 'decimal';
        if (tag === 'ul' && !listType) listType = 'disc';
        if (depth === 1 && tag === 'ol') {
          const items = Array.from(node.children).filter(
            (child) => child.tagName && child.tagName.toLowerCase() === 'li'
          );
          const step = node.reversed ? -1 : 1;
          let value = node.hasAttribute('start')
            ? node.start
            : (node.reversed ? items.length : 1);
          for (const item of items) {
            if (item.hasAttribute('value')) value = item.value;
            if (item === el) {
              ordinal = value;
              break;
            }
            value += step;
          }
        }
      }
      node = node.parentElement;
    }
    return { depth, listType, ordinal };
  };
  const consolidatesText = (root) => {
    if (root.getAttribute('data-domoxml-text-body') === 'true') return true;
    const style = getComputedStyle(root);
    const display = style.display;
    if (display !== 'flex' && display !== 'inline-flex') return false;
    if (!style.flexDirection.startsWith('column')) return false;
    const elements = Array.from(root.children);
    return elements.length > 0 && elements.every((child) => child.children.length === 0);
  };
  const inlineRuns = (root, consolidateFlex) => {
    const runs = [];
    const collect = (node, inherited, href, allowBlock = false) => {
      if (node.nodeType === 3) {
        let text = node.textContent || '';
        if (inherited.whiteSpace === 'normal' || inherited.whiteSpace === 'nowrap') {
          text = text.replace(/\\s+/g, ' ');
        }
        if (text) {
          const styles = pick(inherited);
          if (href) styles.domoxmlHref = href;
          runs.push({ text, styles });
        }
        return;
      }
      if (node.nodeType !== 1) return;
      const el = node;
      if (el.tagName.toLowerCase() === 'br') {
        const styles = pick(inherited);
        if (href) styles.domoxmlHref = href;
        runs.push({ text: '\\n', styles });
        return;
      }
      const cs = getComputedStyle(el);
      if (!allowBlock && !cs.display.startsWith('inline')) return;
      const childHref = el.tagName.toLowerCase() === 'a' && el.getAttribute('href')
        ? el.getAttribute('href') : href;
      for (const child of el.childNodes) collect(child, cs, childHref);
    };
    const rootStyle = getComputedStyle(root);
    const rootHref = linkHref(root);
    for (const child of root.childNodes) {
      if (consolidateFlex && child.nodeType === 3 && !child.textContent.trim()) continue;
      const before = runs.length;
      collect(child, rootStyle, rootHref, consolidateFlex && child.nodeType === 1);
      if (consolidateFlex && runs.slice(before).some((run) => run.text.trim())) {
        runs.push({ text: '\\n', styles: pick(rootStyle) });
      }
    }
    if (consolidateFlex && runs.at(-1)?.text === '\\n') runs.pop();
    return runs.some((run) => run.text.trim()) ? runs : [];
  };
  const out = [];
  // What the browser clips a descendant to. PowerPoint never clips one shape to another, so a
  // descendant that pokes out of an ancestor's `overflow` box is flagged for an isolated raster.
  const walked = new Map();
  const clipCache = new Map();
  const viewport = [
    { x: 0, y: 0 },
    { x: document.documentElement.clientWidth, y: document.documentElement.clientHeight },
  ];
  const cornersOf = (rect, linear, el) => {
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    const rotated = linear && (Math.abs(linear.b) > 1e-6 || Math.abs(linear.c) > 1e-6);
    if (rotated && el instanceof HTMLElement) {
      const hw = el.offsetWidth / 2;
      const hh = el.offsetHeight / 2;
      return [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]].map(([x, y]) => {
        const point = linear.transformPoint({ x, y });
        return { x: cx + point.x, y: cy + point.y };
      });
    }
    return [
      { x: rect.x, y: rect.y }, { x: rect.right, y: rect.y },
      { x: rect.right, y: rect.bottom }, { x: rect.x, y: rect.bottom },
    ];
  };
  const outsideClip = (region, point) => {
    const local = region.inverse.transformPoint({
      x: point.x - region.centre.x, y: point.y - region.centre.y,
    });
    const x = Math.abs(local.x - region.shift.x);
    const y = Math.abs(local.y - region.shift.y);
    const tolerance = 1;
    if (region.clipX && x > region.half.x + tolerance) return true;
    if (region.clipY && y > region.half.y + tolerance) return true;
    const r = region.radius;
    if (r > 0 && region.clipX && region.clipY && x > region.half.x - r && y > region.half.y - r) {
      const dx = x - (region.half.x - r);
      const dy = y - (region.half.y - r);
      return dx * dx + dy * dy > (r + tolerance) * (r + tolerance);
    }
    return false;
  };
  // The padding box an element clips its descendants to, in its own (possibly rotated) frame.
  const clipRegion = (ancestor) => {
    if (clipCache.has(ancestor)) return clipCache.get(ancestor);
    let region = null;
    const record = walked.get(ancestor);
    if (record && ancestor instanceof HTMLElement && ancestor.offsetWidth > 0
        && ancestor.offsetHeight > 0) {
      const cs = record.computed;
      const clipX = cs.overflowX !== 'visible';
      const clipY = cs.overflowY !== 'visible';
      if (clipX || clipY) {
        const bl = parseFloat(cs.borderLeftWidth) || 0;
        const br = parseFloat(cs.borderRightWidth) || 0;
        const bt = parseFloat(cs.borderTopWidth) || 0;
        const bb = parseFloat(cs.borderBottomWidth) || 0;
        const radii = [
          cs.borderTopLeftRadius, cs.borderTopRightRadius,
          cs.borderBottomRightRadius, cs.borderBottomLeftRadius,
        ].map((value) => {
          const first = value.split(' ')[0];
          return first.endsWith('%')
            ? (parseFloat(first) / 100) * ancestor.offsetWidth : parseFloat(first) || 0;
        });
        // CSS Backgrounds 3.4: one factor shrinks every radius until each side fits the border
        // box. getComputedStyle reports the authored value, so `9999px` arrives unscaled.
        const [tl, tr, brr, blr] = radii;
        const fit = Math.min(
          1,
          ancestor.offsetWidth / Math.max(tl + tr, blr + brr),
          ancestor.offsetHeight / Math.max(tl + blr, tr + brr),
        );
        const inverse = (record.linear || new DOMMatrix()).inverse();
        if ([inverse.a, inverse.b, inverse.c, inverse.d].every(Number.isFinite)) {
          region = {
            centre: {
              x: record.rect.x + record.rect.width / 2,
              y: record.rect.y + record.rect.height / 2,
            },
            inverse,
            half: {
              x: (ancestor.offsetWidth - bl - br) / 2,
              y: (ancestor.offsetHeight - bt - bb) / 2,
            },
            shift: { x: (bl - br) / 2, y: (bt - bb) / 2 },
            clipX,
            clipY,
            radius: Math.max(0, Math.max(...radii) * fit - Math.max(bl, br, bt, bb)),
          };
          // A clip that already covers the whole slide is just the slide edge.
          region.coversSlide = viewport.every((point) => !outsideClip(region, point));
        }
      }
    }
    clipCache.set(ancestor, region);
    return region;
  };
  // The element an absolutely positioned `el` is laid out against: the nearest ancestor that is
  // positioned or establishes a containing block (transform, perspective, filter). `offsetParent`
  // is not used because inline <svg> elements do not have it.
  const containingBlockOf = (el) => {
    let ancestor = el.parentElement;
    while (ancestor && ancestor !== document.body && ancestor !== document.documentElement) {
      const cs = getComputedStyle(ancestor);
      if (cs.position !== 'static' || cs.transform !== 'none' || cs.perspective !== 'none'
          || cs.filter !== 'none') {
        return ancestor;
      }
      ancestor = ancestor.parentElement;
    }
    return document.body;
  };
  // Overflow clips a descendant only along its containing-block chain, so an absolutely
  // positioned child escapes the clips of unpositioned ancestors between it and its container.
  const clippersOf = (el) => {
    const found = [];
    let current = el;
    while (current && current !== document.documentElement) {
      const position = getComputedStyle(current).position;
      if (position === 'fixed') break;
      const next = position === 'absolute' ? containingBlockOf(current) : current.parentElement;
      if (!next || next === document.documentElement) break;
      found.push(next);
      current = next;
    }
    return found;
  };
  // The linear part of every ancestor transform composed together. Shapes on a slide are all
  // positioned absolutely, so a descendant must carry the rotation/flip it is drawn with even
  // though its own computed transform is `none`.
  const walk = (el, parent, inheritedLinear) => {
    if (el.getAttribute('data-domoxml-render-layer') === 'true') return;
    const r = el.getBoundingClientRect();
    const text = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join('').trim();
    const index = out.length;
    el.dataset.domoxmlCaptureIndex = String(index);
    const computed = getComputedStyle(el);
    const styles = pick(computed);
    const tag = el.tagName.toLowerCase();
    if (el.hasAttribute('data-domoxml-group')) {
      styles.domoxmlGroupWrapperLeft = computed.left;
      styles.domoxmlGroupWrapperTop = computed.top;
      styles.domoxmlGroupWrapperWidth = computed.width;
      styles.domoxmlGroupWrapperHeight = computed.height;
    }
    if (el.parentElement && el.parentElement.hasAttribute('data-domoxml-group')) {
      // Normalized group metadata may restore pre-flattening member geometry only while
      // the visible CSS projection is unchanged. Capture local layout values before any
      // ancestor transform so extraction can reject stale metadata after an HTML edit.
      styles.domoxmlGroupLayoutLeft = computed.left;
      styles.domoxmlGroupLayoutTop = computed.top;
      styles.domoxmlGroupLayoutWidth = computed.width;
      styles.domoxmlGroupLayoutHeight = computed.height;
    }
    if (tag === 'path' || tag === 'svg') {
      const filterRef = el.getAttribute('filter') || el.style.filter || styles.filter || '';
      const filterMatch = filterRef.match(/^url\\(\\s*['"]?#([^'")]+)['"]?\\s*\\)$/i);
      const svgRoot = tag === 'svg' ? el : el.ownerSVGElement;
      if (filterMatch && svgRoot) {
        const filterNode = Array.from(svgRoot.querySelectorAll('filter'))
          .find((candidate) => candidate.id === filterMatch[1]);
        if (filterNode) {
          const cleanFilter = filterNode.cloneNode(true);
          cleanFilter.removeAttribute('data-domoxml-capture-index');
          for (const child of cleanFilter.querySelectorAll('[data-domoxml-capture-index]')) {
            child.removeAttribute('data-domoxml-capture-index');
          }
          styles.domoxmlSvgFilter = cleanFilter.outerHTML;
        }
      }
    }
    let effectiveLinear = inheritedLinear;
    if (computed.transform && computed.transform !== 'none') {
      const own = new DOMMatrix(computed.transform);
      effectiveLinear = inheritedLinear ? inheritedLinear.multiply(own) : own;
    }
    if (effectiveLinear) {
      effectiveLinear = new DOMMatrix([
        effectiveLinear.a, effectiveLinear.b, effectiveLinear.c, effectiveLinear.d, 0, 0,
      ]);
    }
    // SVG-namespace elements have no layout size to recover, so they keep their own transform.
    // An element with no transform of its own under an upright (scale-only) ancestor is already
    // exact from its bounding box, so only rotation, flips and shear need the composed value.
    if (inheritedLinear && el instanceof HTMLElement && effectiveLinear) {
      const upright = Math.abs(effectiveLinear.b) < 1e-6 && Math.abs(effectiveLinear.c) < 1e-6
        && effectiveLinear.a > 0 && effectiveLinear.d > 0;
      const ownNone = !computed.transform || computed.transform === 'none';
      if (!(ownNone && upright)) {
        const identity = upright && Math.abs(effectiveLinear.a - 1) < 1e-6
          && Math.abs(effectiveLinear.d - 1) < 1e-6;
        styles.transform = identity ? 'none' : effectiveLinear.toString();
      }
    }
    walked.set(el, { rect: r, linear: effectiveLinear, computed });
    if (r.width > 0 && r.height > 0) {
      const corners = cornersOf(r, effectiveLinear, el);
      for (const ancestor of clippersOf(el)) {
        const region = clipRegion(ancestor);
        if (region && !region.coversSlide && corners.some((point) => outsideClip(region, point))) {
          styles.domoxmlClippedByAncestor = 'true';
          break;
        }
      }
    }
    if (styles.transform && styles.transform !== 'none') {
      styles.domoxmlLayoutWidth = String(el.offsetWidth);
      styles.domoxmlLayoutHeight = String(el.offsetHeight);
    }
    const consolidateText = consolidatesText(el);
    if (consolidateText) styles.domoxmlConsolidatedText = 'true';
    if (el.classList.contains('domoxml-slide')) styles.domoxmlSlideRoot = 'true';
    // For <li> elements record the list nesting depth and list type.
    if (tag === 'li') {
      const ctx = listContext(el);
      styles.domoxmlListDepth = String(ctx.depth);
      styles.domoxmlListType = ctx.listType || styles.listStyleType || 'disc';
      if (ctx.ordinal !== null) styles.domoxmlListOrdinal = String(ctx.ordinal);
    }
    // For SVG path elements, capture the 'd' attribute in the src slot so the extractor
    // can parse it as a custom geometry without needing the HTML source.
    const svgSrc = (tag === 'path' || tag === 'svg')
      ? (el.getAttribute('d') || el.getAttribute('viewBox') || '')
      : (el.currentSrc || el.getAttribute('src') || '');
    // For table cells record the HTML colspan/rowspan so the extractor can build the grid.
    if (tag === 'td' || tag === 'th') {
      styles.domoxmlColSpan = String(el.colSpan || 1);
      styles.domoxmlRowSpan = String(el.rowSpan || 1);
    }
    // For the slide root element (first child of body), capture data-transition* attributes
    // so the extractor can recover SlideTransition IR.
    if (el.parentElement === document.body) {
      const tr = el.getAttribute('data-transition');
      const trDur = el.getAttribute('data-transition-duration');
      const trDir = el.getAttribute('data-transition-direction');
      if (tr) styles.domoxmlTransition = tr;
      if (trDur) styles.domoxmlTransitionDuration = trDur;
      if (trDir) styles.domoxmlTransitionDirection = trDir;
    }
    // Stable Canvas IR identity/provenance emitted by normalized HTML. Keep it separate from
    // computed CSS so a PPTX -> HTML -> PPTX cycle can recover source ownership exactly.
    const metadata = {
      domoxmlNodeId: 'data-domoxml-node-id',
      domoxmlSourceFormat: 'data-domoxml-source-format',
      domoxmlSourceId: 'data-domoxml-source-id',
      domoxmlSourcePart: 'data-domoxml-source-part',
      domoxmlOwnerNodeId: 'data-domoxml-owner-node-id',
      domoxmlLayerRole: 'data-domoxml-layer-role',
      domoxmlPreservedPayload: 'data-domoxml-preserved-payload',
      domoxmlRepresentation: 'data-domoxml-representation',
      domoxmlSlideFallback: 'data-domoxml-slide-fallback',
      domoxmlConnector: 'data-domoxml-connector',
      domoxmlEffects: 'data-domoxml-effects',
      domoxmlCustomGeometry: 'data-domoxml-custom-geometry',
      domoxmlRasterBounds: 'data-domoxml-raster-bounds',
      domoxmlReflectionDistance: 'data-domoxml-reflection-distance',
      domoxmlReflectionBlur: 'data-domoxml-reflection-blur',
      domoxmlTextPayload: 'data-domoxml-text-payload',
      domoxmlTableGeometry: 'data-domoxml-table-geometry',
      domoxmlGroup: 'data-domoxml-group',
    };
    for (const [key, attribute] of Object.entries(metadata)) {
      const value = el.getAttribute(attribute);
      if (value) styles[key] = value;
    }
    if (el.id) styles.domoxmlElementId = el.id;
    out.push({
      tag,
      x: r.x, y: r.y, width: r.width, height: r.height,
      text, index, parent,
      src: svgSrc,
      styles,
      textRuns: inlineRuns(el, consolidateText),
    });
    for (const child of el.children) walk(child, index, effectiveLinear);
  };
  walk(document.body, -1, null);
  return out;
}
"""

_CAPTURED_RESOURCE_TYPES = frozenset({"image", "font"})
# The only scheme a render legitimately needs. Rendered HTML is attacker-influenced (callers
# embed sanitizer output, not trusted markup), so this is a hard boundary, not a default —
# there is deliberately no way to widen it from BrowserSession's constructor.
_ALLOWED_URL_SCHEMES = frozenset({"data"})
_BLUR_RE = re.compile(r"blur\(\s*([\d.]+)px\s*\)", re.IGNORECASE)
_BOX_REFLECTION_RE = re.compile(r"^(above|below|left|right)\s+(-?[\d.]+)px\b", re.IGNORECASE)
_MATRIX_RE = re.compile(
    r"matrix\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*"
    r"([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*\)",
    re.IGNORECASE,
)
# Matches CSS rotate(Ndeg) / rotate(Nrad) / rotate(Nturn) / rotate(Ngrad).
_ROTATE_RE = re.compile(
    r"rotate\(\s*([-\d.eE]+)(deg|rad|turn|grad)\s*\)",
    re.IGNORECASE,
)
# Matches scaleX(N) / scaleY(N) — used for flip detection.
_SCALEX_RE = re.compile(r"scaleX\(\s*([-\d.eE]+)\s*\)", re.IGNORECASE)
_SCALEY_RE = re.compile(r"scaleY\(\s*([-\d.eE]+)\s*\)", re.IGNORECASE)
_ISOLATE_JS = """
(index) => {
  const selected = document.querySelector(`[data-domoxml-capture-index="${index}"]`);
  if (!selected) return () => {};
  const changed = [];
  const rootStyles = [
    [document.documentElement, document.documentElement.style.cssText],
    [document.body, document.body.style.cssText],
  ];
  const elements = [
    document.documentElement,
    document.body,
    ...document.body.querySelectorAll('*'),
  ];
  for (const element of elements) {
    changed.push([
      element,
      element.style.getPropertyValue('visibility'),
      element.style.getPropertyPriority('visibility'),
    ]);
    element.style.setProperty(
      'visibility',
      element === selected || selected.contains(element) ? 'visible' : 'hidden',
      'important',
    );
  }
  for (const [element] of rootStyles) {
    element.style.setProperty('background', 'transparent', 'important');
    element.style.setProperty('background-color', 'transparent', 'important');
    element.style.setProperty('background-image', 'none', 'important');
  }
  return () => {
    for (const [element, visibility, priority] of changed) {
      if (visibility) element.style.setProperty('visibility', visibility, priority);
      else element.style.removeProperty('visibility');
    }
    for (const [element, cssText] of rootStyles) element.style.cssText = cssText;
  };
}
"""


# `backdrop-filter` blurs whatever is painted behind an element, so the blurred backdrop is the
# one piece of a glass element PowerPoint cannot express. It is captured on its own: everything
# painted before the element (document order, the stacking order the extractor models) stays, what
# is painted after is hidden, and the element's own paint and descendants are neutralised so only
# the blurred backdrop remains. The element itself, its tint, border, shadow and children, is
# extracted as ordinary native shapes on top.
_BACKDROP_JS = """
(args) => {
  const [index, mode] = args;
  const selected = document.querySelector(`[data-domoxml-capture-index="${index}"]`);
  if (!selected) return () => {};
  const changed = [];
  const hide = (element) => {
    changed.push([
      element,
      element.style.getPropertyValue('visibility'),
      element.style.getPropertyPriority('visibility'),
    ]);
    element.style.setProperty('visibility', 'hidden', 'important');
  };
  for (const element of document.body.querySelectorAll('*')) {
    if (element === selected) continue;
    const inside = selected.contains(element);
    const around = element.contains(selected);
    const later = !inside && !around
      && (selected.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    if (mode === 'shape' || inside || later) hide(element);
  }
  const rootStyles = [
    [document.documentElement, document.documentElement.style.cssText],
    [document.body, document.body.style.cssText],
  ];
  if (mode === 'shape') {
    for (const [element] of rootStyles) {
      element.style.setProperty('background', 'transparent', 'important');
      element.style.setProperty('background-image', 'none', 'important');
    }
  }
  const original = selected.style.cssText;
  const own = {
    'box-shadow': 'none', 'border-color': 'transparent', outline: 'none',
    color: 'transparent', 'text-shadow': 'none',
    background: mode === 'shape' ? '#000' : 'transparent',
  };
  if (mode === 'shape') {
    own['backdrop-filter'] = 'none';
    own.visibility = 'visible';
  }
  for (const [name, value] of Object.entries(own)) {
    selected.style.setProperty(name, value, 'important');
  }
  return () => {
    selected.style.cssText = original;
    for (const [element, visibility, priority] of changed) {
      if (visibility) element.style.setProperty('visibility', visibility, priority);
      else element.style.removeProperty('visibility');
    }
    for (const [element, cssText] of rootStyles) element.style.cssText = cssText;
  };
}
"""


class RenderedTextRun(BaseModel):
    """One ordered inline text fragment with Chromium-resolved typography."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    text: str
    styles: dict[str, str] = Field(default_factory=dict)


class RenderedNode(BaseModel):
    """One element as Chromium laid it out: box (CSS px), direct text, computed styles, plus
    its DOM ``index`` and ``parent`` index (root = ``-1``) for subtree-aware rasterisation."""

    model_config = ConfigDict(frozen=True)

    tag: str
    x: float
    y: float
    width: float
    height: float
    text: str = ""
    index: int = 0
    parent: int = -1
    src: str = ""
    styles: dict[str, str] = Field(default_factory=dict)
    text_runs: tuple[RenderedTextRun, ...] = Field(default_factory=tuple, alias="textRuns")


type RasterPlanner = Callable[["RenderedSlide"], Collection[int]]
"""Names the nodes of a snapshot whose fallback pixels must be captured in isolation."""


class RenderedRaster(BaseModel):
    """One isolated raster fallback region, including effect overflow."""

    model_config = ConfigDict(frozen=True)

    png: bytes
    x: float
    y: float
    width: float
    height: float


class RenderedSlide(BaseModel):
    """The render of one slide: its PNG, the captured layout tree, the resources Chromium
    fetched (image/font bytes keyed by URL), and the device scale the PNG was taken at."""

    model_config = ConfigDict(frozen=True)

    png: bytes
    width: int
    height: int
    scale: float = 1.0
    nodes: tuple[RenderedNode, ...]
    resources: dict[str, bytes] = Field(default_factory=dict)
    rasters: dict[int, RenderedRaster] = Field(default_factory=dict[int, RenderedRaster])
    backdrops: dict[int, RenderedRaster] = Field(default_factory=dict[int, RenderedRaster])


def _raster_bounds(
    node: RenderedNode, *, slide_width: int, slide_height: int
) -> tuple[float, float, float, float]:
    """Return slide-clamped paint bounds for an isolated element raster."""
    encoded_bounds = node.styles.get("domoxmlRasterBounds", "").split()
    if len(encoded_bounds) == 4:
        try:
            left, top, width, height = (float(value) for value in encoded_bounds)
        except ValueError:
            pass
        else:
            if all(math.isfinite(value) for value in (left, top, width, height)) and (
                width > 0 and height > 0
            ):
                clamped_left = min(float(slide_width), max(0.0, left))
                clamped_top = min(float(slide_height), max(0.0, top))
                return (
                    clamped_left,
                    clamped_top,
                    max(clamped_left, min(float(slide_width), left + width)),
                    max(clamped_top, min(float(slide_height), top + height)),
                )
    match = _BLUR_RE.search(node.styles.get("filter", ""))
    padding = float(match.group(1)) * 3 if match is not None else 0.0
    left = node.x - padding
    top = node.y - padding
    right = node.x + node.width + padding
    bottom = node.y + node.height + padding

    shadows = parse_shadows(node.styles.get("boxShadow"))
    for shadow in shadows if len(shadows) > 1 else ():
        if shadow.inset:
            continue
        radians = math.radians(shadow.direction_deg)
        offset_x = emu_to_px(shadow.distance_emu) * math.cos(radians)
        offset_y = emu_to_px(shadow.distance_emu) * math.sin(radians)
        # Chromium expands a box-shadow blur by three standard deviations, where the
        # standard deviation is half the blur radius. The 1.5x paint extent avoids
        # transparent fallback padding that would inflate raster-area accounting.
        extent = max(
            0.0,
            (1.5 * emu_to_px(shadow.blur_emu)) + emu_to_px(shadow.spread_emu),
        )
        candidates = (
            node.x + offset_x - extent,
            node.y + offset_y - extent,
            node.x + node.width + offset_x + extent,
            node.y + node.height + offset_y + extent,
        )
        snapped = tuple(
            float(round(value)) if abs(value - round(value)) < 0.001 else value
            for value in candidates
        )
        shadow_left, shadow_top, shadow_right, shadow_bottom = snapped
        left = min(left, shadow_left)
        top = min(top, shadow_top)
        right = max(right, shadow_right)
        bottom = max(bottom, shadow_bottom)

    reflection = _BOX_REFLECTION_RE.match(node.styles.get("webkitBoxReflect", ""))
    reflection_blur = 0.0
    if reflection is None and node.styles.get("domoxmlReflectionDistance"):
        direction = "below"
        distance = max(0.0, float(node.styles["domoxmlReflectionDistance"]))
        reflection_blur = max(0.0, float(node.styles.get("domoxmlReflectionBlur", "0")))
    elif reflection is not None:
        direction = reflection.group(1).lower()
        distance = max(0.0, float(reflection.group(2)))
    else:
        direction = ""
        distance = 0.0

    if direction:
        transform = node.styles.get("transform", "none")
        matrix = _MATRIX_RE.search(transform)
        if transform not in ("", "none") and matrix is None:
            return (0.0, 0.0, float(slide_width), float(slide_height))
        a, b, c, d = (
            (float(matrix.group(index)) for index in range(1, 5))
            if matrix is not None
            else (1.0, 0.0, 0.0, 1.0)
        )
        layout_width = float(node.styles.get("domoxmlLayoutWidth", node.width))
        layout_height = float(node.styles.get("domoxmlLayoutHeight", node.height))

        def transformed_rect(
            x0: float, y0: float, x1: float, y1: float
        ) -> tuple[float, float, float, float]:
            points = (
                (a * x0 + c * y0, b * x0 + d * y0),
                (a * x1 + c * y0, b * x1 + d * y0),
                (a * x0 + c * y1, b * x0 + d * y1),
                (a * x1 + c * y1, b * x1 + d * y1),
            )
            xs, ys = zip(*points, strict=True)
            return min(xs), min(ys), max(xs), max(ys)

        original = transformed_rect(0.0, 0.0, layout_width, layout_height)
        if direction == "below":
            reflected = transformed_rect(
                0.0,
                layout_height + distance,
                layout_width,
                (2 * layout_height) + distance,
            )
        elif direction == "above":
            reflected = transformed_rect(0.0, -layout_height - distance, layout_width, -distance)
        elif direction == "left":
            reflected = transformed_rect(-layout_width - distance, 0.0, -distance, layout_height)
        else:
            reflected = transformed_rect(
                layout_width + distance,
                0.0,
                (2 * layout_width) + distance,
                layout_height,
            )
        ref_left = node.x + reflected[0] - original[0]
        ref_top = node.y + reflected[1] - original[1]
        ref_right = node.x + reflected[2] - original[0]
        ref_bottom = node.y + reflected[3] - original[1]
        reflected_padding = padding + (reflection_blur * 3)
        left = min(left, ref_left - reflected_padding)
        top = min(top, ref_top - reflected_padding)
        right = max(right, ref_right + reflected_padding)
        bottom = max(bottom, ref_bottom + reflected_padding)
    return (
        max(0.0, left),
        max(0.0, top),
        min(float(slide_width), right),
        min(float(slide_height), bottom),
    )


def _decompose_matrix(a: float, b: float, c: float, d: float) -> tuple[float, bool, bool] | None:
    """Decompose a 2-D linear matrix ``[a b c d]`` into ``(rotation_deg, flip_h, flip_v)`` when
    it is a pure rotation optionally combined with axis flips (±1 scale), else ``None``.

    A CSS matrix maps to OOXML as: optional flipH (negate x), optional flipV (negate y), then a
    rotation. Browsers emit ``rotate(θ)`` as ``matrix(cosθ, sinθ, -sinθ, cosθ, 0, 0)`` (y-down,
    so positive θ is clockwise — same convention as OOXML ``rot``). We try each of the four
    flip combinations and accept the one that leaves a clean rotation."""
    tol = 1e-3
    candidates: list[tuple[float, bool, bool]] = []
    for flip_h, sx in ((False, 1.0), (True, -1.0)):
        for flip_v, sy in ((False, 1.0), (True, -1.0)):
            # Undo the flips: a column scaled by sx/sy. Remaining must be a rotation matrix
            # [cos, sin, -sin, cos] with unit columns and matching cos/sin across both columns.
            ra, rb = a * sx, b * sx
            rc, rd = c * sy, d * sy
            if (
                abs(ra - rd) <= tol  # cosθ agrees
                and abs(rb + rc) <= tol  # sinθ agrees (rb = sinθ, rc = -sinθ)
                and abs((ra * ra + rb * rb) - 1.0) <= tol  # unit length ⇒ no scale/shear
            ):
                angle = math.degrees(math.atan2(rb, ra)) % 360.0
                candidates.append((angle, flip_h, flip_v))
    if not candidates:
        return None

    # A flip can be encoded as flipV+rot180 etc.; prefer the simplest reading: least rotation,
    # then fewest flips. So scaleX(-1) reads as (0°, flipH) not (180°, flipV).
    def _rank(cand: tuple[float, bool, bool]) -> tuple[float, int]:
        angle, fh, fv = cand
        return min(angle, 360.0 - angle), int(fh) + int(fv)

    return min(candidates, key=_rank)


def _matrix_is_complex(a: float, b: float, c: float, d: float) -> bool:
    """True when a 2-D matrix is NOT a pure rotation/flip (i.e. has shear or non-unit scale)."""
    return _decompose_matrix(a, b, c, d) is None


def is_complex_transform(value: str | None) -> bool:
    """Return True when ``value`` cannot be expressed as a pure translation, rotation, or flip.

    Pure rotation (``rotate(Ndeg)``), scale-by-±1 flips (``scaleX(-1)``/``scaleY(-1)``), and
    their combinations are **not** complex — they map natively to ``a:xfrm rot/flipH/flipV``.
    Skew, perspective, matrix-with-shear, and 3-D transforms remain complex (raster fallback).
    """
    if not value or value == "none":
        return False
    lowered = value.lower()
    if lowered.startswith("matrix3d") or "skew" in lowered or "perspective" in lowered:
        return True

    # Check for a matrix() — only non-translation 2-D transforms land here. NOTE: browsers
    # resolve getComputedStyle().transform to the matrix() form, so rotate(Ndeg) arrives here
    # as matrix(cos, sin, -sin, cos, …), NOT as a rotate() token. We must accept rotation +
    # flip matrices natively; only true shear / non-unit scale is complex.
    match = _MATRIX_RE.search(lowered)
    if match is not None:
        a, b, c, d = (float(match.group(index)) for index in range(1, 5))
        return _matrix_is_complex(a, b, c, d)

    # Functional form: strip translate/scaleX(±1)/scaleY(±1)/rotate tokens and see what's left.
    # Any remaining token other than translate → complex.
    remainder = lowered
    remainder = re.sub(r"translate[xy]?\([^)]*\)", "", remainder)
    remainder = re.sub(r"rotate\([^)]*\)", "", remainder)
    remainder = re.sub(r"scalex?\(\s*-?1\s*\)", "", remainder)
    remainder = re.sub(r"scaley\(\s*-?1\s*\)", "", remainder)
    remainder = remainder.strip()
    # If anything other than whitespace/commas remains it is an unrecognised function.
    remainder = re.sub(r"[\s,]+", "", remainder)
    return bool(remainder)


def parse_native_transform(value: str | None) -> tuple[float, bool, bool]:
    """Parse a CSS transform string that has already been verified non-complex.

    Returns ``(rotation_deg, flip_h, flip_v)`` where ``rotation_deg`` is the clockwise
    rotation in degrees (CSS and OOXML both use clockwise-positive degrees).

    Handles:
    - ``rotate(Ndeg|Nrad|Nturn|Ngrad)``
    - ``scaleX(-1)`` / ``scaleY(-1)``
    - ``matrix(a,b,c,d,e,f)`` where |a|=|d|=1 and b=c=0 (pure flip)
    - Combined forms: ``rotate(Ndeg) scaleX(-1)`` etc.

    Translation components are ignored (layout comes from the element's bounding box).
    """
    if not value or value == "none":
        return 0.0, False, False

    rotation_deg = 0.0
    flip_h = False
    flip_v = False
    lowered = value.lower()

    # Matrix form (what getComputedStyle returns): decompose into rotation + flips.
    matrix_match = _MATRIX_RE.search(lowered)
    if matrix_match is not None:
        a, b, c, d = (float(matrix_match.group(i)) for i in range(1, 5))
        decomposed = _decompose_matrix(a, b, c, d)
        if decomposed is not None:
            return decomposed
        return 0.0, False, False

    # Functional form — extract rotate and scale tokens.
    rot_match = _ROTATE_RE.search(lowered)
    if rot_match is not None:
        amount = float(rot_match.group(1))
        unit = rot_match.group(2)
        if unit == "rad":
            import math

            rotation_deg = math.degrees(amount) % 360.0
        elif unit == "turn":
            rotation_deg = (amount * 360.0) % 360.0
        elif unit == "grad":
            rotation_deg = (amount * 0.9) % 360.0
        else:  # deg
            rotation_deg = amount % 360.0

    sx_match = _SCALEX_RE.search(lowered)
    if sx_match is not None:
        flip_h = float(sx_match.group(1)) < -0.5

    sy_match = _SCALEY_RE.search(lowered)
    if sy_match is not None:
        flip_v = float(sy_match.group(1)) < -0.5

    return rotation_deg, flip_h, flip_v


class BrowserSession:
    """A warm headless-Chromium session. Use as an async context manager and call
    :meth:`render` once per slide::

        async with BrowserSession() as session:
            slide = await session.render(html, width=1280, height=720)
    """

    def __init__(self, *, scale: float = 2.0) -> None:
        self._scale = scale
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
        except BaseException:
            # __aexit__ won't run if __aenter__ raises — clean up the started Playwright here.
            await self._playwright.stop()
            self._playwright = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def _capture_backdrop(
        self, page: Page, node: RenderedNode, *, width: int, height: int
    ) -> RenderedRaster | None:
        """The blurred backdrop an element sits over, cut to the element's own border-box shape."""
        x, y, right, bottom = _raster_bounds(node, slide_width=width, slide_height=height)
        region = {
            "left": x * self._scale,
            "top": y * self._scale,
            "width": (right - x) * self._scale,
            "height": (bottom - y) * self._scale,
        }
        shots: list[bytes] = []
        for mode, omit_background in (("layer", False), ("shape", True)):
            restore = await page.evaluate_handle(_BACKDROP_JS, [node.index, mode])
            try:
                shots.append(await page.screenshot(type="png", omit_background=omit_background))
            finally:
                await restore.evaluate("(restore) => restore()")
                await restore.dispose()
        layer, shape = (crop_png(shot, **region) for shot in shots)
        masked = apply_alpha_mask(layer, shape) if layer is not None and shape is not None else None
        if masked is None:
            return None
        return RenderedRaster(png=masked, x=x, y=y, width=right - x, height=bottom - y)

    async def render(
        self,
        html: str,
        *,
        width: int,
        height: int,
        raster_planner: RasterPlanner | None = None,
        backdrop_planner: RasterPlanner | None = None,
    ) -> RenderedSlide:
        """Render ``html`` at ``width`` x ``height`` CSS px → PNG + captured layout + the
        image/font bytes the page fetched (so they can be embedded natively downstream).

        ``raster_planner`` names the nodes that need pixels captured in isolation. It defaults
        to the extractor's own plan, so the code that consumes a raster is the code that decides
        one is needed. ``backdrop_planner`` does the same for blurred-backdrop layers.
        """
        if self._browser is None:
            raise RuntimeError("BrowserSession must be entered via 'async with' before render()")
        context = await self._browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=self._scale,
        )
        resources: dict[str, bytes] = {}

        async def _capture(route: Route) -> None:
            # Unconditional network-isolation boundary. Runs before anything else so no request
            # this handler wasn't explicitly asked to fetch can reach the network — regardless of
            # how the URL got into the DOM (img src, legacy `background=`, SVG `fill="url(...)"`,
            # CSS `background-image`, @font-face, ...).
            if urlsplit(route.request.url).scheme.lower() not in _ALLOWED_URL_SCHEMES:
                await route.abort()
                return
            if route.request.resource_type not in _CAPTURED_RESOURCE_TYPES:
                await route.continue_()
                return
            try:
                response = await route.fetch()
                resources[route.request.url] = await response.body()
            except Exception:  # capture is best-effort; never block the render
                await route.continue_()
                return
            try:
                await route.fulfill(response=response)
            except Exception:
                # If fulfill fails, resolve the intercepted request explicitly so page load
                # doesn't stall on an unresolved route.
                with contextlib.suppress(Exception):
                    await route.continue_()

        try:
            page = await context.new_page()
            await page.route("**/*", _capture)
            await page.set_content(html, wait_until="load")
            await page.evaluate("() => document.fonts.ready.then(() => true)")
            png = await page.screenshot(type="png")
            raw: list[dict[str, Any]] = await page.evaluate(_SNAPSHOT_JS)
            nodes = tuple(RenderedNode.model_validate(node) for node in raw)
            snapshot = RenderedSlide(
                png=png,
                width=width,
                height=height,
                scale=self._scale,
                nodes=nodes,
                resources=resources,
            )
            if raster_planner is None:
                from domoxml.core.ir.extract import plan_isolated_rasters

                raster_planner = plan_isolated_rasters
            requested = raster_planner(snapshot)
            rasters: dict[int, RenderedRaster] = {}
            for node in nodes:
                if node.index not in requested:
                    continue
                restore = await page.evaluate_handle(_ISOLATE_JS, node.index)
                try:
                    isolated_page = await page.screenshot(type="png", omit_background=True)
                finally:
                    await restore.evaluate("(restore) => restore()")
                    await restore.dispose()
                x, y, right, bottom = _raster_bounds(node, slide_width=width, slide_height=height)
                crop = crop_png(
                    isolated_page,
                    left=x * self._scale,
                    top=y * self._scale,
                    width=(right - x) * self._scale,
                    height=(bottom - y) * self._scale,
                )
                if crop is not None:
                    rasters[node.index] = RenderedRaster(
                        png=crop, x=x, y=y, width=right - x, height=bottom - y
                    )
            backdrops: dict[int, RenderedRaster] = {}
            if backdrop_planner is None:
                from domoxml.core.ir.extract import plan_backdrop_layers

                backdrop_planner = plan_backdrop_layers
            wanted = backdrop_planner(snapshot)
            for node in nodes:
                if node.index not in wanted:
                    continue
                layer = await self._capture_backdrop(page, node, width=width, height=height)
                if layer is not None:
                    backdrops[node.index] = layer
            return snapshot.model_copy(update={"rasters": rasters, "backdrops": backdrops})
        finally:
            await context.close()
