# Experimental Takumi rendering backend

domOXML can render HTML and inline CSS through Chromium (the default) or
[Takumi](https://takumi.kane.tw/docs/paint), an embeddable, browserless Rust
renderer with a paint-tree API. Takumi support is **opt-in and experimental**.

## Install

Requires Node.js 20.19+ on the host. From the repository root:

    npm install --prefix domoxml/core/render/takumi

The optional packages are pinned in
domoxml/core/render/takumi/package.json. They are not required for Chromium.

## Use

    from domoxml import Presentation, Slide
    from domoxml.types import OutputFormat

    deck = Presentation(render_engine="takumi")
    deck.add(Slide(html="<div style='background:#4f46e5;color:white'>Hello</div>"))
    output = deck.render({OutputFormat.PNG, OutputFormat.PPTX})
    print(output.coverage, output.warnings)

The engine is selected on each Presentation, not globally; the Chromium path
and its tests remain unchanged.

## Important limitations

This first backend uses takumi-js for the authoritative raster and
takumi-paint for ordered paint operations. Solid rectangular fills and
straightforward text runs can become editable OOXML objects. It does **not**
yet cover the full paint vocabulary (gradients, rounded geometry, complex
transforms, clipping, opacity groups, shadows, masks, blend effects, SVG, etc.).
When the paint tree contains anything outside the proven mapping, domOXML
emits **one entire-slide raster** and marks it rasterized/noneditable in
the normal coverage report. This is deliberate: cropping the original full
screenshot for an unsupported node can duplicate unrelated native content.

The Node bridge does not run HTML scripts. Fonts must be supplied explicitly
to Takumi for non-Geist faces. Until a font-registration API is added to this
bridge, unsupported or absent fonts may differ from Chromium. Remote assets
are not supported by the optional backend. Use inline/data assets, and do not
treat this experimental worker as an untrusted-document security sandbox.

## Failures and diagnostics

If Takumi cannot parse a CSS value (for example, a composite transform that
its style parser rejects), its exact message is preserved as
TakumiRenderError(stage="paint", message=...) and bubbles out of
render() / arender(). Setup, transport and timeout failures use the same
exception with different stage values. Fatal engine failures **must not**
be converted to ConversionWarning or silently trigger Chromium.

A successfully painted document that needs an unavailable OOXML mapping
is different: it renders with a full-slide raster, is marked noneditable in
CoverageReport, and adds a ConversionWarning identifying the paint feature.

## Next steps

- Support additional paint-tree drawables as editable OOXML nodes.
- Add an owned paint-step replay pipeline for isolated transparent fallbacks.
- Expose font registration and deterministic image/resource loading.
- Benchmark and compare Takumi versus Chromium for the existing capability
  and real-deck fixtures before changing any default.
