"""Unit tests for the Graph fidelity backend's config gating — no network, no msal needed.

These assert the bring-your-own-credentials backend degrades gracefully: with no credentials
configured it reports unavailable and refuses to render, so callers (the dev script, CI) skip
it exactly like the LibreOffice backend. They never touch the network.
"""
# tests legitimately probe internal helpers (_cache_path)
# pyright: reportPrivateUsage=false

from __future__ import annotations

import io
import zipfile

import pytest

from domoxml.core.fidelity import graph
from domoxml.core.fonts import FontFace
from domoxml.core.ir.model import Box, ShapeNode, SlideIR
from domoxml.slides import build_pptx

_GRAPH_ENV = (
    "DOMOXML_GRAPH_CLIENT_ID",
    "DOMOXML_GRAPH_TENANT_ID",
    "DOMOXML_GRAPH_SCOPES",
    "DOMOXML_GRAPH_CACHE",
)


def _clear_graph_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _GRAPH_ENV:
        monkeypatch.delenv(var, raising=False)


def test_has_graph_auth_false_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # No client/tenant id → unavailable, short-circuits before any msal/network call.
    _clear_graph_env(monkeypatch)
    assert graph.has_graph_auth() is False


def test_render_raises_clear_error_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_graph_env(monkeypatch)
    with pytest.raises(RuntimeError, match="Graph not configured"):
        graph.render_pptx_to_pngs_via_graph(b"not a real pptx")


def test_device_login_raises_clear_error_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_graph_env(monkeypatch)
    with pytest.raises(RuntimeError, match="Graph not configured"):
        graph.device_login()


def test_cache_path_honours_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOMOXML_GRAPH_CACHE", "/tmp/custom-cache.json")
    assert str(graph._cache_path()) == "/tmp/custom-cache.json"


def test_cache_path_defaults_outside_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    # The token cache must never live inside the package/repo (PRD §3: no creds in repo).
    _clear_graph_env(monkeypatch)
    path = graph._cache_path()
    assert "domoxml" in path.parts
    assert path.name == "msal_token_cache.json"
    assert path.is_absolute()


def test_strip_embedded_fonts_only_changes_temporary_graph_upload() -> None:
    pptx = build_pptx(
        [
            SlideIR(
                width=12_192_000,
                height=6_858_000,
                shapes=(ShapeNode(box=Box(x=0, y=0, width=100, height=100)),),
            )
        ],
        faces=[FontFace(family="Example", bold=False, italic=False, data=b"font")],
    )
    stripped = graph._strip_embedded_fonts(pptx)

    with zipfile.ZipFile(io.BytesIO(pptx)) as original:
        assert "ppt/fonts/font1.fntdata" in original.namelist()
    with zipfile.ZipFile(io.BytesIO(stripped)) as archive:
        assert "ppt/fonts/font1.fntdata" not in archive.namelist()
        assert "ppt/slides/slide1.xml" in archive.namelist()
        assert b"embeddedFontLst" not in archive.read("ppt/presentation.xml")
        assert b'relationships/font"' not in archive.read("ppt/_rels/presentation.xml.rels")
