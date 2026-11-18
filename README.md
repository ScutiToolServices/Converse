# Converse

Live voice conversation on port 29405: the user talks, the service listens the whole time, answers in speech, and stops talking when the user talks over it. It chains three model services you already run (speech to text, a chat model, text to speech) and holds no model itself. It is not true full duplex: the models see only text, so it cannot hear tone or two voices at once.

## Tools and API

- Conversation: `WS /api/converse`. Send binary 16 kHz mono signed 16-bit little-endian PCM continuously, any frame size up to 64,000 bytes, and `{"type":"stop"}` to end. Identity is `X-Requester-Username` (a browser sends `?username=`); `X-Internal-Token` is checked before acceptance when an admin password is set.
- Server events (JSON): `ready`, `speech_start` (the user began talking: stop playing the reply now), `transcript` (what the user said), `reply_text` (one sentence about to be spoken), `audio` (the sample rate of the binary frames that follow), `interrupted` (stop playing and drop what is queued), `turn_end`, `error` (a safe message). Binary frames are 16-bit mono PCM of the reply.
- Browser client: `GET /talk/`. It asks for echo cancellation and noise suppression, streams the microphone and plays the reply. It has no way to send the token header, so it works only with no admin password (loopback).
- No MCP tools: `/mcp` answers the handshake only. `GET /health` returns `{ok, ready}`; `ready` is true when all three slots have an address.

## How a turn goes

1. Every 30 ms of microphone audio goes through a loudness gate. Speech that lasts `min_speech_ms` (240 ms) is a real utterance; shorter sounds are ignored.
2. Silence of `end_silence_ms` (700 ms) ends the utterance. The speech-to-text service transcribes it.
3. The chat service streams its answer. Each finished sentence goes at once to the text-to-speech service, so the first sentence is spoken while the rest is still being written.
4. If the user speaks for `min_speech_ms` during any of this, the turn is cancelled, the two requests are closed (the model services stop work), and the client gets `interrupted`.

## Setup

- Run: `run.bat run` (loads `.env`) or `uv run python -m src.run --dotenv` (first `uv sync`). Docker: `docker compose up -d --build` (the Citadel network must exist).
- Optional cleanup: save an `s1mini` connection (`STC_S1Mini_Model`) and turn on **Clean what I say** to clean each transcript (filler words, punctuation, casing, tone from **Cleanup tone**) before the chat model gets it. Off by default; any failure keeps the raw transcript.
- Save one connection each for `stt`, `cnv` and `tts` on the admin page. The chat service must stream `POST /v1/chat` as NDJSON (`CNV_LFM3_Model` does; the other chat services are `not yet run` here). The speech service must stream `POST /v1/speak` (`TTS_Piper_Model` does).

## Limits worth knowing

- Sessions: 2 at once, 15 minutes each, closed after 60 s without audio. Questions are cut at 30 s. The last 8 turns are sent to the chat model.
- Privacy: nothing is stored; audio is held in memory only while a turn runs.
- Latency has not been measured against real models (`not yet run`). It is the sum of the transcription, the first chat words and the first sentence of speech.
- Voice detection is a loudness gate, not a trained model: a noisy room needs a higher "Voice level" on the settings page, and headphones stop the reply being heard as speech.
- A turn cancelled before its reply started loses that question; the user asks again.

## Running it

- A browser needs HTTPS (or `localhost`) to use the microphone. On another machine, put a TLS proxy in front that passes WebSockets without buffering, or use `/talk/` only on the PC that runs it.
- Every turn makes three model calls, so keep the model services on a fast network.

### Releasing

A plain publish (`run.bat`, Deploy, option 1) only updates the `live` branch, so it is fine for test deploys. A release is a separate step: set `VERSION` (and `pyproject.toml`, to the same number), then use `run.bat`, Deploy, option R, which publishes and tags it. `run.bat`, Build the release ZIP, then builds `_zip_versions\Converse-<VERSION>.zip` and opens GitHub's new-release page for the tag. The repository `ScutiToolServices/Converse` does not exist yet: create it before the first publish.

## Admin page

Main-voice gate (optional): silences other voices (TV, people nearby) before the audio goes to speech to text. `uv sync --extra voice`, put the same WeSpeaker-style ONNX speaker model Scribe uses at `<data folder>/voice/speaker.onnx`, run `python tools/enroll_voice.py clean_speech.wav` (10-30 s of the main voice alone), then turn on `SERVICE_VOICE_GATE` (or "Keep only the main voice" on the admin page). `SERVICE_VOICE_GATE_THRESHOLD=0.4` is the match needed (0-1). Without the extra, the model file or the voiceprint it does nothing. If no segment matches, the audio is sent as it was.

Main-voice gate per conversation: connect with `?voice_gate=true` or `?voice_gate=false` on `/api/converse` (a browser can add it to the URL). Omitted follows the `voice_gate` setting; a value other than true/false/1/0/on/off closes the socket with 1008.

With `SERVICE_ADMIN_PASSWORD` set, open `/admin/` and sign in. The shared sidebar has **Overview**, **Playground**, **Access tokens**, **Model connections**, **Runtime & settings**, **Usage** and **Connect & API**. The Playground has no operations here, because a conversation needs a live microphone: use `/talk/`.

## Tests

```bash
uv sync
uv run pytest -q
```

## Documentation

- [Purpose: input, output and what it is for](docs/purpose.md)
- [Deployment](deployment.md)
- [Changelog](CHANGELOG.md)
- [Docker on this PC](docs/guide-docker-same-device.md)
- [Docker on another machine](docs/guide-docker-deployment-device.md)
- [Run without Docker](docs/guide-no-docker-same-device.md)
- [The admin web UI](docs/guide-web-ui.md)
