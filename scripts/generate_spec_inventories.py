#!/usr/bin/env python
"""Regenerate the schema-derived sections of the OOXML inventory documents."""

from __future__ import annotations

import argparse
import hashlib
import io
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

ECMA_PAGE = "https://ecma-international.org/publications-and-standards/standards/ecma-376/"
SCHEMA_URL = (
    "https://ecma-international.org/wp-content/uploads/ECMA-376-4_5th_edition_december_2016.zip"
)
SCHEMA_ARCHIVE_SHA256 = "bd25da1109f73762356596918bf5ff8b74a1331642dba5f1c1d1dfc6bed34ecd"
SCHEMA_MEMBER = "OfficeOpenXML-XMLSchema-Transitional.zip"
XSD_ARCHIVE_SHA256 = "d34187520749998af306faf1b730e568b0ca6d88ad24638a407c0a9bb4ca04fc"

_XSD = "{http://www.w3.org/2001/XMLSchema}"
_BEGIN = "<!-- BEGIN GENERATED SCHEMA INVENTORY -->"
_END = "<!-- END GENERATED SCHEMA INVENTORY -->"
_SPEC_FILES = {
    "shared": "inventory-shared.md",
    "pptx": "inventory-pptx.md",
    "docx": "inventory-docx.md",
    "xlsx": "inventory-xlsx.md",
}
_PRIMARY_XSDS = {"pptx": "pml.xsd", "docx": "wml.xsd", "xlsx": "sml.xsd"}
_NAMESPACE_ALIASES = {
    "http://schemas.openxmlformats.org/drawingml/2006/chart": "c",
    "http://schemas.openxmlformats.org/drawingml/2006/chartDrawing": "cdr",
    "http://schemas.openxmlformats.org/drawingml/2006/compatibility": "dmlCompat",
    "http://schemas.openxmlformats.org/drawingml/2006/diagram": "dgm",
    "http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas": "lc",
    "http://schemas.openxmlformats.org/drawingml/2006/main": "a",
    "http://schemas.openxmlformats.org/drawingml/2006/picture": "pic",
    "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing": "xdr",
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing": "wp",
    "http://schemas.openxmlformats.org/officeDocument/2006/bibliography": "b",
    "http://schemas.openxmlformats.org/officeDocument/2006/characteristics": "ac",
    "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties": "cp",
    "http://schemas.openxmlformats.org/officeDocument/2006/customXml": "ds",
    "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes": "vt",
    "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties": "ep",
    "http://schemas.openxmlformats.org/officeDocument/2006/math": "m",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships": "r",
    "http://schemas.openxmlformats.org/officeDocument/2006/sharedTypes": "s",
    "http://schemas.openxmlformats.org/presentationml/2006/main": "p",
    "http://schemas.openxmlformats.org/schemaLibrary/2006/main": "sl",
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main": "x",
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main": "w",
    "urn:schemas-microsoft-com:office:excel": "xvml",
    "urn:schemas-microsoft-com:office:office": "o",
    "urn:schemas-microsoft-com:office:powerpoint": "pvml",
    "urn:schemas-microsoft-com:office:word": "wvml",
    "urn:schemas-microsoft-com:vml": "v",
}


@dataclass(frozen=True)
class SchemaElement:
    namespace: str
    name: str
    types: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class SchemaInventory:
    elements: tuple[SchemaElement, ...]
    declarations: int
    complex_types: int
    namespaces: tuple[str, ...]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_outer_archive(path: Path | None) -> bytes:
    if path is not None:
        return path.read_bytes()
    with urllib.request.urlopen(SCHEMA_URL, timeout=60) as response:
        return response.read()


def _load_xsds(path: Path | None) -> dict[str, bytes]:
    outer = _read_outer_archive(path)
    if _sha256(outer) != SCHEMA_ARCHIVE_SHA256:
        raise ValueError("ECMA-376 Part 4 archive SHA-256 does not match the pinned source")
    with zipfile.ZipFile(io.BytesIO(outer)) as archive:
        try:
            inner = archive.read(SCHEMA_MEMBER)
        except KeyError as exc:
            raise KeyError(f"missing expected archive member: {SCHEMA_MEMBER}") from exc
    if _sha256(inner) != XSD_ARCHIVE_SHA256:
        raise ValueError("ECMA-376 Transitional XSD archive SHA-256 does not match the pin")
    with zipfile.ZipFile(io.BytesIO(inner)) as archive:
        return {
            name: archive.read(name) for name in archive.namelist() if name.lower().endswith(".xsd")
        }


