"""Enroll the main voice: python tools/enroll_voice.py clean_speech.wav  (10-30 s of one person talking, no one else).

Needs `uv sync --extra voice`, ffmpeg on PATH and the speaker model at <data folder>/voice/speaker.onnx (the same file
Scribe uses). Writes voice/main.npy. Then turn on "Keep only the main voice" on the admin page (or SERVICE_VOICE_GATE=1)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_settings  # noqa: E402
from src.voicegate import OnnxEmbedder, enroll, save_voiceprint  # noqa: E402

SECONDS = 16000 * 2


def main(audio: Path) -> None:
    settings = load_settings()
    model = settings.voice_dir / "speaker.onnx"
    if not model.is_file():
        sys.exit(f"Put the WeSpeaker-style ONNX speaker model at {model} first.")
    run = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(audio), "-t", "60", "-f", "s16le", "-ar", "16000",
                          "-ac", "1", "pipe:1"], capture_output=True)
    if run.returncode != 0 or len(run.stdout) < 5 * SECONDS:
        sys.exit("ffmpeg could not read at least 5 seconds of audio from that file.")
    save_voiceprint(settings.voice_dir / "main.npy", enroll(OnnxEmbedder(model), run.stdout))
    print(f"Saved {settings.voice_dir / 'main.npy'} from {len(run.stdout) / SECONDS:.0f} s of audio.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
