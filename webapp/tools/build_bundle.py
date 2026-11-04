#!/usr/bin/env python3
"""Build the trimmed domOXML bundle the web app loads into Pyodide.

The old demo shipped 553 loose files under docs/pkg/ and fetched every one
individually at boot. This builder produces ONE zip instead:

- the ``domoxml`` package, minus the desktop-only machinery the web flows
  never touch (fidelity scoring, real-deck corpus, the Node Takumi worker);
- ``defusedxml`` (pure Python, not shipped by Pyodide);
- a ``playwright`` stub, because ``core/render/browser.py`` imports it at
  module level while the web build never starts a browser (Takumi is the
  render backend here). Any real use of the stub raises.

The zip is content-hashed: ``domoxml-bundle-<sha8>.zip`` plus a
``bundle-manifest.json``, so the service worker and HTTP cache can treat a
new build as a new versioned asset and never serve a stale mix.

Usage: build_bundle.py [--repo PATH] [--out DIR] [--defusedxml PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

EXCLUDED_PREFIXES = (
    "domoxml/core/fidelity/",
    "domoxml/core/render/takumi/",
)
EXCLUDED_FILES = {
    "domoxml/core/real_decks.py",
}
INCLUDED_SUFFIXES = (".py", ".xml", ".js", ".json", ".typed")

PLAYWRIGHT_STUB_INIT = '"""Stub for the web bundle: Playwright is never used here."""\n'
PLAYWRIGHT_STUB_ASYNC_API = '''"""Import-time stub for ``playwright.async_api`` (web bundle only).

``domoxml.core.render.browser`` imports these names at module level. The web
build renders with Takumi instead of Chromium, so the names exist purely to
satisfy the import; constructing or calling any of them raises.
"""

from __future__ import annotations


class _Unavailable:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("Playwright is not available in the web build; Takumi is the render backend")


Browser = _Unavailable
Page = _Unavailable
Playwright = _Unavailable
Route = _Unavailable


def async_playwright():
    raise RuntimeError("Playwright is not available in the web build; Takumi is the render backend")
'''


def collect(repo: Path, defusedxml_dir: Path) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    pkg = repo / "domoxml"
    for path in sorted(pkg.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(EXCLUDED_PREFIXES) or rel in EXCLUDED_FILES:
            continue
        if path.suffix not in INCLUDED_SUFFIXES and path.name != "py.typed":
            continue
        files.append((rel, path.read_bytes()))
    for path in sorted(defusedxml_dir.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix == ".py":
            rel = path.relative_to(defusedxml_dir.parent).as_posix()
            files.append((rel, path.read_bytes()))
    files.append(("playwright/__init__.py", PLAYWRIGHT_STUB_INIT.encode()))
    files.append(("playwright/async_api.py", PLAYWRIGHT_STUB_ASYNC_API.encode()))
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--defusedxml", type=Path, default=None)
    args = parser.parse_args()

    defusedxml_dir = args.defusedxml
    if defusedxml_dir is None:
        import defusedxml

        defusedxml_dir = Path(defusedxml.__file__).parent

    files = collect(args.repo, defusedxml_dir)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, data in files:
            info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    blob = buffer.getvalue()
    sha = hashlib.sha256(blob).hexdigest()

    args.out.mkdir(parents=True, exist_ok=True)
    name = f"domoxml-bundle-{sha[:8]}.zip"
    (args.out / name).write_bytes(blob)
    manifest = {
        "bundle": name,
        "sha256": sha,
        "files": len(files),
        "bytes": len(blob),
        "pyodide": "0.29.3",
        "packages_eager": ["pydantic", "lxml", "pillow", "fonttools"],
    }
    (args.out / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {name}: {len(files)} files, {len(blob)} bytes, sha256 {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
