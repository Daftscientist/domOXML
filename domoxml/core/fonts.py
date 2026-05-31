"""Resolve the fonts a deck actually uses to embeddable TrueType faces.

Two sources, in order: the **web fonts the render fetched** (``@font-face``/``<link>`` —
identified by reading each captured file's name table), then **system fonts** via fontconfig.
Whatever the source format (ttf/otf/woff/woff2) it is normalised to embeddable TrueType.
Concrete families only — generics like ``sans-serif`` are skipped — and a system match is
only trusted when fontconfig returns the *requested* family, never a substitute. Any concrete
family that can't be resolved or embedded yields a :class:`ConversionWarning`; nothing is
silently substituted.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from domoxml.core.fontconvert import face_identity, to_embeddable_ttf
from domoxml.core.ir.model import SlideIR
from domoxml.types import ConversionWarning

_GENERIC = {
    "sans-serif",
    "serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-sans-serif",
    "ui-serif",
    "ui-monospace",
    "ui-rounded",
    "emoji",
    "math",
    "fangsong",
    "inherit",
    "initial",
    "revert",
    "unset",
    "",
}

FaceKey = tuple[str, bool, bool]


class FontFace(BaseModel):
    """One concrete font face used by the deck, plus its embeddable TrueType bytes."""

    model_config = ConfigDict(frozen=True)

    family: str
    bold: bool
    italic: bool
    data: bytes


def _resolve_system_file(family: str, *, bold: bool, italic: bool) -> Path | None:
    """Ask fontconfig for the file backing ``family`` (any format), or ``None`` if it would
    substitute a different family."""
    fc = shutil.which("fc-match")
    if fc is None:
        return None
    query = family
    traits = [t for t, on in (("weight=bold", bold), ("slant=italic", italic)) if on]
    if traits:
        query = f"{family}:" + ":".join(traits)
    try:
        out = subprocess.run(
            [fc, "-f", "%{family}\t%{file}", query],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    matched_family, _, file = out.partition("\t")
    # Exact token match: normalize both, split matched into tokens, check for equality
    family_norm = family.strip().strip('"').strip("'").lower()
    matched_norm = matched_family.strip().strip('"').strip("'").lower()
    # Split matched_family into tokens (by comma and whitespace)
    matched_tokens = [token.strip() for part in matched_norm.split(",") for token in part.split()]
    if family_norm not in matched_tokens:
        return None  # fontconfig fell back to a substitute — don't embed the wrong font
    path = Path(file.strip())
    return path if path.is_file() else None


def _web_index(captured_fonts: dict[str, bytes]) -> dict[FaceKey, bytes]:
    """Index captured web-font bytes by ``(family.lower(), bold, italic)`` via their names."""
    index: dict[FaceKey, bytes] = {}
    for data in captured_fonts.values():
        identity = face_identity(data)
        if identity is None:
            continue
        family, bold, italic = identity
        index.setdefault((family.lower(), bold, italic), data)
    return index


def _raw_bytes(key: FaceKey, web_index: dict[FaceKey, bytes]) -> bytes | None:
    """The best source bytes for a used face: exact web font, then its regular web weight,
    then the system file. ``None`` means the family isn't available anywhere."""
    family, bold, italic = key
    lower = family.lower()
    if (lower, bold, italic) in web_index:
        return web_index[(lower, bold, italic)]
    if (lower, False, False) in web_index:
        return web_index[(lower, False, False)]
    path = _resolve_system_file(family, bold=bold, italic=italic)
    return path.read_bytes() if path is not None else None


def _used_faces(slides: list[SlideIR]) -> list[FaceKey]:
    seen: list[FaceKey] = []
    known: set[FaceKey] = set()
    for slide in slides:
        for shape in slide.shapes:
            run = shape.text
            if run is None or run.font_family.strip().lower() in _GENERIC:
                continue
            key = (run.font_family.strip(), run.bold, run.italic)
            if key not in known:
                known.add(key)
                seen.append(key)
    return seen


def resolve_faces(
    slides: list[SlideIR], *, captured_fonts: dict[str, bytes] | None = None
) -> tuple[list[FontFace], list[ConversionWarning]]:
    """Resolve every concrete (family, bold, italic) the slides use to an embeddable face.

    Returns the faces plus a warning for each family that couldn't be resolved or embedded —
    so an un-embeddable font is surfaced, never silently dropped.
    """
    web_index = _web_index(captured_fonts or {})
    faces: list[FontFace] = []
    warnings: list[ConversionWarning] = []
    for key in _used_faces(slides):
        family, bold, italic = key
        raw = _raw_bytes(key, web_index)
        if raw is None:
            warnings.append(
                ConversionWarning(
                    message=f"font '{family}' is not installed or web-loaded; "
                    "PowerPoint will substitute it",
                    element=family,
                )
            )
            continue
        ttf = to_embeddable_ttf(raw)
        if ttf is None:
            warnings.append(
                ConversionWarning(
                    message=f"font '{family}' could not be converted to embeddable TrueType",
                    element=family,
                )
            )
            continue
        faces.append(FontFace(family=family, bold=bold, italic=italic, data=ttf))
    return faces, warnings


def load_faces(slides: list[SlideIR]) -> list[FontFace]:
    """Resolve embeddable faces from system fonts only (convenience for the raw builder)."""
    return resolve_faces(slides)[0]
