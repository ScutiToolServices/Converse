"""The Converse options the admin page can change. The default shown is the value at start (built in), which
load_settings already read; a saved value wins over it."""

from __future__ import annotations

from src.config import Settings
from src.runtime import Config, LiveSettings, Setting

# attribute of Settings -> (setting key, conversion to the attribute's unit); every key is its attribute's own name
FIELDS = {name: (name, convert) for name, convert in {
    "system_prompt": str, "temperature": float, "max_tokens": int, "voice": str, "tts_speed": float,
    "history_turns": int, "cleanup": bool, "cleanup_styling": str, "voice_gate": bool, "voice_gate_threshold": float, "vad_threshold": float, "end_silence_ms": int, "min_speech_ms": int,
    "max_utterance_s": int, "session_max_s": int, "idle_s": float, "timeout_s": int,
}.items()}


def schema(base: Settings) -> list[Setting]:
    return [
        Setting("system_prompt", "System prompt", "text", base.system_prompt, blank=False,
                help="Sent first in every chat call. Keep replies short and free of markdown: they are spoken."),
        Setting("temperature", "Chat temperature", "float", base.temperature, minimum=0, maximum=2),
        Setting("max_tokens", "Longest reply (tokens)", "int", base.max_tokens, minimum=16, maximum=4096),
        Setting("voice", "Voice", "text", base.voice, help="A voice of the TTS service. Empty = its default voice."),
        Setting("tts_speed", "Speaking speed", "float", base.tts_speed, minimum=0.5, maximum=2),
        Setting("history_turns", "Turns remembered", "int", base.history_turns, minimum=0, maximum=32,
                help="Earlier question-and-answer pairs sent with each question."),
        Setting("cleanup", "Clean what I say", "bool", base.cleanup,
                help="Runs each transcript through the STC_S1Mini_Model service (filler words, punctuation, casing) before the chat model gets it. Needs the s1mini connection; without it, or if it fails, the raw transcript is used."),
        Setting("cleanup_styling", "Cleanup tone", "text", base.cleanup_styling, blank=False,
                help="casual, semi-casual, semi-formal or formal. Anything else makes the cleanup service refuse, so the raw transcript is used."),
        Setting("voice_gate", "Keep only the main voice", "bool", base.voice_gate,
                help="Silences other voices before transcribing, so the TV or people nearby are not answered. Needs the speaker model and an enrolled voice in the data folder's voice/ (tools/enroll_voice.py); without them it does nothing."),
        Setting("voice_gate_threshold", "Main-voice match (0-1)", "float", base.voice_gate_threshold, minimum=0.05, maximum=0.95,
                help="Higher drops more of other voices but may drop the main voice. Tune on real recordings."),
        Setting("vad_threshold", "Voice level", "float", base.vad_threshold, minimum=0.001, maximum=0.5,
                help="Loudness (0 to 1) a 30 ms slice needs to count as speech. Raise it in a noisy room."),
        Setting("end_silence_ms", "Silence that ends a turn (ms)", "int", base.end_silence_ms, minimum=200, maximum=3000),
        Setting("min_speech_ms", "Shortest speech (ms)", "int", base.min_speech_ms, minimum=60, maximum=2000,
                help="Speech must last this long before it starts a turn or interrupts the reply."),
        Setting("max_utterance_s", "Longest question (seconds)", "int", base.max_utterance_s, minimum=2, maximum=120),
        Setting("session_max_s", "Longest session (seconds)", "int", base.session_max_s, minimum=30, maximum=86400),
        Setting("idle_s", "Idle timeout (seconds)", "float", base.idle_s, minimum=5, maximum=3600,
                help="A session that receives no audio for this long is closed."),
        Setting("timeout_s", "Model call time limit (seconds)", "int", base.timeout_s, minimum=5, maximum=600),
        Setting("max_sessions", "Sessions at once", "int", base.max_sessions, minimum=1, maximum=16, restart=True),
        Setting("stream_max_frame_bytes", "Largest audio frame (bytes)", "int", base.stream_max_frame_bytes,
                minimum=1024, maximum=1048576, restart=True),
        Setting("data_path", "Data folder", "text", "", restart=True,
                help=f"Where stored data goes. Empty = {base.state_dir}. Applies after a restart. "
                     f"Settings and saved model connections stay in the standard folder."),
    ]


def make_config(base: Settings) -> Config | None:
    """None, so nothing is changeable at run time, unless SERVICE_ADMIN_PASSWORD is set."""
    return Config(base.state_dir / "settings.json", schema(base)) if base.admin_password else None


def live(base: Settings, config: Config | None):
    return LiveSettings(base, config, FIELDS) if config else base
