"""Serialize a set of named parts into an OPC (OOXML) package — a deflated ZIP."""

from __future__ import annotations

import io
import zipfile


def write_package(parts: dict[str, bytes | str]) -> bytes:
    """Write ``{part_path: content}`` to an OPC ZIP and return the bytes.

    ``part_path`` is the in-package path (e.g. ``"[Content_Types].xml"``,
    ``"ppt/slides/slide1.xml"``). The caller supplies every part, including
    ``[Content_Types].xml`` and the relationship parts. Strings are UTF-8 encoded.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in parts.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(path, data)
    return buffer.getvalue()
