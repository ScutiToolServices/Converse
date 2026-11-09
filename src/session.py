"""One live conversation: microphone PCM in, spoken reply PCM out, both flowing at the same time.

The loop is listen -> transcribe -> chat -> speak, but listening never stops. While a reply is being spoken, every 30 ms
frame still goes through the voice detector; speech that lasts `min_speech_ms` cancels the turn in flight (chat request,
speech request, queued sentences) and tells the client to flush what it has not played yet (barge-in). This is the
cascaded way to feel full duplex: the models never hear tone or overlap, only text.

shortcut: a turn cancelled before its reply started loses the earlier question (the next utterance is a new turn);
merge the two if users report it."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from collections.abc import Awaitable, Callable

from src.clients import Pipeline
from src.errors import ConverseError
from src.vad import FRAME_BYTES, FRAME_MS, Vad

PRE_ROLL_FRAMES = 10  # 300 ms of audio before the voice detector fired, so the first word is not clipped
PCM_BYTES_PER_SECOND = 16000 * 2
_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*\s+|[。！？]+|\n+")
_MARKDOWN = re.compile(r"[*_`#]+")
MIN_SENTENCE_CHARS = 12  # shorter pieces ("Hi.", "Yes.") wait for the next sentence: one speech request is cheaper than two


class SentenceChunker:
    """Cuts streamed text into sentences as soon as one is complete, so speech can start before the reply ends."""

    def __init__(self) -> None:
        self._buffer = ""

    def push(self, text: str) -> list[str]:
        self._buffer += text
        out: list[str] = []
        start = 0
        for match in _BOUNDARY.finditer(self._buffer):
            if len(self._buffer[start:match.end()].strip()) >= MIN_SENTENCE_CHARS:
                out.append(self._buffer[start:match.end()].strip())
                start = match.end()
        self._buffer = self._buffer[start:]
        return out

    def flush(self) -> str:
        rest, self._buffer = self._buffer.strip(), ""
        return rest


class Session:
    """`send_json` and `send_bytes` deliver to the client; `feed` takes the client's PCM. All three run on one event loop."""

    def __init__(self, pipeline: Pipeline, vad: Vad, settings, send_json: Callable[[dict], Awaitable[None]],
                 send_bytes: Callable[[bytes], Awaitable[None]]) -> None:
        self._pipeline, self._vad, self._settings = pipeline, vad, settings
        self._json, self._bytes = send_json, send_bytes
        self._pending = bytearray()  # input that is not yet a whole 30 ms frame
        self._pre: deque[bytes] = deque(maxlen=PRE_ROLL_FRAMES)
        self._utterance = bytearray()
        self._in_speech = False
        self._announced = False  # speech has lasted min_speech_ms: it is a real utterance, not a click
        self._speech_ms = 0
        self._silence_ms = 0
        self._turn: asyncio.Task | None = None
        self._history: list[tuple[str, str]] = []
        self._rate = 0

    async def feed(self, pcm: bytes) -> None:
        self._pending += pcm
        while len(self._pending) >= FRAME_BYTES:
            frame = bytes(self._pending[:FRAME_BYTES])
            del self._pending[:FRAME_BYTES]
            await self._frame(frame)

    async def close(self) -> None:
        await self._cancel_turn()

    async def _frame(self, frame: bytes) -> None:
        s = self._settings
        if self._vad.is_speech(frame):
            if not self._in_speech:
                self._in_speech, self._speech_ms, self._silence_ms = True, 0, 0
                self._utterance = bytearray(b"".join(self._pre))
                self._pre.clear()
            self._utterance += frame
            self._speech_ms += FRAME_MS
            self._silence_ms = 0
            if self._speech_ms >= s.min_speech_ms and not self._announced:
                self._announced = True
                if await self._cancel_turn():
                    await self._json({"type": "interrupted"})
                await self._json({"type": "speech_start"})
        elif self._in_speech:
            self._utterance += frame
            self._silence_ms += FRAME_MS
            if self._silence_ms >= s.end_silence_ms:
                self._end_utterance()
        else:
            self._pre.append(frame)
        if self._in_speech and len(self._utterance) >= s.max_utterance_s * PCM_BYTES_PER_SECOND:
            self._end_utterance()

    def _end_utterance(self) -> None:
        pcm, announced = bytes(self._utterance), self._announced
        self._in_speech = self._announced = False
        self._utterance = bytearray()
        if announced:
            self._turn = asyncio.create_task(self._run_turn(pcm))

    async def _cancel_turn(self) -> bool:
        """Stops the turn in flight and waits until its model calls are closed. True when there was one."""
        turn, self._turn = self._turn, None
        if turn is None or turn.done():
            return False
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        return True

    def _messages(self, question: str) -> list[dict[str, str]]:
        turns = self._history[-self._settings.history_turns:] if self._settings.history_turns else []
        messages = [{"role": "system", "content": self._settings.system_prompt}]
        for asked, answered in turns:
            messages += [{"role": "user", "content": asked}, {"role": "assistant", "content": answered}]
        return [*messages, {"role": "user", "content": question}]

    async def _run_turn(self, pcm: bytes) -> None:
        question, spoken = "", []
        producer: asyncio.Task | None = None
        try:
            question = await asyncio.wait_for(self._pipeline.transcribe(pcm), self._settings.timeout_s)
            if not question:
                return
            await self._json({"type": "transcript", "text": question})
            sentences: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4)  # chat does not run far ahead of speech
            messages = self._messages(question)

            async def produce() -> None:
                chunker = SentenceChunker()
                try:
                    async for piece in self._pipeline.chat(messages):
                        for sentence in chunker.push(piece):
                            await sentences.put(sentence)
                    if tail := chunker.flush():
                        await sentences.put(tail)
                finally:
                    await sentences.put(None)

            producer = asyncio.create_task(produce())
            while (sentence := await sentences.get()) is not None:
                text = _MARKDOWN.sub("", sentence).strip()
                if not text:
                    continue
                await self._json({"type": "reply_text", "text": sentence})
                spoken.append(sentence)
                async for rate, chunk in self._pipeline.speak(text):
                    if rate != self._rate:
                        self._rate = rate
                        await self._json({"type": "audio", "rate": rate})
                    await self._bytes(chunk)
            await producer  # raises what the chat step raised
            await self._json({"type": "turn_end"})
        except TimeoutError:
            await self._json({"type": "error", "message": "A model took too long to answer."})
        except ConverseError as error:
            await self._json({"type": "error", "message": str(error)})
        finally:
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            if question and spoken:  # only what was started counts: an interrupted reply is remembered as far as it went
                self._history.append((question, " ".join(spoken)))
                del self._history[:-32]
