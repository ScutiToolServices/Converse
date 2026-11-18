"""Voice activity: is this 30 ms slice of 16 kHz mono PCM speech?"""

from __future__ import annotations

import array
import math
import sys
from collections.abc import Callable
from typing import Protocol

FRAME_MS = 30
FRAME_BYTES = 16000 * 2 * FRAME_MS // 1000  # 960


class Vad(Protocol):
    def is_speech(self, frame: bytes) -> bool: ...


class EnergyVad:
    """Loudness gate: the frame's RMS against a threshold (0 to 1 of full scale), read on every call so the admin
    page changes it live.

    shortcut: steady noise above the threshold counts as speech and a quiet voice does not; the browser page asks for
    echo cancellation and noise suppression. Put a trained model (Silero VAD) behind `Vad` if that is not enough."""

    def __init__(self, threshold: float | Callable[[], float]) -> None:
        self._threshold = threshold if callable(threshold) else (lambda: threshold)

    def is_speech(self, frame: bytes) -> bool:
        samples = array.array("h")
        samples.frombytes(frame[: len(frame) // 2 * 2])
        if sys.byteorder == "big":
            samples.byteswap()
        if not samples:
            return False
        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768
        return rms >= self._threshold()
