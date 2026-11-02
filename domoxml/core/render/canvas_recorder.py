"""Record a page's canvas 2D drawing calls so a canvas can leave as vector, not pixels.

A ``<canvas>`` is a bitmap, but the commands that drew it are not: ``fillRect``, ``arc``,
gradients and ``fillText`` all describe shapes. ``RECORDER_JS`` is injected before the page's own
scripts, wraps ``CanvasRenderingContext2D`` and keeps, per canvas, the SVG those commands add up
to. ``window.__domoxmlCanvas(canvas)`` returns that SVG at snapshot time, or ``null`` with a
reason when the canvas used something SVG cannot say exactly (patterns, shadows, compositing
modes, pixel reads and writes, WebGL). A canvas that cannot be recorded stays a raster and the
reason is reported, so nothing is ever approximated silently.

Paths are stored already transformed into canvas space (``getTransform()`` is read when each
point is added, exactly as a canvas does), and arcs become cubic Béziers, so the SVG needs no
transform tracking of its own.
"""

# ruff: noqa: E501  (embedded JavaScript, kept one statement per line)
from __future__ import annotations

RECORDER_JS = r"""
(() => {
  if (window.__domoxmlCanvas) return;
  const LIMIT = 20000;
  const TAU = Math.PI * 2;
  const logs = new WeakMap();
  const states = new WeakMap();
  const gradients = new WeakMap();
  const natives = {};
  const scratch = document.createElement('canvas').getContext('2d');
  const proto = CanvasRenderingContext2D.prototype;
  const n = (v) => Math.round(v * 1000) / 1000;

  const logFor = (canvas) => {
    let log = logs.get(canvas);
    if (!log) {
      log = { body: [], defs: [], open: 0, bad: null, count: 0, gid: 0, stack: [] };
      logs.set(canvas, log);
    }
    return log;
  };
  const reset = (log) => {
    log.body = []; log.defs = []; log.open = 0; log.count = 0; log.stack = [];
  };
  const resetAll = (log) => { reset(log); if (log.ctx) states.delete(log.ctx); };
  const bad = (log, why) => { if (!log.bad) log.bad = why; };
  const stateFor = (ctx) => {
    let s = states.get(ctx);
    if (!s) { s = { path: [], cur: null, start: null }; states.set(ctx, s); logFor(ctx.canvas).ctx = ctx; }
    return s;
  };
  const point = (ctx, x, y) => {
    const m = ctx.getTransform();
    return [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f];
  };
  const fmt = (p) => `${n(p[0])} ${n(p[1])}`;

  const addMove = (ctx, x, y) => {
    const s = stateFor(ctx);
    s.path.push(`M${fmt(point(ctx, x, y))}`);
    s.cur = [x, y]; s.start = [x, y];
  };
  const addLine = (ctx, x, y) => {
    const s = stateFor(ctx);
    if (!s.cur) return addMove(ctx, x, y);
    s.path.push(`L${fmt(point(ctx, x, y))}`);
    s.cur = [x, y];
  };
  const addCubic = (ctx, c1, c2, e) => {
    const s = stateFor(ctx);
    s.path.push(`C${fmt(point(ctx, c1[0], c1[1]))} ${fmt(point(ctx, c2[0], c2[1]))} ${fmt(point(ctx, e[0], e[1]))}`);
    s.cur = e;
  };
  // Arc of an ellipse as cubics, from angle a0 sweeping by `sweep` (signed radians).
  const addArc = (ctx, cx, cy, rx, ry, rot, a0, sweep) => {
    const cr = Math.cos(rot), sr = Math.sin(rot);
    const at = (t) => [cx + rx * Math.cos(t) * cr - ry * Math.sin(t) * sr, cy + rx * Math.cos(t) * sr + ry * Math.sin(t) * cr];
    const deriv = (t) => [-rx * Math.sin(t) * cr - ry * Math.cos(t) * sr, -rx * Math.sin(t) * sr + ry * Math.cos(t) * cr];
    const first = at(a0);
    if (stateFor(ctx).cur) addLine(ctx, first[0], first[1]); else addMove(ctx, first[0], first[1]);
    const count = Math.max(1, Math.ceil(Math.abs(sweep) / (Math.PI / 2) - 1e-9));
    const step = sweep / count;
    const k = 4 / 3 * Math.tan(step / 4);
    for (let i = 0; i < count; i++) {
      const t0 = a0 + i * step, t1 = t0 + step;
      const p0 = at(t0), p1 = at(t1), d0 = deriv(t0), d1 = deriv(t1);
      addCubic(ctx, [p0[0] + k * d0[0], p0[1] + k * d0[1]], [p1[0] - k * d1[0], p1[1] - k * d1[1]], p1);
    }
  };
  const sweepOf = (s, e, ccw) => {
    let d = e - s;
    if (!ccw && d >= TAU) return TAU;
    if (ccw && -d >= TAU) return -TAU;
    d = ((d % TAU) + TAU) % TAU;
    return ccw ? (d === 0 ? 0 : d - TAU) : d;
  };

  const color = (value) => {
    scratch.fillStyle = '#000'; scratch.fillStyle = value;
    const v = scratch.fillStyle;
    const m = /^rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?\)$/.exec(v);
    if (m) return { c: `rgb(${m[1]},${m[2]},${m[3]})`, a: m[4] === undefined ? 1 : parseFloat(m[4]) };
    return { c: v, a: 1 };
  };
  const matrixOf = (ctx) => { const m = ctx.getTransform(); return `matrix(${n(m.a)} ${n(m.b)} ${n(m.c)} ${n(m.d)} ${n(m.e)} ${n(m.f)})`; };

  // The SVG paint for a canvas fill or stroke style: [attribute value, opacity] or null if inexact.
  const paintOf = (log, ctx, style) => {
    if (typeof style === 'string') { const c = color(style); return [c.c, c.a]; }
    const g = gradients.get(style);
    if (!g) { bad(log, 'canvas pattern or unknown paint'); return null; }
    const id = `g${log.gid++}`;
    const stops = g.stops.map((s) => { const c = color(s[1]); return `<stop offset="${n(s[0])}" stop-color="${c.c}" stop-opacity="${c.a}"/>`; }).join('');
    const space = `gradientUnits="userSpaceOnUse" gradientTransform="${matrixOf(ctx)}"`;
    if (g.kind === 'linear') {
      log.defs.push(`<linearGradient id="${id}" ${space} x1="${n(g.a[0])}" y1="${n(g.a[1])}" x2="${n(g.a[2])}" y2="${n(g.a[3])}">${stops}</linearGradient>`);
    } else {
      log.defs.push(`<radialGradient id="${id}" ${space} fx="${n(g.a[0])}" fy="${n(g.a[1])}" fr="${n(g.a[2])}" cx="${n(g.a[3])}" cy="${n(g.a[4])}" r="${n(g.a[5])}">${stops}</radialGradient>`);
    }
    return [`url(#${id})`, 1];
  };

  const plain = (log, ctx) => {
    if (ctx.globalCompositeOperation !== 'source-over') bad(log, `globalCompositeOperation ${ctx.globalCompositeOperation}`);
    if (ctx.filter && ctx.filter !== 'none') bad(log, 'canvas filter');
    if (ctx.shadowBlur > 0 || ctx.shadowOffsetX !== 0 || ctx.shadowOffsetY !== 0) {
      if (color(ctx.shadowColor).a > 0) bad(log, 'canvas shadow');
    }
  };
  const emit = (ctx, markup) => {
    const log = logFor(ctx.canvas);
    if (++log.count > LIMIT) { bad(log, 'too many drawing operations'); return; }
    log.body.push(markup);
  };
  const dashOf = (ctx, scale) => {
    const dash = ctx.getLineDash();
    if (!dash.length) return '';
    return ` stroke-dasharray="${dash.map((d) => n(d * scale)).join(' ')}" stroke-dashoffset="${n(ctx.lineDashOffset * scale)}"`;
  };

  const paintPath = (ctx, d, mode, rule) => {
    const log = logFor(ctx.canvas);
    plain(log, ctx);
    if (!d) return;
    const alpha = ctx.globalAlpha < 1 ? ` opacity="${n(ctx.globalAlpha)}"` : '';
    if (mode === 'fill') {
      const p = paintOf(log, ctx, ctx.fillStyle);
      if (p) emit(ctx, `<path d="${d}" fill="${p[0]}" fill-opacity="${n(p[1])}" fill-rule="${rule}" stroke="none"${alpha}/>`);
    } else {
      const m = ctx.getTransform();
      const sx = Math.hypot(m.a, m.b), sy = Math.hypot(m.c, m.d);
      if (Math.abs(sx - sy) > 0.01 * Math.max(sx, sy)) { bad(log, 'stroke under non-uniform scale'); return; }
      const p = paintOf(log, ctx, ctx.strokeStyle);
      if (p) emit(ctx, `<path d="${d}" fill="none" stroke="${p[0]}" stroke-opacity="${n(p[1])}" stroke-width="${n(ctx.lineWidth * sx)}" stroke-linecap="${ctx.lineCap === 'butt' ? 'butt' : ctx.lineCap}" stroke-linejoin="${ctx.lineJoin}" stroke-miterlimit="${n(ctx.miterLimit)}"${dashOf(ctx, sx)}${alpha}/>`);
    }
  };
  const rectD = (ctx, x, y, w, h) => `M${fmt(point(ctx, x, y))}L${fmt(point(ctx, x + w, y))}L${fmt(point(ctx, x + w, y + h))}L${fmt(point(ctx, x, y + h))}Z`;
  const fullCanvas = (ctx, x, y, w, h) => {
    const m = ctx.getTransform();
    return m.a === 1 && m.b === 0 && m.c === 0 && m.d === 1 && m.e === 0 && m.f === 0 && x <= 0 && y <= 0 && x + w >= ctx.canvas.width && y + h >= ctx.canvas.height;
  };

  const wrap = (name, fn) => {
    const original = proto[name];
    if (typeof original !== 'function') return;
    natives[name] = original;
    proto[name] = function (...args) {
      try { fn.call(this, args); } catch (e) { bad(logFor(this.canvas), `recorder error in ${name}`); }
      return original.apply(this, args);
    };
  };

  wrap('beginPath', function () { const s = stateFor(this); s.path = []; s.cur = null; s.start = null; });
  wrap('moveTo', function (a) { addMove(this, a[0], a[1]); });
  wrap('lineTo', function (a) { addLine(this, a[0], a[1]); });
  wrap('closePath', function () { const s = stateFor(this); if (s.cur) { s.path.push('Z'); s.cur = s.start; } });
  wrap('bezierCurveTo', function (a) { if (!stateFor(this).cur) addMove(this, a[0], a[1]); addCubic(this, [a[0], a[1]], [a[2], a[3]], [a[4], a[5]]); });
  wrap('quadraticCurveTo', function (a) {
    const s = stateFor(this);
    if (!s.cur) addMove(this, a[0], a[1]);
    const [x0, y0] = s.cur;
    addCubic(this, [x0 + 2 / 3 * (a[0] - x0), y0 + 2 / 3 * (a[1] - y0)], [a[2] + 2 / 3 * (a[0] - a[2]), a[3] + 2 / 3 * (a[1] - a[3])], [a[2], a[3]]);
  });
  wrap('arc', function (a) { addArc(this, a[0], a[1], a[2], a[2], 0, a[3], sweepOf(a[3], a[4], a[5])); });
  wrap('ellipse', function (a) { addArc(this, a[0], a[1], a[2], a[3], a[4], a[5], sweepOf(a[5], a[6], a[7])); });
  wrap('arcTo', function (a) {
    const s = stateFor(this);
    const [x1, y1, x2, y2, r] = a;
    if (!s.cur) { addMove(this, x1, y1); return; }
    const [x0, y0] = s.cur;
    const v0 = [x0 - x1, y0 - y1], v2 = [x2 - x1, y2 - y1];
    const l0 = Math.hypot(...v0), l2 = Math.hypot(...v2);
    const cross = v0[0] * v2[1] - v0[1] * v2[0];
    if (l0 === 0 || l2 === 0 || r === 0 || Math.abs(cross) < 1e-9 * l0 * l2) { addLine(this, x1, y1); return; }
    const u0 = [v0[0] / l0, v0[1] / l0], u2 = [v2[0] / l2, v2[1] / l2];
    const angle = Math.acos(Math.max(-1, Math.min(1, u0[0] * u2[0] + u0[1] * u2[1])));
    const t = r / Math.tan(angle / 2);
    const t0 = [x1 + u0[0] * t, y1 + u0[1] * t], t2 = [x1 + u2[0] * t, y1 + u2[1] * t];
    const bis = [u0[0] + u2[0], u0[1] + u2[1]], bl = Math.hypot(...bis);
    const d = r / Math.sin(angle / 2);
    const c = [x1 + bis[0] / bl * d, y1 + bis[1] / bl * d];
    const a0 = Math.atan2(t0[1] - c[1], t0[0] - c[0]), a1 = Math.atan2(t2[1] - c[1], t2[0] - c[0]);
    let sweep = a1 - a0;
    while (sweep > Math.PI) sweep -= TAU;
    while (sweep < -Math.PI) sweep += TAU;
    addArc(this, c[0], c[1], r, r, 0, a0, sweep);
  });
  wrap('rect', function (a) {
    const [x, y, w, h] = a;
    addMove(this, x, y); addLine(this, x + w, y); addLine(this, x + w, y + h); addLine(this, x, y + h);
    stateFor(this).path.push('Z'); stateFor(this).cur = [x, y];
  });
  wrap('roundRect', function (a) {
    const [x, y, w, h] = a;
    const radii = [].concat(a[4] === undefined ? 0 : a[4]);
    if (radii.some((r) => typeof r !== 'number') || w < 0 || h < 0) { bad(logFor(this.canvas), 'roundRect radii'); return; }
    const [tl, tr, br, bl] = radii.length === 1 ? [radii[0], radii[0], radii[0], radii[0]] : radii.length === 2 ? [radii[0], radii[1], radii[0], radii[1]] : radii.length === 3 ? [radii[0], radii[1], radii[2], radii[1]] : radii;
    addMove(this, x + tl, y); addLine(this, x + w - tr, y);
    addArc(this, x + w - tr, y + tr, tr, tr, 0, -Math.PI / 2, Math.PI / 2);
    addLine(this, x + w, y + h - br);
    addArc(this, x + w - br, y + h - br, br, br, 0, 0, Math.PI / 2);
    addLine(this, x + bl, y + h);
    addArc(this, x + bl, y + h - bl, bl, bl, 0, Math.PI / 2, Math.PI / 2);
    addLine(this, x, y + tl);
    addArc(this, x + tl, y + tl, tl, tl, 0, Math.PI, Math.PI / 2);
    stateFor(this).path.push('Z'); stateFor(this).cur = [x + tl, y];
  });

  const pathArgs = (ctx, args, fn) => {
    const log = logFor(ctx.canvas);
    if (args[0] && typeof args[0] === 'object') { bad(log, 'Path2D drawing'); return; }
    fn(args[0] === 'evenodd' ? 'evenodd' : 'nonzero');
  };
  wrap('fill', function (a) { pathArgs(this, a, (rule) => paintPath(this, stateFor(this).path.join(''), 'fill', rule)); });
  wrap('stroke', function (a) { if (a[0]) { bad(logFor(this.canvas), 'Path2D drawing'); return; } paintPath(this, stateFor(this).path.join(''), 'stroke', 'nonzero'); });
  wrap('fillRect', function (a) { paintPath(this, rectD(this, a[0], a[1], a[2], a[3]), 'fill', 'nonzero'); });
  wrap('strokeRect', function (a) { paintPath(this, rectD(this, a[0], a[1], a[2], a[3]), 'stroke', 'nonzero'); });
  wrap('clearRect', function (a) {
    const log = logFor(this.canvas);
    if (!log.open && !log.stack.length && fullCanvas(this, a[0], a[1], a[2], a[3])) { reset(log); return; }
    if (log.body.length) bad(log, 'partial clearRect');
  });
  wrap('clip', function (a) {
    const log = logFor(this.canvas);
    if (a[0] && typeof a[0] === 'object') { bad(log, 'Path2D clip'); return; }
    const id = `c${log.gid++}`;
    log.defs.push(`<clipPath id="${id}"><path d="${stateFor(this).path.join('')}" clip-rule="${a[0] === 'evenodd' ? 'evenodd' : 'nonzero'}"/></clipPath>`);
    log.body.push(`<g clip-path="url(#${id})">`);
    log.open++;
  });
  wrap('save', function () { logFor(this.canvas).stack.push(logFor(this.canvas).open); });
  wrap('restore', function () {
    const log = logFor(this.canvas);
    if (!log.stack.length) return;
    const to = log.stack.pop();
    while (log.open > to) { log.body.push('</g>'); log.open--; }
  });
  wrap('reset', function () { resetAll(logFor(this.canvas)); });

  // ctx.font is a CSS shorthand; SVG consumers read the longhand attributes far more reliably.
  const fontAttributes = (font) => {
    const m = /^(.*?)([\d.]+)px(?:\/[^ ]+)? (.+)$/.exec(font);
    if (!m) return `style="font:${font.replace(/"/g, "'")}"`;
    const words = m[1].trim().split(/\s+/).filter(Boolean);
    const style = words.find((w) => w === 'italic' || w === 'oblique') || 'normal';
    const weight = words.find((w) => w === 'bold' || /^[1-9]00$/.test(w)) || 'normal';
    const family = m[3].replace(/"/g, "'");
    return `font-style="${style}" font-weight="${weight}" font-size="${m[2]}" font-family="${family}"`;
  };
  const textOf = (ctx, args, mode) => {
    const log = logFor(ctx.canvas);
    plain(log, ctx);
    if (args[3] !== undefined) { bad(log, 'fillText maxWidth'); return; }
    const anchors = { start: 'start', left: 'start', center: 'middle', right: 'end', end: 'end' };
    const baselines = { alphabetic: 'alphabetic', top: 'text-before-edge', hanging: 'hanging', middle: 'central', ideographic: 'ideographic', bottom: 'text-after-edge' };
    const p = paintOf(log, ctx, mode === 'fill' ? ctx.fillStyle : ctx.strokeStyle);
    if (!p) return;
    const escaped = String(args[0]).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const paint = mode === 'fill'
      ? `fill="${p[0]}" fill-opacity="${n(p[1])}"`
      : `fill="none" stroke="${p[0]}" stroke-opacity="${n(p[1])}" stroke-width="${n(ctx.lineWidth)}"`;
    emit(ctx, `<text transform="${matrixOf(ctx)}" x="${n(args[1])}" y="${n(args[2])}" ${fontAttributes(ctx.font)} xml:space="preserve" text-anchor="${anchors[ctx.textAlign]}" dominant-baseline="${baselines[ctx.textBaseline]}" ${paint}${ctx.globalAlpha < 1 ? ` opacity="${n(ctx.globalAlpha)}"` : ''}>${escaped}</text>`);
  };
  wrap('fillText', function (a) { textOf(this, a, 'fill'); });
  wrap('strokeText', function (a) { textOf(this, a, 'stroke'); });

  wrap('drawImage', function (a) {
    const log = logFor(this.canvas);
    plain(log, this);
    const src = a[0];
    let w = src.naturalWidth || src.videoWidth || src.width, h = src.naturalHeight || src.videoHeight || src.height;
    if (src instanceof HTMLVideoElement) { bad(log, 'drawImage of a video'); return; }
    let url;
    try {
      const tmp = document.createElement('canvas'); tmp.width = w; tmp.height = h;
      natives.drawImage.call(tmp.getContext('2d'), src, 0, 0);
      url = tmp.toDataURL('image/png');
    } catch (e) { bad(log, 'drawImage of a tainted or unreadable source'); return; }
    const smooth = this.imageSmoothingEnabled ? '' : ' style="image-rendering:pixelated"';
    const alpha = this.globalAlpha < 1 ? ` opacity="${n(this.globalAlpha)}"` : '';
    const image = `<image href="${url}" width="${w}" height="${h}" preserveAspectRatio="none"${smooth}/>`;
    if (a.length === 9) {
      const [, sx, sy, sw, sh, dx, dy, dw, dh] = a;
      emit(this, `<g transform="${matrixOf(this)}"${alpha}><svg x="${n(dx)}" y="${n(dy)}" width="${n(dw)}" height="${n(dh)}" viewBox="${n(sx)} ${n(sy)} ${n(sw)} ${n(sh)}" preserveAspectRatio="none" overflow="hidden">${image}</svg></g>`);
    } else {
      const dw = a.length === 5 ? a[3] : w, dh = a.length === 5 ? a[4] : h;
      emit(this, `<g transform="${matrixOf(this)}"${alpha}><svg x="${n(a[1])}" y="${n(a[2])}" width="${n(dw)}" height="${n(dh)}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" overflow="hidden">${image}</svg></g>`);
    }
  });
  for (const name of ['putImageData', 'createPattern', 'drawFocusIfNeeded']) {
    wrap(name, function () { bad(logFor(this.canvas), name); });
  }
  wrap('createConicGradient', function () { bad(logFor(this.canvas), 'conic gradient'); });

  const original = { linear: proto.createLinearGradient, radial: proto.createRadialGradient };
  const track = (kind, make) => function (...args) {
    const gradient = make.apply(this, args);
    const info = { kind, a: args, stops: [] };
    gradients.set(gradient, info);
    const add = gradient.addColorStop.bind(gradient);
    gradient.addColorStop = (offset, value) => { info.stops.push([offset, value]); return add(offset, value); };
    return gradient;
  };
  proto.createLinearGradient = track('linear', original.linear);
  proto.createRadialGradient = track('radial', original.radial);

  // Resizing a canvas clears it; anything that is not the 2D context cannot be recorded.
  for (const side of ['width', 'height']) {
    const d = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, side);
    Object.defineProperty(HTMLCanvasElement.prototype, side, {
      ...d,
      set(value) { resetAll(logFor(this)); d.set.call(this, value); },
    });
  }
  const getContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
    if (type !== '2d') bad(logFor(this), `${type} canvas context`);
    return getContext.call(this, type, ...rest);
  };

  window.__domoxmlCanvas = (canvas) => {
    const log = logs.get(canvas);
    if (!log) return { svg: null, reason: 'canvas was never drawn to' };
    if (log.bad) return { svg: null, reason: log.bad };
    const close = '</g>'.repeat(log.open);
    const { width, height } = canvas;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><defs>${log.defs.join('')}</defs>${log.body.join('')}${close}</svg>`;
    let png = null;
    try { png = canvas.toDataURL('image/png'); } catch (e) { return { svg: null, reason: 'canvas is tainted' }; }
    return { svg, png, reason: null };
  };
})();
"""
