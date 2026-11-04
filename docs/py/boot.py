# Pyodide bootstrap for the domOXML web app.
#
# The worker JS loads Pyodide (with the eager packages passed to
# loadPyodide, so they download during runtime initialisation), unpacks the
# content-hashed domoxml bundle into /bundle, puts it on sys.path, installs
# the Takumi JS bridge as a global, then runs this file. Everything the UI
# can do goes through the three async functions exposed as `domoxml_api`.
import base64
import json
import sys

if "/bundle" not in sys.path:
    sys.path.insert(0, "/bundle")

from domoxml.web import aconvert, apreview, aread_deck, environment  # noqa: E402


async def convert(payload_json: str) -> str:
    """{fragments, width, height, css?, transitions?} -> {pptx_b64, coverage, warnings}"""
    payload = json.loads(payload_json)
    result = await aconvert(
        payload["fragments"],
        width=int(payload["width"]),
        height=int(payload["height"]),
        css=payload.get("css"),
        transitions=payload.get("transitions"),
    )
    return json.dumps(result)


async def read_deck(data: bytes) -> str:
    """PPTX bytes -> {width_px, height_px, css, slides: [{html, transition}]}"""
    return json.dumps(await aread_deck(bytes(data)))


async def preview(payload_json: str) -> bytes:
    """{html, width, height, css?} -> PNG bytes (Takumi render of one slide)."""
    payload = json.loads(payload_json)
    return await apreview(
        payload["html"],
        width=int(payload["width"]),
        height=int(payload["height"]),
        css=payload.get("css"),
    )


async def preview_b64(payload_json: str) -> str:
    """base64 variant of preview(), handy where raw bytes are awkward."""
    return base64.b64encode(await preview(payload_json)).decode("ascii")


domoxml_api = {
    "convert": convert,
    "read_deck": read_deck,
    "preview": preview,
    "preview_b64": preview_b64,
    "environment": environment(),
}
