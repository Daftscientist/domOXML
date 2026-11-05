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

from domoxml.web import (  # noqa: E402
    aconvert,
    aconvert_captured,
    apreview,
    aread_deck,
    capture_pages,
    capture_plan,
    environment,
    normalize_captured,
    slide_ir,
)


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


def capture_pages_fn(payload_json: str) -> str:
    """{fragments, width, height, css?} -> {pages, snapshot_js, resources_js, recorder_js}"""
    payload = json.loads(payload_json)
    return json.dumps(
        capture_pages(
            payload["fragments"],
            width=int(payload["width"]),
            height=int(payload["height"]),
            css=payload.get("css"),
        )
    )


def capture_plan_fn(payload_json: str) -> str:
    """{raw, width, height} -> {isolated, backdrops} raster planning."""
    payload = json.loads(payload_json)
    return json.dumps(
        capture_plan(
            payload["raw"],
            width=int(payload["width"]),
            height=int(payload["height"]),
        )
    )


async def convert_captured(payload_json: str) -> str:
    """{fragments, captures, width, height, css?, transitions?} -> convert result."""
    payload = json.loads(payload_json)
    result = await aconvert_captured(
        payload["fragments"],
        payload["captures"],
        width=int(payload["width"]),
        height=int(payload["height"]),
        css=payload.get("css"),
        transitions=payload.get("transitions"),
    )
    return json.dumps(result)


def slide_ir_fn(payload_json: str) -> str:
    """{capture, width, height} -> the slide's IR as a display tree."""
    payload = json.loads(payload_json)
    return json.dumps(
        slide_ir(
            payload["capture"],
            width=int(payload["width"]),
            height=int(payload["height"]),
        )
    )


def normalize_fn(payload_json: str) -> str:
    """{capture, width, height} -> the slide normalised to domOXML HTML."""
    payload = json.loads(payload_json)
    return json.dumps(
        normalize_captured(
            payload["capture"],
            width=int(payload["width"]),
            height=int(payload["height"]),
        )
    )


domoxml_api = {
    "convert": convert,
    "convert_captured": convert_captured,
    "capture_pages": capture_pages_fn,
    "capture_plan": capture_plan_fn,
    "slide_ir": slide_ir_fn,
    "normalize": normalize_fn,
    "read_deck": read_deck,
    "preview": preview,
    "preview_b64": preview_b64,
    "environment": environment(),
}