def _files_for(kind: str, xsds: dict[str, bytes]) -> tuple[str, ...]:
    if kind == "shared":
        excluded = set(_PRIMARY_XSDS.values())
        return tuple(sorted(name for name in xsds if name not in excluded))
    return (_PRIMARY_XSDS[kind],)


def _inventory(kind: str, xsds: dict[str, bytes]) -> SchemaInventory:
    declarations = 0
    complex_types = 0
    rows: dict[tuple[str, str], tuple[set[str], set[str]]] = defaultdict(lambda: (set(), set()))
    namespaces: set[str] = set()
    for source in _files_for(kind, xsds):
        try:
            xsd_bytes = xsds[source]
        except KeyError as exc:
            raise KeyError(f"missing expected XSD part: {source}") from exc
        root = ElementTree.fromstring(xsd_bytes)
        namespace = root.attrib.get("targetNamespace", "")
        namespaces.add(namespace)
        complex_types += len(root.findall(f".//{_XSD}complexType[@name]"))
        for element in root.findall(f".//{_XSD}element[@name]"):
            declarations += 1
            name = element.attrib["name"]
            element_type = element.attrib.get("type", "(anonymous)")
            types, sources = rows[(namespace, name)]
            types.add(element_type)
            sources.add(source)
    elements = tuple(
        SchemaElement(namespace, name, tuple(sorted(types)), tuple(sorted(sources)))
        for (namespace, name), (types, sources) in sorted(
            rows.items(),
            key=lambda item: (
                _NAMESPACE_ALIASES.get(item[0][0], item[0][0]),
                item[0][1].casefold(),
                item[0][1],
            ),
        )
    )
    return SchemaInventory(elements, declarations, complex_types, tuple(sorted(namespaces)))


def _generated_markdown(kind: str, inventory: SchemaInventory) -> str:
    namespace_label = "namespace" if len(inventory.namespaces) == 1 else "namespaces"
    lines = [
        _BEGIN,
        "## ECMA-376 Schema Surface",
        "",
        (
            "Generated by `scripts/generate_spec_inventories.py` from the official "
            "ECMA-376 5th edition Part 4 Transitional XSDs. The source archives are "
            "SHA-256 pinned in the generator."
        ),
        "",
        (
            f"This `{kind}` partition contains **{len(inventory.elements)} qualified element "
            f"names**, **{inventory.declarations} named declarations**, "
            f"**{inventory.complex_types} named complex types**, and "
            f"**{len(inventory.namespaces)} {namespace_label}**. Repeated declarations of one "
            "QName "
            "are combined and retain every declared type."
        ),
        "",
        (
            "This appendix is a discovery checklist, not an implementation percentage. One "
            "user-facing capability often uses several elements, and one element can participate "
            "in unrelated capabilities. Runtime status belongs in the curated tables above and "
            "in executable fixtures."
        ),
        "",
        f"Official standard: <{ECMA_PAGE}>",
        "",
        "### Namespace Legend",
        "",
        "| Prefix | Namespace |",
        "|---|---|",
    ]
    for namespace in inventory.namespaces:
        alias = _NAMESPACE_ALIASES.get(namespace, "(none)")
        lines.append(f"| `{alias}` | `{namespace}` |")
    lines.extend(
        [
            "",
            "### Elements",
            "",
            "| QName | Declared type(s) | Source XSD |",
            "|---|---|---|",
        ]
    )
    for element in inventory.elements:
        alias = _NAMESPACE_ALIASES.get(element.namespace, "?")
        types = "<br>".join(f"`{value}`" for value in element.types)
        sources = "<br>".join(f"`{value}`" for value in element.sources)
        lines.append(f"| `{alias}:{element.name}` | {types} | {sources} |")
    lines.extend([_END, ""])
    return "\n".join(lines)


def _replace_generated(document: str, generated: str) -> str:
    start = document.find(_BEGIN)
    if start < 0:
        raise ValueError("inventory document is missing generated-section markers")
    end = document.find(_END, start + len(_BEGIN))
    if end < 0:
        raise ValueError("inventory document is missing generated-section markers")
    end += len(_END)
    return document[:start] + generated.rstrip() + document[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, help="local ECMA-376 Part 4 ZIP instead of download"
    )
    parser.add_argument("--spec-dir", type=Path, default=Path("spec"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    xsds = _load_xsds(args.archive)
    stale: list[Path] = []
    for kind, filename in _SPEC_FILES.items():
        path = args.spec_dir / filename
        current = path.read_text(encoding="utf-8")
        expected = _replace_generated(current, _generated_markdown(kind, _inventory(kind, xsds)))
        if current == expected:
            continue
        if args.check:
            stale.append(path)
        else:
            path.write_text(expected, encoding="utf-8")
    if stale:
        for path in stale:
            print(f"stale: {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
