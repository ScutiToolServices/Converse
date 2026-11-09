import asyncio

from src.session import Session, SentenceChunker
from src.vad import EnergyVad
from tests.conftest import FakePipeline, frames


class Wire:
    """What the client would receive."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.audio = bytearray()

    async def json(self, event: dict) -> None:
        self.events.append(event)

    async def bytes(self, data: bytes) -> None:
        self.audio += data

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


def make(settings, pipeline: FakePipeline) -> tuple[Session, Wire]:
    wire = Wire()
    return Session(pipeline, EnergyVad(0.05), settings, wire.json, wire.bytes), wire


async def settle(session: Session) -> None:
    if session._turn is not None:
        await asyncio.wait_for(asyncio.shield(session._turn), 2)


def test_chunker_waits_for_a_whole_sentence_and_merges_short_ones():
    chunker = SentenceChunker()
    assert chunker.push("Hi. ") == []  # too short alone
    assert chunker.push("How are you doing today? I am") == ["Hi. How are you doing today?"]
    assert chunker.flush() == "I am"


def test_chunker_keeps_decimals_together():
    assert SentenceChunker().push("The value is 3.5 percent today. Next") == ["The value is 3.5 percent today."]


def test_energy_vad_levels():
    vad = EnergyVad(0.05)
    assert vad.is_speech(frames(1, True))
    assert not vad.is_speech(frames(1, False))


async def test_one_turn_runs_listen_transcribe_chat_speak(settings):
    pipeline = FakePipeline()
    session, wire = make(settings, pipeline)
    await session.feed(frames(5, False) + frames(10, True) + frames(12, False))
    await settle(session)
    assert wire.types() == ["speech_start", "transcript", "reply_text", "audio", "reply_text", "turn_end"]
    assert wire.events[1]["text"] == "hello there"
    assert pipeline.spoken == ["Hi, nice to meet you.", "How can I help today?"]
    assert len(wire.audio) == 800 and wire.events[3]["rate"] == 22050


async def test_pre_roll_keeps_the_start_of_the_first_word(settings):
    pipeline = FakePipeline()
    session, _ = make(settings, pipeline)
    await session.feed(frames(20, False) + frames(10, True) + frames(12, False))
    await settle(session)
    # 10 speech + 10 pre-roll + 10 trailing silence frames of 960 bytes
    assert pipeline.heard == [960 * 30]


async def test_a_click_shorter_than_min_speech_starts_nothing(settings):
    pipeline = FakePipeline()
    session, wire = make(settings, pipeline)
    await session.feed(frames(1, True) + frames(20, False))
    assert session._turn is None and wire.events == [] and pipeline.heard == []


async def test_speaking_over_the_reply_interrupts_it(settings):
    hold = asyncio.Event()
    pipeline = FakePipeline(hold=hold)
    session, wire = make(settings, pipeline)
    await session.feed(frames(10, True) + frames(12, False))
    await asyncio.sleep(0.05)  # the first piece of audio has been sent, the rest waits
    assert "reply_text" in wire.types() and "turn_end" not in wire.types()
    await session.feed(frames(5, True))  # the user talks again
    assert wire.types()[-2:] == ["interrupted", "speech_start"]
    assert session._turn is None and pipeline.closed_chat == 1
    assert session._history == [("hello there", "Hi, nice to meet you.")]  # only what was started


async def test_history_goes_to_the_next_question(settings):
    pipeline = FakePipeline()
    session, _ = make(settings, pipeline)
    for _ in range(2):
        await session.feed(frames(10, True) + frames(12, False))
        await settle(session)
    second = pipeline.asked[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]


async def test_a_failed_step_reports_a_safe_error_and_the_session_goes_on(settings):
    pipeline = FakePipeline(fail="cnv")
    session, wire = make(settings, pipeline)
    await session.feed(frames(10, True) + frames(12, False))
    await settle(session)
    assert wire.events[-1] == {"type": "error", "message": "The chat model failed."}
    pipeline.fail = ""
    await session.feed(frames(10, True) + frames(12, False))
    await settle(session)
    assert wire.types()[-1] == "turn_end"


async def test_empty_transcript_is_not_answered(settings):
    pipeline = FakePipeline(text="")
    session, wire = make(settings, pipeline)
    await session.feed(frames(10, True) + frames(12, False))
    await settle(session)
    assert wire.types() == ["speech_start"] and pipeline.asked == []
