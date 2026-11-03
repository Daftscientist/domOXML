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

from domoxml.core.images import apply_alpha_mask, crop_png, unrotate_region
from domoxml.core.ir.parse import parse_shadows
from domoxml.core.render.canvas_recorder import RECORDER_JS
from domoxml.core.units import emu_to_px

# Walks the rendered DOM and, per element, captures its box, direct text, ordered inline
# text runs, the computed styles the extractor needs, and enough structure (index/parent)
# to let the extractor rasterise an element together with its subtree. This is the raw material.
_SNAPSHOT_JS = """
() => {
  const pick = (cs) => ({
    color: cs.color, appearance: cs.appearance, backgroundColor: cs.backgroundColor,
    backgroundImage: cs.backgroundImage,
    backgroundSize: cs.backgroundSize, backgroundPosition: cs.backgroundPosition,
    backgroundRepeat: cs.backgroundRepeat, backgroundBlendMode: cs.backgroundBlendMode,
    backgroundOrigin: cs.backgroundOrigin, backgroundClip: cs.backgroundClip,
    fontSize: cs.fontSize, fontFamily: cs.fontFamily,
    fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
    textDecorationLine: cs.textDecorationLine, textDecorationStyle: cs.textDecorationStyle,
    textDecorationColor: cs.textDecorationColor, verticalAlign: cs.verticalAlign,
    accentColor: cs.accentColor,
    writingMode: cs.writingMode,
    textTransform: cs.textTransform,
    fontVariantCaps: cs.fontVariantCaps, letterSpacing: cs.letterSpacing,
    textAlign: cs.textAlign, lineHeight: cs.lineHeight,
    outlineWidth: cs.outlineWidth, outlineStyle: cs.outlineStyle, outlineColor: cs.outlineColor,
    outlineOffset: cs.outlineOffset,
    borderRadius: cs.borderRadius, opacity: cs.opacity,
    borderTopLeftRadius: cs.borderTopLeftRadius, borderTopRightRadius: cs.borderTopRightRadius,
    borderBottomRightRadius: cs.borderBottomRightRadius,
    borderBottomLeftRadius: cs.borderBottomLeftRadius,
    boxShadow: cs.boxShadow, filter: cs.filter, webkitBoxReflect: cs.webkitBoxReflect,
    maskImage: cs.maskImage, maskComposite: cs.maskComposite,
    maskRepeat: cs.maskRepeat, maskPosition: cs.maskPosition, maskSize: cs.maskSize,
    maskOrigin: cs.maskOrigin, maskClip: cs.maskClip, maskMode: cs.maskMode,
    mixBlendMode: cs.mixBlendMode, backdropFilter: cs.backdropFilter,
    clipPath: cs.clipPath, transform: cs.transform, transformOrigin: cs.transformOrigin,
    borderTopWidth: cs.borderTopWidth, borderTopStyle: cs.borderTopStyle,
    borderTopColor: cs.borderTopColor,
    borderImageSource: cs.borderImageSource, borderImageSlice: cs.borderImageSlice,
    borderImageWidth: cs.borderImageWidth, borderImageOutset: cs.borderImageOutset,
    borderImageRepeat: cs.borderImageRepeat,
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
    textShadow: cs.textShadow, webkitTextStrokeWidth: cs.webkitTextStrokeWidth,
    webkitTextStrokeColor: cs.webkitTextStrokeColor, webkitTextFillColor: cs.webkitTextFillColor,
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
  const SVG_PAINT = ['fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width',
    'stroke-opacity', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
    'stroke-dasharray', 'stroke-dashoffset', 'opacity', 'stop-color', 'stop-opacity',
    'clip-rule', 'visibility', 'font-family', 'font-size',
    'font-weight', 'font-style', 'text-anchor', 'dominant-baseline', 'letter-spacing'];
  // A standalone copy of an <svg>: sheet-driven paint is inlined, so it renders outside the page.
  const serializeSvg = (el, rect) => {
    const clone = el.cloneNode(true);
    const originals = [el, ...el.querySelectorAll('*')];
    const clones = [clone, ...clone.querySelectorAll('*')];
    originals.forEach((original, i) => {
      const cs = getComputedStyle(original);
      for (const property of SVG_PAINT) {
        const value = cs.getPropertyValue(property);
        if (value) clones[i].setAttribute(property, value);
      }
    });
    // Paint a stylesheet hid or moved cannot be carried to a standalone file: leave it raster.
    const GRAPHIC = new Set(['path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
      'g', 'text', 'tspan', 'image', 'use']);
    const drifted = originals.slice(1).some((original) => {
      if (!GRAPHIC.has(original.tagName.toLowerCase())) return false;
      if (original.closest('defs, mask, clipPath, pattern, symbol, marker')) return false;
      const cs = getComputedStyle(original);
      const moved = cs.transform !== 'none' && !original.hasAttribute('transform');
      return cs.display === 'none' || moved;
    });
    if (drifted) return null;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(rect.width));
    clone.setAttribute('height', String(rect.height));
    clone.removeAttribute('style');
    clone.removeAttribute('class');
    return new XMLSerializer().serializeToString(clone);
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
    if (computed.transform && computed.transform !== 'none' && el instanceof HTMLElement) {
      // The transformed corners of the element's own box (skew and perspective included), so a
      // plain filled box under a non-rotation transform can be a native quadrilateral. Only when
      // no ancestor is transformed: the corners are measured through the ancestors' transforms.
      let transformedAncestor = false;
      for (let a = el.parentElement; a; a = a.parentElement) {
        if (getComputedStyle(a).transform !== 'none') { transformedAncestor = true; break; }
      }
      if (!transformedAncestor) {
        const saved = el.style.transform;
        el.style.transform = 'none';
        const box = el.getBoundingClientRect();
        el.style.transform = saved;
        const [originX, originY] = computed.transformOrigin.split(' ').map(parseFloat);
        const matrix = new DOMMatrix(computed.transform);
        const corners = [[box.left, box.top], [box.right, box.top], [box.right, box.bottom],
          [box.left, box.bottom]].map(([x, y]) => {
          const point = matrix.transformPoint(new DOMPoint(x - box.left - originX,
            y - box.top - originY, 0, 1));
          return [box.left + originX + point.x / point.w, box.top + originY + point.y / point.w];
        });
        styles.domoxmlQuad = corners.flat().map((value) => Math.round(value * 100) / 100).join(',');
      }
    }
    if (!styles.domoxmlQuad && el instanceof HTMLElement && el.offsetWidth > 0
        && el.offsetHeight > 0 && !(el instanceof HTMLImageElement)) {
      // Under a 3D or perspective ancestor an element's corners cannot be derived from its own
      // style, so measure them: four zero-size probes at the border box corners are laid out
      // through every ancestor transform, and where each lands is where that corner is drawn.
      let projective = false;
      for (let a = el.parentElement; a; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (cs.perspective !== 'none'
            || (cs.transform !== 'none' && !new DOMMatrix(cs.transform).is2D)) {
          projective = true;
          break;
        }
      }
      if (projective) {
        const previous = el.style.position;
        if (computed.position === 'static') el.style.position = 'relative';
        const bl = parseFloat(computed.borderLeftWidth) || 0;
        const bt = parseFloat(computed.borderTopWidth) || 0;
        const w = el.offsetWidth, h = el.offsetHeight;
        const corners = [[0, 0], [w, 0], [w, h], [0, h]].map(([x, y]) => {
          const probe = document.createElement('span');
          probe.style.cssText = 'position:absolute;width:0;height:0;margin:0;padding:0;border:0;'
            + `left:${x - bl}px;top:${y - bt}px;visibility:hidden`;
          el.appendChild(probe);
          const at = probe.getBoundingClientRect();
          el.removeChild(probe);
          return [at.x, at.y];
        });
        el.style.position = previous;
        styles.domoxmlQuad = corners.flat().map((v) => Math.round(v * 100) / 100).join(',');
        styles.domoxmlProjected = 'true';
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
      if (!(ownNone && upright) && !styles.domoxmlProjected) {
        const identity = upright && Math.abs(effectiveLinear.a - 1) < 1e-6
          && Math.abs(effectiveLinear.d - 1) < 1e-6;
        styles.transform = identity ? 'none' : effectiveLinear.toString();
      }
    }
    walked.set(el, { rect: r, linear: effectiveLinear, computed });
    if (r.width > 0 && r.height > 0) {
      const corners = cornersOf(r, effectiveLinear, el);
      let window = null;
      let windowExact = true;
      for (const ancestor of clippersOf(el)) {
        const region = clipRegion(ancestor);
        if (region && !region.coversSlide && corners.some((point) => outsideClip(region, point))) {
          styles.domoxmlClippedByAncestor = 'true';
        }
        if (!region || region.coversSlide) continue;
        // The clip as a page rectangle (and corner radius), when it is upright and unscaled.
        const inverse = region.inverse;
        const upright = Math.abs(inverse.a - 1) < 1e-6 && Math.abs(inverse.d - 1) < 1e-6
          && Math.abs(inverse.b) < 1e-6 && Math.abs(inverse.c) < 1e-6;
        if (!upright || region.clipX !== region.clipY) { windowExact = false; continue; }
        const cx = region.centre.x + region.shift.x, cy = region.centre.y + region.shift.y;
        const rect = { left: cx - region.half.x, top: cy - region.half.y,
          right: cx + region.half.x, bottom: cy + region.half.y, radius: region.radius };
        if (!window) { window = rect; continue; }
        const merged = {
          left: Math.max(window.left, rect.left), top: Math.max(window.top, rect.top),
          right: Math.min(window.right, rect.right),
          bottom: Math.min(window.bottom, rect.bottom),
          radius: Math.max(window.radius, rect.radius),
        };
        // A rounded clip survives an intersection only when it is the whole result: otherwise a
        // new straight edge cuts through its corners and the result is not one rounded box.
        const same = (a, b) => Math.abs(a.left - b.left) + Math.abs(a.top - b.top)
          + Math.abs(a.right - b.right) + Math.abs(a.bottom - b.bottom) < 0.01;
        if ((window.radius > 0 && !same(merged, window))
            || (rect.radius > 0 && !same(merged, rect))) {
          windowExact = false;
        }
        window = merged;
      }
      // A clip that turns with the element (both carry the same rotation) is a plain rectangle
      // in the element's own frame, whatever the angle: where it sits relative to the element's
      // layout box is what a native shape needs.
      if (styles.domoxmlClippedByAncestor && !(window && windowExact) && effectiveLinear
          && el instanceof HTMLElement && el.offsetWidth > 0 && el.offsetHeight > 0) {
        const turning = [];
        for (const ancestor of clippersOf(el)) {
          const region = clipRegion(ancestor);
          if (region && !region.coversSlide) turning.push([ancestor, region]);
        }
        if (turning.length === 1) {
          const [ancestor, region] = turning[0];
          const record = walked.get(ancestor);
          const same = record && record.linear && ['a', 'b', 'c', 'd'].every(
            (k) => Math.abs(record.linear[k] - effectiveLinear[k]) < 1e-6);
          const rotating = Math.abs(region.inverse.b) > 1e-6 || Math.abs(region.inverse.c) > 1e-6;
          if (same && rotating && region.clipX && region.clipY) {
            const mine = region.inverse.transformPoint({
              x: r.x + r.width / 2 - region.centre.x, y: r.y + r.height / 2 - region.centre.y,
            });
            const left = region.shift.x - region.half.x - (mine.x - el.offsetWidth / 2);
            const top = region.shift.y - region.half.y - (mine.y - el.offsetHeight / 2);
            styles.domoxmlLocalClipRect = [left, top, 2 * region.half.x, 2 * region.half.y,
              region.radius].map((v) => Math.round(v * 100) / 100).join(',');
          }
        }
      }
      if (styles.domoxmlClippedByAncestor && window && windowExact) {
        const parts = [window.left, window.top, window.right - window.left,
          window.bottom - window.top, window.radius];
        styles.domoxmlClipRect = parts.map((v) => Math.round(v * 100) / 100).join(',');
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
      const notes = el.getAttribute('data-notes');
      if (notes && notes.trim()) styles.domoxmlNotes = notes;
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
    if (tag === 'progress' || tag === 'meter' || (tag === 'input'
        && ['checkbox', 'radio', 'range'].includes(el.type))) {
      const number = (v) => (v === undefined || v === '' || Number.isNaN(Number(v))
        ? null : Number(v));
      styles.domoxmlControl = JSON.stringify({
        tag, type: el.type || '', checked: !!el.checked, value: number(el.value),
        min: number(el.min), max: number(el.max), low: number(el.low), high: number(el.high),
        optimum: number(el.optimum), indeterminate: tag === 'progress' && el.position === -1,
        rtl: getComputedStyle(el).direction === 'rtl',
      });
    }
    if (tag === 'select' && (el.multiple || el.size > 1)) styles.domoxmlSelectList = 'true';
    if (tag === 'iframe' && el.hasAttribute('srcdoc')) styles.domoxmlSrcdoc = 'true';
    if (el.getAttribute('aria-hidden') !== 'true') {
      const title = tag === 'svg' ? el.querySelector(':scope > title') : null;
      const alt = el.getAttribute('aria-label')
        || (tag === 'img' ? el.getAttribute('alt') : null)
        || (title ? title.textContent : null);
      if (alt && alt.trim()) styles.domoxmlAlt = alt.trim();
    }
    const colCs = getComputedStyle(el);
    if (colCs.columnCount !== 'auto' && parseInt(colCs.columnCount, 10) > 1
        && colCs.columnFill !== 'auto' && el.offsetHeight > 0) {
      // Balanced columns: how tall the tallest column actually is, so the text area can be
      // shrunk to it (PowerPoint fills columns in order up to the box height).
      try {
        // A transformed element or ancestor distorts the measured rectangles.
        for (let up = el; up && up.nodeType === 1; up = up.parentElement) {
          if (getComputedStyle(up).transform !== 'none') throw new Error('transformed');
        }
        const range = document.createRange();
        range.selectNodeContents(el);
        let bottom = -Infinity;
        for (const r of range.getClientRects()) {
          if (r.width > 0) bottom = Math.max(bottom, r.bottom);
        }
        const top = el.getBoundingClientRect().top + (parseFloat(colCs.paddingTop) || 0)
          + (parseFloat(colCs.borderTopWidth) || 0);
        // A fraction of the element's own height, so it holds in the shape's local coordinates.
        if (bottom > top) styles.domoxmlColumnsHeight = String((bottom - top) / el.offsetHeight);
      } catch (e) { /* keep the sequential fill */ }
    }
    if (tag === 'svg' && el.getAttribute('preserveAspectRatio')) {
      styles.domoxmlSvgAspect = el.getAttribute('preserveAspectRatio');
    }
    if (tag === 'svg' && !(el.parentElement && el.parentElement.closest('svg'))) {
      try {
        const source = serializeSvg(el, r);
        if (source) styles.domoxmlSvgSource = source;
      } catch (e) { /* not embeddable */ }
    }
    if (tag === 'canvas' && window.__domoxmlCanvas) {
      const recorded = window.__domoxmlCanvas(el);
      if (recorded.svg) {
        styles.domoxmlCanvasSvg = recorded.svg;
        styles.domoxmlCanvasPng = recorded.png;
      } else {
        styles.domoxmlCanvasReason = recorded.reason;
      }
    }
    let fieldText = text;
    let fieldRuns = null;
    const textTypes = ['', 'text', 'search', 'email', 'url', 'tel', 'password', 'number'];
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      styles.domoxmlField = tag === 'textarea' ? 'multi' : 'single';
      // Chrome paints a default drop-down white although its computed background is grey.
      if (tag === 'select' && styles.appearance === 'auto'
          && styles.backgroundColor === 'rgb(239, 239, 239)') {
        styles.backgroundColor = 'rgb(255, 255, 255)';
      }
    }
    if (tag === 'select' && !el.multiple && el.size <= 1 && el.selectedOptions[0]) {
      fieldText = el.selectedOptions[0].label || el.selectedOptions[0].textContent || '';
    } else if (tag === 'input' && textTypes.includes(el.type)) {
      let shown = el.value;
      if (shown && el.type === 'password') shown = '\u2022'.repeat(shown.length);
      const hint = !shown && el.placeholder;
      fieldText = shown || el.placeholder || '';
      if (hint) {
        const ph = pick(computed);
        ph.color = getComputedStyle(el, '::placeholder').color;
        ph.webkitTextFillColor = ph.color;
        fieldRuns = [{ text: fieldText, styles: ph }];
      }
    }
    if (fieldText && fieldText !== text) {
      fieldRuns = fieldRuns || [{ text: fieldText, styles: pick(computed) }];
    }
    out.push({
      tag,
      x: r.x, y: r.y, width: r.width, height: r.height,
      text: fieldText, index, parent,
      src: svgSrc,
      styles,
      textRuns: fieldRuns || inlineRuns(el, consolidateText),
    });
    for (const child of el.children) walk(child, index, effectiveLinear);
  };
  // ::before and ::after have no box of their own to measure, so each one that paints is turned
  // into a real element carrying its computed style; the pseudo is then switched off. Layout is
  // unchanged (the real child sits where the pseudo did), and everything downstream sees an
  // ordinary element.
  const materializePseudos = () => {
    const VOID = new Set(['IMG', 'INPUT', 'BR', 'HR', 'TEXTAREA', 'SELECT', 'VIDEO', 'AUDIO',
      'CANVAS', 'IFRAME', 'SVG', 'PROGRESS', 'METER']);
    const style = document.createElement('style');
    style.textContent = '[data-domoxml-pseudo-host]::before,[data-domoxml-pseudo-host]::after'
      + '{content:none !important}';
    document.head.appendChild(style);
    // The text of a computed `content` value: quoted strings and attr() only. Anything else
    // (counters, images) returns null and the pseudo-element is left as it was.
    const textOf = (host, content) => {
      let text = '';
      let at = 0;
      while (at < content.length) {
        const ch = content[at];
        if (ch === ' ') { at += 1; continue; }
        if (ch === '"' || ch === "'") {
          let end = at + 1;
          let piece = '';
          while (end < content.length && content[end] !== ch) {
            if (content[end] === String.fromCharCode(92) && end + 1 < content.length) {
              end += 1;
              let hex = '';
              while (end < content.length && hex.length < 6 && /[0-9a-fA-F]/.test(content[end])) {
                hex += content[end];
                end += 1;
              }
              if (hex) {
                piece += String.fromCodePoint(parseInt(hex, 16));
                if (content[end] === ' ') end += 1;
                continue;
              }
            }
            piece += content[end];
            end += 1;
          }
          if (end >= content.length) return null;
          text += piece;
          at = end + 1;
        } else if (content.startsWith('attr(', at)) {
          const close = content.indexOf(')', at);
          if (close < 0) return null;
          text += host.getAttribute(content.slice(at + 5, close).trim()) || '';
          at = close + 1;
        } else {
          return null;
        }
      }
      return text;
    };
    for (const host of Array.from(document.body.querySelectorAll('*'))) {
      if (VOID.has(host.tagName.toUpperCase()) || host.closest('svg')) continue;
      // Read both pseudo-elements before changing anything: marking the host switches them off,
      // and a computed style is live.
      const found = [];
      for (const which of ['before', 'after']) {
        const cs = getComputedStyle(host, '::' + which);
        const content = cs.content;
        if (!content || content === 'none' || content === 'normal') continue;
        const text = textOf(host, content);
        if (text === null) continue;  // counters, images and the like: left as they were
        const properties = Array.from(cs, (name) => [name, cs.getPropertyValue(name)]);
        found.push({ which, text, properties });
      }
      for (const { which, text, properties } of found) {
        const span = document.createElement('span');
        span.setAttribute('data-domoxml-pseudo', which);
        for (const [name, value] of properties) span.style.setProperty(name, value);
        span.textContent = text;
        if (which === 'before') host.insertBefore(span, host.firstChild);
        else host.appendChild(span);
      }
      if (found.length) host.setAttribute('data-domoxml-pseudo-host', '1');
    }
  };
  // Text that follows a block child of the same parent sits in its own anonymous block box, below
  // that child. The snapshot reads a parent's text as one body at its top, so that text would be
  // merged into the first line. Wrapping it in a real block reproduces the anonymous box exactly.
  const wrapAnonymousBlocks = () => {
    const SKIP = new Set(['SVG', 'BUTTON', 'SELECT', 'TEXTAREA', 'OPTION', 'TABLE', 'TBODY',
      'THEAD', 'TFOOT', 'TR', 'RUBY', 'HEAD', 'STYLE', 'SCRIPT']);
    const outOfFlow = (node) => {
      if (node.nodeType !== 1) return false;
      const cs = getComputedStyle(node);
      return cs.position === 'absolute' || cs.position === 'fixed' || cs.float !== 'none';
    };
    const inFlowBlock = (node) => {
      if (node.nodeType !== 1 || outOfFlow(node)) return false;
      const cs = getComputedStyle(node);
      const display = cs.display;
      return display !== 'none' && display !== 'contents' && !display.startsWith('inline');
    };
    const hasText = (nodes) => nodes.some((node) => (node.textContent || '').trim() !== '');
    for (const host of Array.from(document.body.querySelectorAll('*'))) {
      if (SKIP.has(host.tagName.toUpperCase()) || host.closest('svg')) continue;
      const display = getComputedStyle(host).display;
      if (display.startsWith('inline') && display !== 'inline-block') continue;
      const children = Array.from(host.childNodes);
      if (!children.some(inFlowBlock)) continue;
      const groups = [];
      let current = [];
      let seenBlock = false;
      for (const node of children) {
        if (inFlowBlock(node)) {
          if (current.length) groups.push({ nodes: current, after: seenBlock });
          current = [];
          seenBlock = true;
        } else if (!outOfFlow(node)) {
          current.push(node);  // out-of-flow boxes stay where they are
        }
      }
      if (current.length) groups.push({ nodes: current, after: seenBlock });
      for (const group of groups) {
        // The leading group is the parent's own first line; only later groups are anonymous.
        if (!group.after || !hasText(group.nodes)) continue;
        const wrapper = document.createElement('span');
        wrapper.setAttribute('data-domoxml-anon', 'true');
        wrapper.style.display = 'block';
        group.nodes[0].parentNode.insertBefore(wrapper, group.nodes[0]);
        for (const node of group.nodes) wrapper.appendChild(node);
      }
    }
  };
  materializePseudos();
  wrapAnonymousBlocks();
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
  if (mode !== 'layer') own['backdrop-filter'] = 'none';
  if (mode === 'shape') own.visibility = 'visible';
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


class RenderedBackdrop(BaseModel):
    """What sits behind a ``backdrop-filter`` element, captured two ways.

    ``blurred`` is the backdrop as the browser paints it, cut to the element's shape in slide
    coordinates: exact in place for any renderer that cannot blur. ``sharp`` is the same backdrop
    before blurring, sampled upright in the element's own frame (device pixels), for PowerPoint to
    blur itself; it is ``None`` when the element's transform cannot be undone as a plain rotation.
    """

    model_config = ConfigDict(frozen=True)

    blurred: RenderedRaster
    sharp: bytes | None = None


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
    backdrops: dict[int, RenderedBackdrop] = Field(default_factory=dict[int, RenderedBackdrop])


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
    ) -> RenderedBackdrop | None:
        """The backdrop an element blurs, blurred (cut to its shape) and sharp (upright)."""
        x, y, right, bottom = _raster_bounds(node, slide_width=width, slide_height=height)
        region = {
            "left": x * self._scale,
            "top": y * self._scale,
            "width": (right - x) * self._scale,
            "height": (bottom - y) * self._scale,
        }
        shots: dict[str, bytes] = {}
        for mode, omit_background in (("layer", False), ("shape", True), ("sharp", False)):
            restore = await page.evaluate_handle(_BACKDROP_JS, [node.index, mode])
            try:
                shots[mode] = await page.screenshot(type="png", omit_background=omit_background)
            finally:
                await restore.evaluate("(restore) => restore()")
                await restore.dispose()
        layer, shape = crop_png(shots["layer"], **region), crop_png(shots["shape"], **region)
        masked = apply_alpha_mask(layer, shape) if layer is not None and shape is not None else None
        if masked is None:
            return None
        blurred = RenderedRaster(png=masked, x=x, y=y, width=right - x, height=bottom - y)
        return RenderedBackdrop(blurred=blurred, sharp=self._upright_backdrop(node, shots["sharp"]))

    def _upright_backdrop(self, node: RenderedNode, sharp_page: bytes) -> bytes | None:
        """The sharp backdrop in the element's own frame, or ``None`` if not a plain rotation."""
        transform = node.styles.get("transform", "none")
        rotation, flip_h, flip_v = (0.0, False, False)
        if transform not in ("", "none"):
            if is_complex_transform(transform):
                return None
            rotation, flip_h, flip_v = parse_native_transform(transform)
        if flip_h or flip_v:
            return None
        layout_w = float(node.styles.get("domoxmlLayoutWidth", node.width))
        layout_h = float(node.styles.get("domoxmlLayoutHeight", node.height))
        return unrotate_region(
            sharp_page,
            center_x=node.x + node.width / 2,
            center_y=node.y + node.height / 2,
            width=layout_w,
            height=layout_h,
            rotation_deg=rotation,
            scale=self._scale,
        )

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
            await context.add_init_script(RECORDER_JS)
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
            backdrops: dict[int, RenderedBackdrop] = {}
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
