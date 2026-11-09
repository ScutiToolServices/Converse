"""The Converse server: a live voice conversation over one WebSocket, a browser page for it, and a health check."""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from src.admin_api import Backends, Slot, Usage, register
from src.clients import Pipeline, RoutedPipeline, probe_cnv, probe_s1mini, probe_stt, probe_tts
from src.config import PROJECT_DIR, Settings
from src.middleware import TokenMiddleware
from src.options import live, make_config
from src.runtime import Config
from src.session import Session
from src.tokens import TokenStore
from src.vad import EnergyVad

WEB_DIR = Path(os.environ.get("SERVICE_WEB_DIR") or PROJECT_DIR / "web")

INSTRUCTIONS = (
    "Converse holds a live spoken conversation (speech to text, chat model, text to speech) over the WebSocket "
    "/api/converse. It has no MCP tools: open the WebSocket from a voice client."
)

CONNECT = {
    "host": "converse",
    "port": 29405,
    "paths": [
        {"label": "Live conversation", "method": "WS", "path": "/api/converse"},
        {"label": "Browser page, no token", "method": "GET", "path": "/talk/"},
        {"label": "MCP", "method": "POST", "path": "/mcp"},
        {"label": "Health, no token", "method": "GET", "path": "/health"},
    ],
}


class SessionLimit:
    """How many conversations run at once. One event loop, so a plain counter is enough."""

    def __init__(self, limit: int) -> None:
        self._limit, self._open = limit, 0

    def acquire(self) -> bool:
        if self._open >= self._limit:
            return False
        self._open += 1
        return True

    def release(self) -> None:
        self._open -= 1


def build_app(settings: Settings, pipeline: Pipeline | None = None, config: Config | None = None) -> Starlette:
    """`config` (default: from SERVICE_ADMIN_PASSWORD, see options.make_config) makes the options in options.py
    changeable on /admin/ while running; without it they stay as the environment set them."""
    config = config if config is not None else make_config(settings)
    base, settings = settings, live(settings, config)
    backends = Backends(base.state_dir / "backends.json")
    tokens = TokenStore(base.state_dir / "tokens.json", "converse_")
    usage = Usage()
    pipeline = pipeline or RoutedPipeline(lambda: backends.get("stt"), lambda: backends.get("cnv"), lambda: backends.get("tts"), settings, lambda: backends.get("s1mini"))
    limit = SessionLimit(settings.max_sessions)
    mcp = FastMCP(name="converse", instructions=INSTRUCTIONS, host=settings.host, port=settings.port)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True, "ready": all(backends.get(key) is not None for key in ("stt", "cnv", "tts"))})

    async def converse(websocket: WebSocket) -> None:
        # A browser cannot set headers on a WebSocket, so the page sends the name as ?username=.
        owner = (websocket.headers.get("x-requester-username") or websocket.query_params.get("username", "")).strip()[:64]
        if not owner:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        if not limit.acquire():
            await websocket.close(code=1013)  # after accept, so a proxy can see why
            return
        session = Session(pipeline, EnergyVad(lambda: settings.vad_threshold), settings, websocket.send_json, websocket.send_bytes)
        deadline = time.monotonic() + settings.session_max_s
        try:
            async with usage.track(owner, "conversation"):
                await websocket.send_json({"type": "ready", "sample_rate": 16000, "frame_ms": 30})
                while (left := deadline - time.monotonic()) > 0:
                    try:
                        message = await asyncio.wait_for(websocket.receive(), min(settings.idle_s, left))
                    except TimeoutError:
                        await websocket.send_json({"type": "error", "message": "Session closed: no audio received."})
                        break
                    if message["type"] == "websocket.disconnect":
                        return
                    data = message.get("bytes")
                    if data is not None:
                        if len(data) > settings.stream_max_frame_bytes:
                            await websocket.send_json({"type": "error", "message": "Audio frame is too large."})
                            await websocket.close(code=1009)
                            return
                        await session.feed(data)
                    elif message.get("text", "").strip().startswith('{"type":"stop"'):
                        break
                await websocket.close()
        except WebSocketDisconnect:
            pass
        finally:
            await session.close()
            limit.release()

    async def status() -> list[dict[str, str]]:
        return [{"label": key.upper(), "value": "connected" if backends.get(key) else "not connected"} for key in ("stt", "cnv", "tts")]

    if config is not None:
        register(mcp, connect=CONNECT, service="Converse", admin_password=base.admin_password, usage=usage, backends=backends,
                 tokens=tokens, status=status, slots=[
            Slot("stt", "Speech to text", "The STT_Whisper_Model (or STT_Moonshine_Model) service that hears the user.",
                 probe_stt, "http://127.0.0.1:29300", local=False),
            Slot("cnv", "Chat", "A CNV model service that answers. It must stream `POST /v1/chat` (NDJSON), as CNV_LFM3_Model does.",
                 probe_cnv, "http://127.0.0.1:29202", local=False),
            Slot("tts", "Text to speech", "The TTS_Piper_Model service that speaks. It must stream `POST /v1/speak`.",
                 probe_tts, "http://127.0.0.1:29320", local=False),
            Slot("s1mini", "Transcript cleanup", "The STC_S1Mini_Model service that cleans the transcript when the Clean what I say setting is on. Optional.",
                 probe_s1mini, "http://127.0.0.1:29280", local=False),
        ])

        @mcp.custom_route("/admin/settings", methods=["GET", "PUT"])
        async def admin_settings(request: Request) -> Response:
            given = request.headers.get("x-admin-password", "").encode("utf-8")
            if not hmac.compare_digest(given, base.admin_password.encode("utf-8")):
                return JSONResponse({"detail": "Wrong admin password."}, status_code=401)
            if request.method == "PUT":
                try:
                    values = (await request.json())["values"]
                    if not isinstance(values, dict):
                        raise TypeError
                except (ValueError, KeyError, TypeError):
                    return JSONResponse({"detail": "Send {\"values\": {...}}."}, status_code=422)
                try:
                    await asyncio.to_thread(config.set, values)
                except ValueError as error:
                    return JSONResponse({"detail": str(error)}, status_code=422)
            return JSONResponse({"service": "Converse", "settings": config.describe()})

    app = mcp.streamable_http_app()
    if config is not None and WEB_DIR.is_dir():
        app.router.routes.append(Mount("/admin", StaticFiles(directory=WEB_DIR, html=True)))
    if (WEB_DIR / "talk").is_dir():
        app.router.routes.append(Mount("/talk", StaticFiles(directory=WEB_DIR / "talk", html=True)))
    app.router.routes.append(WebSocketRoute("/api/converse", converse))
    app.add_middleware(TokenMiddleware, tokens=tokens if base.admin_password else None)
    return app
