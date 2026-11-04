"""Opt-in Takumi bridge: browserless paint-tree and PNG capture.

Takumi is not a drop-in replacement for Chromium's computed DOM. It is a
separate renderer feeding the same canonical IR and conversion outputs.
Unexpected paint operations fall back to ONE slide-owned PNG, never an
unisolated per-element crop that could duplicate adjacent text.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from domoxml.core.ir.extract import ExtractResult
from domoxml.core.ir.model import (
    Box,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.units import px_to_emu, px_to_pt
from domoxml.types import (
    ConversionWarning,
    CoverageItem,
    Editability,
    Representation,
    SourceRetention,
)


class TakumiRenderError(RuntimeError):
    """A fatal engine/transport error. Never converted into a non-fatal warning."""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        self.detail = message
        super().__init__(f"Takumi {stage} failed: {message}")


@dataclass(frozen=True)
class TakumiRenderedSlide:
    png: bytes
    width: int
    height: int
    steps: tuple[dict[str, Any], ...]


def decode_takumi_worker_reply(stdout: bytes, stderr: bytes, status: int) -> dict[str, Any]:
    """Preserve the original Takumi error, including CSS parse errors, for callers."""
    try:
        parsed: Any = json.loads(stdout)
    except (UnicodeDecodeError, ValueError) as exc:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise TakumiRenderError("bridge", detail or "worker did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise TakumiRenderError("bridge", "worker returned a non-object response")
    reply = cast(dict[str, Any], parsed)
    if not reply.get("ok"):
        stage = str(reply.get("stage", "render"))
        message = str(reply.get("message", "unknown error"))
        raise TakumiRenderError(stage, message)
    if status != 0:
        raise TakumiRenderError(
            "bridge", stderr.decode("utf-8", errors="replace").strip() or f"exit status {status}"
        )
    return reply


class TakumiSession:
    """Render HTML through optional local Node.js Takumi dependencies.

    Install packages once with npm install --prefix domoxml/core/render/takumi.
    No browser process, global npm install, or remote rendering service is used.

    Web branch addition: under Pyodide (``sys.platform == "emscripten"``) there
    is no Node subprocess; instead the session calls the host page's async JS
    bridge ``domoxmlTakumiBridge(jsonString) -> jsonString``, which runs the
    same takumi-paint / takumi-js packages in-page (see webapp/). The reply
    contract is identical, so the decoder and extractor are shared.
    """

    def __init__(self, *, timeout_seconds: float = 90.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.worker = Path(__file__).with_name("takumi") / "worker.mjs"

    async def __aenter__(self) -> Self:
        if _is_emscripten():
            if _js_bridge() is None:
                raise TakumiRenderError(
                    "setup", "domoxmlTakumiBridge JS function is not installed on the host page"
                )
            return self
        if shutil.which("node") is None:
            raise TakumiRenderError("setup", "Node.js >=20.19 is required (node not found)")
        if not (self.worker.parent / "node_modules").is_dir():
            raise TakumiRenderError(
                "setup",
                "optional packages missing; run: npm install --prefix domoxml/core/render/takumi",
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def render(self, html: str, *, width: int, height: int) -> TakumiRenderedSlide:
        payload = json.dumps({"html": html, "width": width, "height": height}).encode("utf-8")
        bridge = _js_bridge()
        if bridge is not None:
            try:
                reply_text = await asyncio.wait_for(
                    bridge(payload.decode("utf-8")), timeout=self.timeout_seconds
                )
            except TimeoutError as exc:
                raise TakumiRenderError(
                    "timeout", f"render exceeded {self.timeout_seconds:g}s"
                ) from exc
            reply = decode_takumi_worker_reply(str(reply_text).encode("utf-8"), b"", 0)
            return self._slide_from_reply(reply, width=width, height=height)
        try:
            process = await asyncio.create_subprocess_exec(
                "node",
                str(self.worker),
                cwd=str(self.worker.parent),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise TakumiRenderError("setup", str(exc)) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(payload), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise TakumiRenderError(
                "timeout", f"render exceeded {self.timeout_seconds:g}s"
            ) from exc

        reply = decode_takumi_worker_reply(stdout, stderr, process.returncode or 0)
        return self._slide_from_reply(reply, width=width, height=height)

    @staticmethod
    def _slide_from_reply(
        reply: dict[str, Any], *, width: int, height: int
    ) -> TakumiRenderedSlide:
        encoded = reply.get("png")
        if not isinstance(encoded, str):
            raise TakumiRenderError("bridge", "worker did not return a PNG")
        try:
            png = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TakumiRenderError("bridge", "invalid base64 PNG returned") from exc
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise TakumiRenderError("bridge", "worker returned invalid PNG bytes")
        raw_steps: Any = reply.get("steps")
        if not isinstance(raw_steps, list):
            raise TakumiRenderError("bridge", "worker returned an invalid paint step list")
        steps = cast(list[Any], raw_steps)
        if not all(isinstance(step, dict) for step in steps):
            raise TakumiRenderError("bridge", "worker returned an invalid paint step list")
        return TakumiRenderedSlide(
            png=png, width=width, height=height, steps=tuple(cast(list[dict[str, Any]], steps))
        )


def _is_emscripten() -> bool:
    import sys

    return sys.platform == "emscripten"


def _js_bridge() -> Any:
    """The host page's async Takumi bridge under Pyodide, else None.

    The webapp worker installs ``domoxmlTakumiBridge`` as a global async JS
    function taking a JSON string and resolving to a JSON string with the
    worker.mjs reply shape. Returns None on CPython so the Node subprocess
    transport is used there.
    """
    if not _is_emscripten():
        return None
    try:
        import js

        bridge = getattr(js, "domoxmlTakumiBridge", None)
    except Exception:
        return None
    return bridge


def _rgba(raw: Any) -> Rgba:
    if not isinstance(raw, list):
        raise ValueError("invalid Takumi RGBA colour")
    values = cast(list[Any], raw)
    if len(values) != 4 or not all(isinstance(n, int) and 0 <= n <= 255 for n in values):
        raise ValueError("invalid Takumi RGBA colour")
    rgba = cast(list[int], values)
    return Rgba(r=rgba[0], g=rgba[1], b=rgba[2], a=rgba[3] / 255.0)


def _box(raw: Any) -> Box:
    if not isinstance(raw, dict):
        raise ValueError("invalid Takumi paint bounds")
    bounds = cast(dict[str, Any], raw)
    x, y, width, height = (float(bounds[key]) for key in ("x", "y", "width", "height"))
    if not all(-1000000 < val < 1000000 for val in (x, y, width, height)):
        raise ValueError("Takumi paint bounds out of range")
    if width <= 0 or height <= 0:
        raise ValueError("nonpositive Takumi paint bounds")
    return Box(x=px_to_emu(x), y=px_to_emu(y), width=px_to_emu(width), height=px_to_emu(height))


def extract_takumi(slide: TakumiRenderedSlide) -> ExtractResult:
    """Translate proven simple paint operations; composite unsupported paint once.

    No false claims about element isolation: until selective paint-step replay is
    implemented, any unsupported operation makes the WHOLE slide one raster layer.
    """
    contents: list[ShapeNode] = []
    reason: str | None = None
    for index, step in enumerate(slide.steps):
        try:
            kind = step.get("type")
            if kind == "fill":
                contents.append(
                    ShapeNode(box=_box(step["bounds"]), fill=SolidFill(color=_rgba(step["color"])))
                )
            elif kind == "text":
                text = str(step["text"])
                if not text:
                    continue
                rect = {
                    "x": step["x"],
                    "y": step["y"],
                    "width": max(float(step["width"]) + 2, 1),
                    "height": max(float(step["height"]) + 2, 1),
                }
                weight = str(step.get("fontWeight", "400"))
                contents.append(
                    ShapeNode(
                        box=_box(rect),
                        text=TextBody(
                            paragraphs=(
                                TextParagraph(
                                    runs=(
                                        TextRun(
                                            text=text,
                                            font_family=str(step.get("fontFamily") or "Geist"),
                                            size_pt=px_to_pt(float(step["fontSize"])),
                                            bold=weight in {"bold", "700", "800", "900"},
                                            italic=step.get("fontStyle") in {"italic", "oblique"},
                                            color=_rgba(step["color"]),
                                        ),
                                    )
                                ),
                            ),
                            autofit="none",
                        ),
                    )
                )
            elif kind == "image":
                # The bridge resolves the image source to bytes (data: URIs
                # inline; http(s) fetched host-side). The picture becomes a
                # native PowerPoint picture at its painted box, like the
                # Chromium path's <img> handling.
                ext = str(step.get("ext", "")).lower().lstrip(".")
                if ext == "jpeg":
                    ext = "jpg"
                if ext not in {"png", "jpg", "gif", "bmp"}:
                    raise ValueError(f"unsupported image extension: {ext or 'none'}")
                data = base64.b64decode(str(step["data"]), validate=True)
                if not data:
                    raise ValueError("empty image data")
                contents.append(
                    ShapeNode(
                        box=_box(step["bounds"]),
                        fill=PictureFill(data=data, ext=ext, raster_role="takumi-image"),
                    )
                )
            else:
                reason = str(step.get("reason", kind or "unrecognized operation"))
                break
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            reason = f"paint step {index}: {exc}"
            break

    if reason is not None:
        picture = PictureFill(data=slide.png, ext="png", raster_role="takumi-slide")
        full = Box(x=0, y=0, width=px_to_emu(slide.width), height=px_to_emu(slide.height))
        return ExtractResult(
            slide=SlideIR(
                width=full.width, height=full.height, contents=(ShapeNode(box=full, fill=picture),)
            ),
            coverage=(
                CoverageItem(
                    element="slide",
                    representation=Representation.RASTERIZED,
                    editability=Editability.NONE,
                    raster_area_emu2=full.width * full.height,
                    reason=f"Takumi paint tree needs unsupported OOXML mapping: {reason}",
                ),
            ),
            warnings=(
                ConversionWarning(
                    element="slide",
                    message=f"Takumi used one noneditable slide raster: {reason}",
                ),
            ),
        )
    canvas = SlideIR(
        width=px_to_emu(slide.width),
        height=px_to_emu(slide.height),
        contents=tuple(contents),
    )
    return ExtractResult(
        slide=canvas,
        coverage=tuple(
            CoverageItem(
                element=f"takumi-paint-{index}",
                representation=Representation.NATIVE,
                editability=Editability.SEMANTIC,
                source_retention=SourceRetention.NOT_REQUIRED,
            )
            for index in range(len(contents))
        ),
        warnings=(),
    )
