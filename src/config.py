"""Converse settings, read from the environment (and a local .env, never committed)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

DEFAULT_SYSTEM_PROMPT = (
    "You are a voice assistant in a spoken conversation. Answer in one to three short sentences of plain speech: "
    "no lists, no markdown, no emoji."
)


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 29405
    data_dir: Path = PROJECT_DIR / ".data"
    config_dir: Path | None = None  # set when the data folder was moved: the folder that keeps settings.json
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.7
    max_tokens: int = 200
    voice: str = ""  # empty = the TTS service's default voice
    tts_speed: float = 1.0
    history_turns: int = 8
    cleanup: bool = False  # clean what the user said through STC_S1Mini_Model before the chat model sees it
    cleanup_styling: str = "semi-formal"  # casual, semi-casual, semi-formal or formal
    # Main-voice gate: needs data_dir/voice/speaker.onnx and main.npy (tools/enroll_voice.py); off without them.
    voice_gate: bool = False
    voice_gate_threshold: float = 0.4
    vad_threshold: float = 0.015  # level (0 to 1 of full scale) a 30 ms frame needs to count as voice
    end_silence_ms: int = 700  # this much silence after speech ends the user's turn
    min_speech_ms: int = 240  # shorter speech is a click or cough: it neither starts a turn nor interrupts the bot
    max_utterance_s: int = 30
    session_max_s: int = 900
    idle_s: float = 60
    max_sessions: int = 2
    timeout_s: int = 60  # per model call: transcription, and the wait for the first chat piece or audio
    stream_max_frame_bytes: int = 64000
    # Unlocks /admin/ (settings page). Empty = the page is off and settings stay as the environment set them.
    admin_password: str = ""

    @property
    def state_dir(self) -> Path:
        """Where settings.json and backends.json live: the first data folder, even after the data folder was moved."""
        return self.config_dir or self.data_dir

    @property
    def voice_dir(self) -> Path:
        return self.data_dir / "voice"

    @property
    def exposed_without_auth(self) -> bool:
        """Listening beyond loopback with no admin password means no tokens, so anything that can reach the port could use the models."""
        return not self.admin_password.strip() and self.host not in LOOPBACK_HOSTS


def _from_environment() -> Settings:
    env = os.environ.get
    return Settings(
        host=env("SERVICE_HOST", "127.0.0.1"),
        port=int(env("SERVICE_PORT", "29405")),
        data_dir=Path(env("SERVICE_DATA_DIR") or PROJECT_DIR / ".data"),
        voice_gate=env("SERVICE_VOICE_GATE", "").strip().lower() in ("1", "true", "yes", "on"),
        voice_gate_threshold=float(env("SERVICE_VOICE_GATE_THRESHOLD", "0.4")),
        admin_password=env("SERVICE_ADMIN_PASSWORD", ""),
    )


def with_saved_data_path(settings: Settings) -> Settings:
    """The admin page's "Data folder" setting moves stored data to another folder. It is read once, here at start.
    Settings and saved model connections stay in the first folder, which is where this value is saved. A folder that
    cannot be written is ignored."""
    try:
        saved = json.loads((settings.data_dir / "settings.json").read_text("utf-8")).get("data_path")
    except (OSError, ValueError, AttributeError):
        return settings
    if not isinstance(saved, str) or not saved.strip():
        return settings
    target = Path(saved.strip()).expanduser()
    if not target.is_absolute():
        target = PROJECT_DIR / target
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-test"
        probe.write_text("x")
        probe.unlink()
    except OSError:
        logging.getLogger(__name__).warning("Data folder %s cannot be written; using %s", target, settings.data_dir)
        return settings
    return replace(settings, data_dir=target, config_dir=settings.data_dir)


def load_settings() -> Settings:
    return with_saved_data_path(_from_environment())
