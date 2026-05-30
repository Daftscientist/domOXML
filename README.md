# domOXML

**Transpile HTML/CSS into editable OOXML — PowerPoint first.**

domOXML turns a slide written in plain HTML/CSS into a native, *editable* `.pptx`
(real shapes and text — not a flat image), plus matching PNGs and a normalized HTML
form. Design with the richest styling system there is, and ship a file people can open
and edit in PowerPoint.

> ⚠️ **Alpha — early development.** The API will change, and it's not on PyPI yet.

## Install

Not on PyPI yet — install from source while it's in alpha:

```bash
git clone https://github.com/Daftscientist/domOXML
cd domOXML
pip install -e .
playwright install chromium   # the rendering engine domOXML drives
```

## Example

```python
from pathlib import Path

from domoxml import Presentation, Slide
from domoxml.types import OutputFormat, SlideSize

deck = Presentation(size=SlideSize.WIDE_16_9)
deck.add(Slide(html="<h1>Coffee that tastes like <span>calm</span>.</h1>"))

result = deck.render({OutputFormat.PPTX, OutputFormat.PNG})
result.save(Path("out/"))
```

> The API above is the target surface, landing incrementally during alpha.

## Why

- **Editable, not flat** — elements map to native DrawingML shapes and text; only
  genuinely un-mappable flourish is rasterised, layered *behind* editable content.
- **Beauty is just CSS** — author any style you like; no templates, no lock-in.
- **One source, many outputs** — `.pptx`, `.png`, and normalized HTML from a single render.

## Requirements

- Python 3.12+
- Chromium (installed via `playwright install chromium`) — the CSS layout/render engine.
- LibreOffice is *optional*, used only for the opt-in fidelity check.

## License

MIT © Leo Johnston
