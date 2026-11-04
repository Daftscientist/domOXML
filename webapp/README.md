# domOXML Studio (web app)

The browser workspace for domOXML: author a presentation as HTML, watch each
slide render live, present it, open existing .pptx files, and export an
editable PowerPoint. Everything runs on the device. There is no server and
no upload: the Python package runs in Pyodide (WebAssembly CPython) and
slides are rendered by [Takumi](https://github.com/kane50613/takumi), never
by the host page's DOM.

## How it fits together

- `src/` — React + shadcn UI. It boots and is fully interactive before any
  Python loads; the engine warms up in the background and the header shows
  its status.
- `src/worker/engine.worker.ts` — a module worker that loads Pyodide 0.29.3
  with the package's Python dependencies declared up front
  (`loadPyodide({ packages })`), so the runtime and the packages download
  as one initialisation instead of sequential passes. It then unpacks the
  domOXML bundle and answers `preview`, `convert` and `readDeck` RPCs.
- `bridge/takumi-bridge.mjs` — the Takumi renderer (paint + WASM raster)
  exposed to Python as the async global `domoxmlTakumiBridge`, which is the
  transport `domoxml.core.render.takumi_backend` uses under Pyodide. The
  same bridge module is used by the Node test harness.
- `py/boot.py` — worker-side bootstrap: puts the bundle on `sys.path` and
  exposes `domoxml.web` (preview / convert / read_deck) as `domoxml_api`.
- `tools/build_bundle.py` — builds the content-hashed Python bundle
  (`public/py/domoxml-bundle-<hash>.zip` + `bundle-manifest.json`). Test and
  development files are excluded; a stub stands in for Playwright, whose
  import the package performs at module load but never calls in the browser
  (rendering is Takumi's job here).
- `public/sw.js` — service worker. Content-hashed assets, the bundle and
  the version-pinned Pyodide CDN files are cache-first, so a repeat visit
  downloads nothing; HTML and the bundle manifest are network-first so new
  deployments land on the next load. The cache name is stamped with the
  bundle hash at assembly time.
- `tools/assemble_site.py` — production build + assembly of the repo's
  `docs/` folder for GitHub Pages.

The Pyodide runtime itself loads from the jsDelivr CDN, pinned to
v0.29.3. A `?pyodide=<url>` query parameter can point the engine at a
mirrored runtime (used for offline development and testing).

## Develop

```sh
npm install
npm run dev          # Vite dev server; engine loads Pyodide from the CDN
npm run test:node    # end-to-end engine test under Node (no browser)
npm run build        # production build into dist/
python3 tools/build_bundle.py --out public/py   # after changing domoxml source
python3 tools/assemble_site.py                  # build + assemble ../docs
```
