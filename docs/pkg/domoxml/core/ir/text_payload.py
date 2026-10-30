"""Versioned normalized-HTML payloads for exact text-body IR round-trips."""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from domoxml.core.ir.model import TextBody


class TextPayload(BaseModel):
    """Text-body semantics carried beside renderer-facing HTML spans and CSS."""

    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    text: TextBody


def encode_text_body(text: TextBody) -> str:
    """Serialize one text body to compact, URL-safe versioned JSON."""
    raw = TextPayload(text=text).model_dump_json().encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_text_body(value: str | None) -> TextBody | None:
    """Validate a normalized-HTML text payload, returning ``None`` when invalid."""
    if not value:
        return None
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        return TextPayload.model_validate_json(raw).text
    except (ValidationError, ValueError, TypeError):
        return None
