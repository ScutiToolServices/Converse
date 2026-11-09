from dataclasses import replace

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.app import build_app
from tests.conftest import FakePipeline, frames
from tests.seed import seed_token

ANN = {"X-Requester-Username": "ann"}


def make(settings, **changes):
    settings = replace(settings, **changes)
    if settings.admin_password:
        seed_token(settings, "secret")
    return TestClient(build_app(settings, FakePipeline()))


def test_health_is_not_ready_without_connections(settings):
    assert make(settings).get("/health").json() == {"ok": True, "ready": False}


def test_talk_page_is_served(settings):
    response = make(settings).get("/talk/")
    assert response.status_code == 200 and "Converse" in response.text


def test_a_whole_turn_over_the_websocket(settings):
    with make(settings).websocket_connect("/api/converse", headers=ANN) as ws:
        assert ws.receive_json() == {"type": "ready", "sample_rate": 16000, "frame_ms": 30}
        ws.send_bytes(frames(10, True) + frames(12, False))
        seen = []
        while not seen or seen[-1]["type"] != "turn_end":
            message = ws.receive()
            if message.get("text"):
                import json
                seen.append(json.loads(message["text"]))
        assert [e["type"] for e in seen] == ["speech_start", "transcript", "reply_text", "audio", "reply_text", "turn_end"]


def test_browser_name_in_the_query_is_enough_without_a_password(settings):
    with make(settings).websocket_connect("/api/converse?username=ann") as ws:
        assert ws.receive_json()["type"] == "ready"


def test_a_session_without_a_name_is_refused(settings):
    with pytest.raises(WebSocketDisconnect) as refused:
        with make(settings).websocket_connect("/api/converse"):
            pass
    assert refused.value.code == 1008


def test_a_token_is_needed_when_an_admin_password_is_set(settings):
    client = make(settings, admin_password="pw")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/converse", headers=ANN):
            pass
    with client.websocket_connect("/api/converse", headers={**ANN, "X-Internal-Token": "secret"}) as ws:
        assert ws.receive_json()["type"] == "ready"


def test_sessions_are_limited(settings):
    client = make(settings, max_sessions=1)
    with client.websocket_connect("/api/converse", headers=ANN) as first:
        first.receive_json()
        with client.websocket_connect("/api/converse", headers=ANN) as second:
            with pytest.raises(WebSocketDisconnect) as full:
                second.receive_json()
            assert full.value.code == 1013


def test_an_oversize_frame_closes_the_session(settings):
    with make(settings, stream_max_frame_bytes=2000).websocket_connect("/api/converse", headers=ANN) as ws:
        ws.receive_json()
        ws.send_bytes(b"\0" * 3000)
        assert ws.receive_json()["message"] == "Audio frame is too large."
