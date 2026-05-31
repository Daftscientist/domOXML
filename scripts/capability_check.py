#!/usr/bin/env python
"""Render isolated HTML capability fixtures and assert editable OOXML structure."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from domoxml.core.capabilities import load_capabilities, validate_capability
from domoxml.presentation import Presentation, Slide
from domoxml.types import OutputFormat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("capabilities/pptx"))
    args = parser.parse_args(argv)

    fixtures = load_capabilities(args.fixtures)
    if not fixtures:
        print(f"no capability fixtures found under {args.fixtures}", file=sys.stderr)
        return 1

    failures = 0
    for fixture in fixtures:
        deck = Presentation().add(Slide(html=fixture.html))
        result = deck.render({OutputFormat.PPTX})
        errors = validate_capability(fixture, result)
        if errors:
            failures += 1
            print(f"FAIL {fixture.id}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"ok   {fixture.id}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
