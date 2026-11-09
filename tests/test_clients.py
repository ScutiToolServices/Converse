import json
import struct
from dataclasses import dataclass

import httpx
import pytest

import src.clients as clients
from src.clients import RoutedPipeline, probe_s1mini
from src.errors import NotConnected, StepFailed


@dataclass
class S:
    timeout_s: float = 2
    temperature: float = 0.7
    max_tokens: int = 50
    voice: str = ""
    tts_speed: float = 1.0
    cleanup: bool = False
    cleanup_styling: str = "formal"


def wav(rate: int, pcm: bytes) -> bytes:
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16, b"data", 0xFFFFFFFF) + pcm


def pipeline(handler, connected=True):
    slot = (lambda: ("http://svc", "tok")) if connected else (lambda: None)
    pipe = RoutedPipeline(slot, slot, slot, S())
    transport = httpx.MockTransport(handler)
    pipe._client = lambda: httpx.AsyncClient(transport=transport)  # the model services are faked at the HTTP layer
    return pipe


async def test_transcribe_sends_pcm_and_token():
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, token=request.headers["x-internal-token"], size=len(request.content))
        return httpx.Response(200, json={"text": " hello ", "segments": [], "words": [], "language": "en"})

    assert await pipeline(handler).transcribe(b"\0\0" * 10) == "hello"
    assert seen == {"path": "/v1/transcribe", "token": "tok", "size": 20}


async def test_chat_yields_pieces_and_stops_at_done():
    lines = [{"type": "content", "text": "Hi "}, {"type": "content", "text": "there."}, {"type": "done", "content": "Hi there."}]

    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True and body["messages"][0]["role"] == "user"
        return httpx.Response(200, content="".join(json.dumps(x) + "\n" for x in lines))

    pieces = [p async for p in pipeline(handler).chat([{"role": "user", "content": "x"}])]
    assert pieces == ["Hi ", "there."]


async def test_chat_error_line_becomes_a_safe_failure():
    def handler(request):
        return httpx.Response(200, content=json.dumps({"type": "error", "status": 500, "message": "secret detail"}) + "\n")

    with pytest.raises(StepFailed, match="The chat model failed.") as failed:
        [p async for p in pipeline(handler).chat([{"role": "user", "content": "x"}])]
    assert "secret" not in str(failed.value)


async def test_speak_strips_the_header_reads_the_rate_and_keeps_samples_whole():
    body = wav(22050, b"\x01\x00" * 3 + b"\x02")

    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=body)

    chunks = [c async for c in pipeline(handler).speak("hello")]
    assert chunks == [(22050, b"\x01\x00" * 3)]  # the odd trailing byte is held back, never sent half a sample


async def test_http_failure_hides_the_upstream_text():
    def handler(request):
        return httpx.Response(500, text="traceback at http://internal/secret")

    with pytest.raises(StepFailed) as failed:
        [c async for c in pipeline(handler).speak("hello")]
    assert str(failed.value) == "Speech synthesis failed."


async def test_a_missing_connection_says_where_to_save_one():
    with pytest.raises(NotConnected, match="admin page"):
        await pipeline(lambda r: httpx.Response(200), connected=False).transcribe(b"")


def test_wav_header_constant_matches_the_piper_header():
    assert len(wav(22050, b"")) == clients.WAV_HEADER_BYTES


def cleaned(handler, *, cleanup=True, connected=True):
    stt = lambda: ("http://svc", "tok")
    pipe = RoutedPipeline(stt, stt, stt, S(cleanup=cleanup), (lambda: ("http://s1", "s1tok")) if connected else (lambda: None))
    transport = httpx.MockTransport(handler)
    pipe._client = lambda: httpx.AsyncClient(transport=transport)
    return pipe


def stt_and_s1(seen, s1_reply):
    def handler(request):
        seen.append((request.url.host, request.url.path, request.headers.get("x-internal-token")))
        if request.url.host == "s1":
            seen.append(json.loads(request.content))
            return s1_reply
        return httpx.Response(200, json={"text": "um hello there", "segments": [], "words": [], "language": "en"})
    return handler


async def test_cleanup_off_never_calls_s1mini():
    seen = []
    assert await cleaned(stt_and_s1(seen, httpx.Response(200, json={"content": "x"})), cleanup=False).transcribe(b"\0\0") == "um hello there"
    assert all(host != "s1" for host, *_ in [s for s in seen if isinstance(s, tuple)])


async def test_cleanup_sends_the_transcript_and_returns_the_cleaned_text():
    seen = []
    assert await cleaned(stt_and_s1(seen, httpx.Response(200, json={"content": "Hello there."}))).transcribe(b"\0\0") == "Hello there."
    assert ("s1", "/v1/normalize", "s1tok") in seen and {"text": "um hello there", "styling": "formal"} in seen


@pytest.mark.parametrize("reply, connected", [
    (httpx.Response(500, text="boom"), True), (httpx.Response(200, text="not json"), True),
    (httpx.Response(200, json={"content": "  "}), True), (httpx.Response(200, json={"content": "x"}), False),
])
async def test_cleanup_that_cannot_run_keeps_the_raw_transcript(reply, connected):
    assert await cleaned(stt_and_s1([], reply), connected=connected).transcribe(b"\0\0") == "um hello there"


async def test_probe_s1mini_checks_the_model_name(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ok", "content": "Ok.", "model": "s1-mini"})), **kw))
    assert await probe_s1mini("http://s1:29280", "tok") == "Connected, token accepted, model s1-mini."
