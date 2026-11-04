#!/usr/bin/env python3
"""Assemble the deployable site into the repo's docs/ folder (web branch).

Runs the Vite production build, then copies dist/ into docs/ so GitHub
Pages can serve the app from the branch's /docs. The service worker is
stamped with the Python bundle's content hash, so each new bundle build
rolls the cache version and stale assets are dropped on activate.

Usage: assemble_site.py [--repo PATH]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    webapp = args.repo / "webapp"
    docs = args.repo / "docs"

    if not args.skip_build:
        subprocess.run(["npm", "run", "build"], cwd=webapp, check=True)

    dist = webapp / "dist"
    if not dist.is_dir():
        print("dist/ missing; run the Vite build first", file=sys.stderr)
        return 1

    manifest = json.loads((dist / "py" / "bundle-manifest.json").read_text())
    stamp = manifest["sha256"][:8]

    # Remove the previous app payload, keep the repo's own docs files.
    for name in ("index.html", "assets", "py", "sw.js", "favicon.svg"):
        target = docs / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    for item in dist.rglob("*"):
        rel = item.relative_to(dist)
        if rel.parts and rel.parts[0] == "pyodide":
            continue  # local test mirror only; production loads Pyodide from the CDN
        dest = docs / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    sw = docs / "sw.js"
    sw.write_text(sw.read_text().replace("__BUILD__", stamp))
    (docs / ".nojekyll").touch()
    print(f"assembled docs/ (service worker cache domoxml-studio-{stamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
