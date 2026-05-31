# domOXML

**Transpile HTML/CSS into editable OOXML — PowerPoint first.**

domOXML turns a slide written in plain HTML/CSS into a native, *editable* `.pptx` —
real shapes and text, not a flat screenshot — plus matching PNGs. Design with the
richest styling system there is, and ship a file people can open and edit in PowerPoint.

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

result = deck.render({OutputFormat.PPTX, OutputFormat.PNG, OutputFormat.HTML})
result.save(Path("out/"))
```

Read an existing deck into deterministic per-slide HTML/CSS:

```python
from domoxml import pptx_to_html

html = pptx_to_html(Path("deck.pptx"))
html.save(Path("out/html"))
```

## Why

- **Editable, not flat** — text, fills (solid / gradient / image), borders, shadows and
  basic geometry map to native DrawingML. Only genuinely un-mappable flourish (CSS
  filters, blend modes, clip paths, rotation, `<svg>`/`<canvas>`) is rasterised, layered
  *behind* the editable content.
- **Beauty is just CSS** — author any style you like; no templates, no lock-in. Fonts the
  deck uses are embedded so it looks right on machines that don't have them.
- **Nothing dropped silently** — every element is accounted for in a coverage report, and
  every approximation or raster emits a warning, so you always know what was lossy.

## Requirements

- Python 3.12+
- Chromium (installed via `playwright install chromium`) — the CSS layout/render engine.
- LibreOffice is *optional*, used only for the opt-in fidelity check.

## Development

Install the dev extras (linters, type-checker, tests) and enable the git hooks once:

```bash
pip install -e ".[dev]"
git config core.hooksPath .githooks   # run the CI gate before every push
```

### Optional: Microsoft Graph fidelity backend (BYO credentials)

Install the Graph extra, copy the example env file, and provide your own Azure app values:

```bash
pip install -e ".[dev,graph]"
cp .env.example .env
```

First-time auth stores a token cache outside the repo (`~/.cache/domoxml/...` by default):

```bash
python -c "from domoxml.core.fidelity import device_login; device_login()"
```

Then run the fidelity checker locally:

```bash
uv run python scripts/fidelity_check.py --backend graph --heatmap
uv run python scripts/fidelity_check.py --backend both --heatmap
```

The `pre-push` hook runs the exact CI checks — `ruff check`, `ruff format --check`,
`pyright`, and `pytest` — so anything CI would reject is caught before it leaves your
machine. Run them by hand any time:

```bash
ruff check . && ruff format --check . && pyright && pytest
```

The fidelity checker is intentionally not part of auto-running git hooks (it can be slow and
requires browser/network tooling). If you want to run it on push locally, use the opt-in helper
in `.githooks/pre-push.graph.example`.

## License

MIT © Leo Johnston
