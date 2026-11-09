"""The three model services Converse calls, each over HTTP and each streaming where the service can:

  STT  `STT_Whisper_Model` (or Moonshine)  POST /v1/transcribe   16 kHz mono PCM in, text out
  CNV  a `CNV_*_Model` chat service        POST /v1/chat         messages in, NDJSON pieces out (`stream: true`)
  TTS  `TTS_Piper_Model` (or Paradee)      POST /v1/speak        text in, WAV out, sentence by sentence (`stream: true`)
  S1M  `STC_S1Mini_Model` (optional)       POST /v1/normalize    the transcript in, cleaned text out (`cleanup` setting)

Every failure becomes one safe message: httpx, JSON and shape errors vary and may hold URLs. The slots are read on every
call (a getter), so a change on the admin page applies to the next turn."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Protocol

import httpx

from src.admin_api import ProbeError, check
from src.errors import NotConnected, StepFailed

WAV_HEADER_BYTES = 44  # TTS_Piper_Model streams a plain 44-byte RIFF header with an unknown length, then 16-bit mono PCM


class Pipeline(Protocol):
    """What a session needs from the models. `app.py` builds `RoutedPipeline`; tests build fakes."""

    async def transcribe(self, pcm: bytes) -> str: ...

    def chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...

    def speak(self, text: str) -> AsyncIterator[tuple[int, bytes]]:
        """(sample rate, 16-bit mono PCM) pieces."""


Slot = Callable[[], tuple[str, str] | None]


def _headers(token: str) -> dict[str, str]:
    return {"X-Internal-Token": token} if token else {}


class RoutedPipeline:
    def __init__(self, stt: Slot, cnv: Slot, tts: Slot, settings, s1mini: Slot = lambda: None) -> None:
        self._stt, self._cnv, self._tts, self._settings, self._s1mini = stt, cnv, tts, settings, s1mini

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._settings.timeout_s)  # one per call, closed by the caller's `async with`

    @staticmethod
    def _slot(slot: Slot, what: str) -> tuple[str, str]:
        found = slot()
        if found is None:
            raise NotConnected(f"No {what} service is connected. Save a connection on the Converse admin page.")
        return found

    async def transcribe(self, pcm: bytes) -> str:
        url, token = self._slot(self._stt, "speech-to-text")
        try:
            async with self._client() as http:
                reply = await http.post(url + "/v1/transcribe", params={"language": "en", "word_timestamps": "false"},
                                        content=pcm, headers=_headers(token))
            reply.raise_for_status()
            text = str(reply.json()["text"]).strip()
        except Exception as error:
            raise StepFailed("Speech recognition failed.") from error
        return await self._clean(text)

    async def _clean(self, text: str) -> str:
        """Optional STC_S1Mini_Model cleanup of what the user said. Any problem keeps the raw text: a turn never fails here."""
        remote = self._s1mini()
        if not (self._settings.cleanup and remote and text):
            return text
        try:
            async with self._client() as http:
                reply = await http.post(remote[0] + "/v1/normalize", headers=_headers(remote[1]),
                                        json={"text": text, "styling": self._settings.cleanup_styling})
            reply.raise_for_status()
            return str(reply.json()["content"]).strip() or text
        except Exception:
            return text

    async def chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        url, token = self._slot(self._cnv, "chat")
        body = {"messages": messages, "temperature": self._settings.temperature,
                "max_tokens": self._settings.max_tokens, "stream": True}
        try:
            async with self._client() as http, http.stream("POST", url + "/v1/chat", json=body, headers=_headers(token)) as reply:
                reply.raise_for_status()
                async for line in reply.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event["type"] == "content":
                        yield event["text"]
                    elif event["type"] == "error":
                        raise StepFailed("The chat model failed.")
                    elif event["type"] == "done":
                        return
        except StepFailed:
            raise
        except Exception as error:
            raise StepFailed("The chat model failed.") from error

    async def speak(self, text: str) -> AsyncIterator[tuple[int, bytes]]:
        url, token = self._slot(self._tts, "text-to-speech")
        body = {"text": text, "speed": self._settings.tts_speed, "stream": True}
        if self._settings.voice:
            body["voice"] = self._settings.voice
        try:
            async with self._client() as http, http.stream("POST", url + "/v1/speak", json=body, headers=_headers(token)) as reply:
                reply.raise_for_status()
                head, rate, odd = bytearray(), 0, b""
                async for chunk in reply.aiter_bytes():
                    if len(head) < WAV_HEADER_BYTES:
                        head += chunk
                        if len(head) < WAV_HEADER_BYTES:
                            continue
                        rate = int.from_bytes(head[24:28], "little")
                        chunk = bytes(head[WAV_HEADER_BYTES:])
                    chunk = odd + chunk
                    odd = chunk[len(chunk) // 2 * 2:]  # a 16-bit sample is never split between two pieces
                    if chunk := chunk[: len(chunk) // 2 * 2]:
                        yield rate, chunk
        except Exception as error:
            raise StepFailed("Speech synthesis failed.") from error


async def probe_stt(url: str, token: str) -> str:
    """The admin page's Test button for the speech-to-text address: reachable, then the token on a tenth of a second of silence."""
    await check(url, "", "/health")
    reply = await check(url, token, "/v1/transcribe", method="POST", content=b"\0\0" * 1600,
                        params={"language": "en", "word_timestamps": "false"})
    try:
        return f"Connected, token accepted, model {reply.json()['model']}."
    except (ValueError, KeyError, TypeError):
        raise ProbeError("That address is not a speech-to-text model service.") from None


async def probe_s1mini(url: str, token: str) -> str:
    """Reachable, then the token on one short sentence."""
    await check(url, "", "/health")
    reply = await check(url, token, "/v1/normalize", method="POST", json={"text": "ok"})
    try:
        return f"Connected, token accepted, model {reply.json()['model']}."
    except (ValueError, KeyError, TypeError):
        raise ProbeError("That address is not a STC_S1Mini_Model service.") from None


async def probe_cnv(url: str, token: str) -> str:
    """Reachable, then the token on a one-word question."""
    await check(url, "", "/health")
    reply = await check(url, token, "/v1/chat", method="POST",
                        json={"messages": [{"role": "user", "content": "Say hi."}], "max_tokens": 16})
    try:
        reply.json()["content"]
    except (ValueError, KeyError, TypeError):
        raise ProbeError("That address is not a chat model service.") from None
    return "Connected, token accepted."


async def probe_tts(url: str, token: str) -> str:
    """Reachable, then the token on the voice list."""
    await check(url, "", "/health")
    reply = await check(url, token, "/v1/voices")
    try:
        return f"Connected, token accepted, {len(reply.json()['voices'])} voice(s)."
    except (ValueError, KeyError, TypeError):
        raise ProbeError("That address is not a text-to-speech model service.") from None
