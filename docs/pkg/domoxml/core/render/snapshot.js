
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
          text = text.replace(/\s+/g, ' ');
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
        runs.push({ text: '\n', styles });
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
        runs.push({ text: '\n', styles: pick(rootStyle) });
      }
    }
    if (consolidateFlex && runs.at(-1)?.text === '\n') runs.pop();
    return runs.some((run) => run.text.trim()) ? runs : [];
  };
  const out = [];
  const walk = (el, parent) => {
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
      const filterMatch = filterRef.match(/^url\(\s*['"]?#([^'")]+)['"]?\s*\)$/i);
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
    for (const child of el.children) walk(child, index);
  };
  walk(document.body, -1);
  return out;
}
