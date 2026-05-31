"""Render a ``.pptx`` to per-slide PNGs via the *real* Microsoft 365 engine (Microsoft
Graph) — the optional, highest-fidelity fidelity backend.

Bring-your-own credentials: this never ships Microsoft app credentials (PRD §3). A
contributor registers their own Azure app (public client / device-code flow enabled) and
sets the environment variables below; the resolved delegated token is cached **outside** the
package. With no credentials configured, :func:`has_graph_auth` returns ``False`` and callers
skip the backend gracefully — exactly like :func:`~domoxml.core.fidelity.has_libreoffice`.

Pipeline (mirrors the LibreOffice backend): upload the ``.pptx`` to the user's OneDrive →
``GET /content?format=pdf`` (Office Online engine, true PowerPoint fidelity) → delete the
temp file → rasterise the PDF with poppler.

Environment:
    DOMOXML_GRAPH_CLIENT_ID   Azure app (client) id.            Required.
    DOMOXML_GRAPH_TENANT_ID   Azure tenant id (or "common").    Required.
    DOMOXML_GRAPH_SCOPES      Space-separated scopes.           Default "Files.ReadWrite".
    DOMOXML_GRAPH_CACHE       MSAL token cache path.            Default ~/.cache/domoxml/...

Requires the ``graph`` extra (``pip install -e ".[graph]"`` for ``msal``) and poppler.
First-time auth: ``device_login()`` (e.g. via ``scripts/fidelity_check.py``).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.client import HTTPResponse
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from domoxml.core.fidelity._poppler import pdf_to_pngs

_AUTHORITY_BASE = "https://login.microsoftonline.com"
_GRAPH = "https://graph.microsoft.com/v1.0"
_PPTX_CT = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_PML_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_FONT_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
_FONT_PART_PREFIX = "ppt/fonts/"


def _client_id() -> str | None:
    return os.environ.get("DOMOXML_GRAPH_CLIENT_ID") or None


def _tenant_id() -> str | None:
    return os.environ.get("DOMOXML_GRAPH_TENANT_ID") or None


def _scopes() -> list[str]:
    return os.environ.get("DOMOXML_GRAPH_SCOPES", "Files.ReadWrite").split()


def _cache_path() -> Path:
    """Token cache location — env override, else XDG cache. Never inside the package/repo."""
    override = os.environ.get("DOMOXML_GRAPH_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "domoxml" / "msal_token_cache.json"


# msal ships only partial type information, so its app/cache objects cross our boundary as
# ``Any`` and are immediately narrowed to concrete types by the small helpers below — keeping
# the rest of the module strictly typed without scattering per-call ignores.
def _load_app() -> tuple[Any, Any]:
    """Build an MSAL public-client app with the persisted token cache, or ``(None, None)`` if
    the ``graph`` extra isn't installed or credentials aren't configured."""
    client_id, tenant_id = _client_id(), _tenant_id()
    if not client_id or not tenant_id:
        return None, None
    try:
        # Optional dep, imported only when Graph is configured. msal ships partial stubs, so
        # it crosses our boundary as ``Any`` (see the helpers below) — ignore the stub warning.
        import msal  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]
    except ImportError:
        return None, None

    msal_mod: Any = msal
    cache: Any = msal_mod.SerializableTokenCache()
    path = _cache_path()
    if path.exists():
        cache.deserialize(path.read_text())
    app: Any = msal_mod.PublicClientApplication(
        client_id, authority=f"{_AUTHORITY_BASE}/{tenant_id}", token_cache=cache
    )
    return app, cache


def _persist(cache: Any) -> None:
    if cache is not None and bool(cache.has_state_changed):
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(cache.serialize()))


def _silent_token(app: Any, cache: Any) -> str | None:
    """Acquire a cached access token silently (no prompt), or ``None`` if unavailable."""
    accounts: list[Any] = list(app.get_accounts())
    result: dict[str, Any] | None = (
        app.acquire_token_silent(_scopes(), account=accounts[0]) if accounts else None
    )
    _persist(cache)
    if result is None:
        return None
    token = result.get("access_token")
    return token if isinstance(token, str) else None


def has_graph_auth() -> bool:
    """True when the Graph backend is usable *without prompting*: the ``graph`` extra is
    installed, credentials are configured, and a silent token can be acquired from cache.
    Performs no interactive login (it may refresh a cached token over the network)."""
    app, cache = _load_app()
    if app is None:
        return False
    return _silent_token(app, cache) is not None


def device_login() -> None:
    """Interactive first-time device-code login. Prints the code/URL to complete in a browser,
    then caches the token for later silent use by :func:`has_graph_auth` / the render."""
    app, cache = _load_app()
    if app is None:
        raise RuntimeError(
            "Graph not configured — install the 'graph' extra and set "
            "DOMOXML_GRAPH_CLIENT_ID / DOMOXML_GRAPH_TENANT_ID (see .env.example)"
        )
    flow: dict[str, Any] = app.initiate_device_flow(scopes=_scopes())
    if "user_code" not in flow:
        raise RuntimeError(f"device flow failed (enable 'Allow public client flows'?): {flow}")
    print(flow["message"], flush=True)
    result: dict[str, Any] = app.acquire_token_by_device_flow(flow)
    _persist(cache)
    if "access_token" not in result:
        raise RuntimeError(f"device login failed: {result.get('error_description')}")


def _token() -> str:
    app, cache = _load_app()
    if app is None:
        raise RuntimeError(
            "Graph not configured — install the 'graph' extra and set "
            "DOMOXML_GRAPH_CLIENT_ID / DOMOXML_GRAPH_TENANT_ID (see .env.example)"
        )
    token = _silent_token(app, cache)
    if token is None:
        raise RuntimeError("no cached Graph token — run device_login() first")
    return token


def _request(
    method: str,
    url: str,
    token: str,
    *,
    data: bytes | None = None,
    ctype: str | None = None,
    timeout: float = 120.0,
) -> HTTPResponse:
    headers = {"Authorization": f"Bearer {token}"}
    if ctype:
        headers["Content-Type"] = ctype
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)  # fixed https Graph host


def _graph_pdf_bytes(item_id: str, token: str, *, timeout: float) -> bytes:
    """Fetch the Graph PDF rendition while ensuring the bearer token is not forwarded to
    a redirect host."""

    class _NoRedirect(urllib.request.HTTPErrorProcessor):
        def http_response(self, request: Any, response: HTTPResponse) -> HTTPResponse:
            code = response.status
            if code >= 400:
                raise urllib.error.HTTPError(
                    request.full_url,
                    code,
                    response.reason,
                    response.headers,
                    response,
                )
            return response

        https_response = http_response

    source_url = f"{_GRAPH}/me/drive/items/{item_id}/content?format=pdf"
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        source_url,
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    response = opener.open(request, timeout=timeout)
    if response.status in {301, 302, 303, 307, 308}:
        location = response.headers.get("Location")
        if not location:
            raise RuntimeError("Graph PDF redirect missing Location header")
        redirect_url = urllib.parse.urljoin(source_url, location)
        return urllib.request.urlopen(redirect_url, timeout=timeout).read()
    return response.read()


def _strip_embedded_fonts(pptx: bytes) -> bytes:
    """Remove embedded-font parts from the temporary Graph upload.

    Microsoft 365's PDF rendition endpoint rejects decks with embedded fonts with HTTP 406.
    Desktop PowerPoint and LibreOffice honor them, so generated artifacts retain fonts; only
    the disposable copy uploaded for Graph validation is sanitized.
    """
    source_buffer = io.BytesIO(pptx)
    output_buffer = io.BytesIO()
    with (
        zipfile.ZipFile(source_buffer) as source,
        zipfile.ZipFile(output_buffer, "w", compression=zipfile.ZIP_DEFLATED) as output,
    ):
        for info in source.infolist():
            if info.filename.startswith(_FONT_PART_PREFIX):
                continue
            data = source.read(info.filename)
            if info.filename == "ppt/presentation.xml":
                root = ElementTree.fromstring(data)
                root.attrib.pop("embedTrueTypeFonts", None)
                embedded = root.find(f"{{{_PML_NS}}}embeddedFontLst")
                if embedded is not None:
                    root.remove(embedded)
                data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            elif info.filename == "ppt/_rels/presentation.xml.rels":
                root = ElementTree.fromstring(data)
                for rel in list(root):
                    if rel.get("Type") == _FONT_REL_TYPE:
                        root.remove(rel)
                data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            output.writestr(info, data)
    return output_buffer.getvalue()


def render_pptx_to_pdf(pptx: bytes, *, timeout: float = 120.0) -> bytes:
    """Convert ``pptx`` to PDF via Microsoft Graph (true PowerPoint fidelity).

    Uploads the deck to a temp file in the user's OneDrive, requests the PDF rendition, then
    deletes the temp file. Requires configured credentials (see :func:`has_graph_auth`)."""
    token = _token()
    name = f"domoxml-tmp-{uuid.uuid4().hex}.pptx"
    uploaded = _request(
        "PUT",
        f"{_GRAPH}/me/drive/root:/{name}:/content",
        token,
        data=_strip_embedded_fonts(pptx),
        ctype=_PPTX_CT,
        timeout=timeout,
    )
    metadata: dict[str, Any] = json.load(uploaded)
    item_id = str(metadata["id"])
    try:
        return _graph_pdf_bytes(item_id, token, timeout=timeout)
    finally:
        with contextlib.suppress(urllib.error.URLError):
            _request("DELETE", f"{_GRAPH}/me/drive/items/{item_id}", token, timeout=timeout)


def render_pptx_to_pngs_via_graph(
    pptx: bytes, *, dpi: int = 96, timeout: float = 120.0
) -> list[bytes]:
    """Render each slide of ``pptx`` to a PNG via Graph (→ PDF) + poppler (→ PNGs)."""
    pdf = render_pptx_to_pdf(pptx, timeout=timeout)
    return pdf_to_pngs(pdf, dpi=dpi, timeout=timeout)
