import asyncio
from collections.abc import AsyncIterator

import pytest

from src.config import Settings
from src.errors import StepFailed
from src.vad import FRAME_BYTES

LOUD = (b"\x00\x40") * (FRAME_BYTES // 2)  # constant level 0.5 of full scale: speech
QUIET = b"\x00\x00" * (FRAME_BYTES // 2)


def frames(count: int, loud: bool) -> bytes:
    return (LOUD if loud else QUIET) * count


class FakePipeline:
    """Stands in for the three model services. `hold` makes speech wait, so a test can interrupt it."""

    def __init__(self, text: str = "hello there", reply: tuple[str, ...] = ("Hi, nice to meet you. ", "How can I help today?"),
                 fail: str = "", hold: asyncio.Event | None = None) -> None:
        self.text, self.reply, self.fail, self.hold = text, reply, fail, hold
        self.heard: list[int] = []
        self.asked: list[list[dict[str, str]]] = []
        self.spoken: list[str] = []
        self.closed_chat = 0

    async def transcribe(self, pcm: bytes) -> str:
        self.heard.append(len(pcm))
        if self.fail == "stt":
            raise StepFailed("Speech recognition failed.")
        return self.text

    async def chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        self.asked.append(messages)
        try:
            if self.fail == "cnv":
                raise StepFailed("The chat model failed.")
            for piece in self.reply:
                yield piece
        finally:
            self.closed_chat += 1

    async def speak(self, text: str) -> AsyncIterator[tuple[int, bytes]]:
        self.spoken.append(text)
        yield 22050, b"\x01\x00" * 100
        if self.hold is not None:
            await self.hold.wait()
        yield 22050, b"\x02\x00" * 100


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, end_silence_ms=300, min_speech_ms=90, idle_s=5, timeout_s=2)
