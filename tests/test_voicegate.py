import pytest

np = pytest.importorskip("numpy")  # optional extra "voice"

from src.voicegate import RATE, enroll, gate  # noqa: E402


def tone(hz: float, seconds: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def pcm_of(*parts: np.ndarray) -> bytes:
    return (np.concatenate(parts) * 32768).astype("<i2").tobytes()


def embed(samples: np.ndarray) -> np.ndarray:
    """Fake voiceprint: which of two pitches dominates the spectrum."""
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), 1 / RATE)
    return np.array([spectrum[abs(freqs - 200) < 20].sum(), spectrum[abs(freqs - 800) < 20].sum()])


def test_other_voice_is_silenced_and_length_kept():
    quiet = np.zeros(int(0.5 * RATE), dtype=np.float32)
    mine, other = tone(200, 1.5), tone(800, 1.5)
    pcm = pcm_of(mine, quiet, other, quiet, mine)
    voiceprint = enroll(embed, pcm_of(tone(200, 2)))
    out = gate(pcm, voiceprint, embed)
    assert len(out) == len(pcm)
    samples = np.frombuffer(out, dtype="<i2")
    a, b = int(2.0 * RATE), int(3.5 * RATE)
    assert not samples[a:b].any()
    assert samples[: int(1.5 * RATE)].any() and samples[int(4 * RATE):].any()


def test_nothing_matches_returns_input_unchanged():
    pcm = pcm_of(tone(800, 2))
    assert gate(pcm, enroll(embed, pcm_of(tone(200, 2))), embed) == pcm


def test_fbank_shape():
    from src.voicegate import fbank
    assert fbank(tone(200, 1.0)).shape == (98, 80)


async def test_pipeline_runs_prefilter_before_stt():
    import httpx
    from types import SimpleNamespace
    from src.clients import RoutedPipeline

    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request.content)
        return httpx.Response(200, json={"text": " hello "})

    class Pipeline(RoutedPipeline):
        def _client(self):
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    settings = SimpleNamespace(cleanup=False, timeout_s=5)
    slot = lambda: ("http://stt", "")
    audio, silent = bytes([1, 1, 1, 1]), bytes(2)
    assert await Pipeline(slot, slot, slot, settings).transcribe(audio) == "hello"
    assert await Pipeline(slot, slot, slot, settings, prefilter=lambda: (lambda pcm: silent)).transcribe(audio) == "hello"
    assert posted == [audio, silent]
