# Converse

Live voice conversation tool service: microphone audio in, spoken reply out, one WebSocket. A standalone service on port 29405. It chains three model services: speech to text (`STT_Whisper_Model`), a chat model (a `CNV_*_Model` that streams `POST /v1/chat`) and text to speech (`TTS_Piper_Model`, streaming `POST /v1/speak`). Counterpart of Scribe (speech to text) and Bard (text to speech), which it does not call: they return whole results, not streams.

## Agent instructions
This file is the one instruction file for every coding agent; `CLAUDE.md` only imports it (`@AGENTS.md`). Edit this file, never `CLAUDE.md`.

## Commands (from this folder, venv `.venv`, managed by uv)
- Install: `uv sync` (`winget install astral-sh.uv` if missing; on this machine set `UV_CACHE_DIR=D:/User/.uv-cache`)
- Test: `uv run pytest -q`
- Run: `run.bat run`, or `uv run python -m src.run` (add `--dotenv` to load `.env`). Open `http://127.0.0.1:29405/talk/` for the browser client.

## Rules
- Follow the `tool-service-parity` skill and `AI/ToolServices/_docs/SHARED-FEATURES.md` (what must match in every tool service) and `AI/ToolServices/_docs/SERVICE-SPECIFIC.md` (what differs on purpose). A change to a shared feature goes to every tool service; a new difference goes into `SERVICE-SPECIFIC.md` in the same change.
- Never read or print `.env`. Tools never run a model: the three slots (`stt`, `cnv`, `tts`) are remote-only and read on every call.
- Logic lives in `session.py` (voice detection, turns, barge-in), `clients.py` (the three model calls), `vad.py`; `app.py` is glue. Everything is async; no blocking call on the event loop.
- Cleanup: optional fourth slot `s1mini` (`STC_S1Mini_Model`, `RoutedPipeline._clean` in `clients.py`), used only when the `cleanup` setting is on; `cleanup_styling` is passed as `styling`. It runs inside `transcribe`, so the `transcript` event and the chat model get the cleaned text. No address, a refusal or any error returns the raw transcript, never an error event. `/health` `ready` does not need it.
- Main-voice gate: `src/voicegate.py` is byte-identical to Scribe's (numpy, optional extra `voice`; copy it, do not edit one side). It runs inside `RoutedPipeline.transcribe` before the STT call, in a thread, via the `prefilter` callable read per call; it silences speech segments under `voice_gate_threshold` (0.4) similarity to `<data>/voice/main.npy` using `<data>/voice/speaker.onnx`, and any error sends the original audio. Off unless `voice_gate` is on and both files exist. Enroll with `tools/enroll_voice.py`. It fails open: if no segment matches, the audio goes through unchanged, so a TV alone can still start a turn. `app.py` imports it lazily so Converse starts without numpy.
- Main-voice gate per conversation: `?voice_gate=` on `/api/converse` (`flag()` in `app.py`) -> `Session(voice_gate=)` -> `Pipeline.transcribe(pcm, voice_gate=)`; `Session` passes the keyword only when it is not None, so fake pipelines in tests need not accept it. `False` never gates, `True` gates when a voice is set up, `None` follows the setting.
- Barge-in: speech that lasts `min_speech_ms` cancels the turn in flight (chat and speech requests are closed, so the model services stop) and sends `{type:interrupted}`. The server sends audio faster than real time, so the turn is usually already over while the client still plays: the client must therefore stop playing and drop queued audio on `speech_start` as well as on `interrupted`. Keep this order in `Session._frame`.
- Wire format of `/api/converse`: client sends binary 16 kHz mono s16le PCM (any frame size up to `stream_max_frame_bytes`) and `{"type":"stop"}`. Server sends JSON `ready`, `speech_start`, `transcript`, `reply_text`, `audio` (sample rate of the binary frames that follow), `interrupted`, `turn_end`, `error` (safe message only), and binary s16le PCM. Identity is `X-Requester-Username`, or `?username=` for a browser.
- The browser page (`web/talk/`) cannot send the `X-Internal-Token` header on a WebSocket, so it works only with no admin password (loopback). Other clients send the header.
- Voice detection is a loudness gate (`EnergyVad`), not a trained model: see the `shortcut:` comment in `vad.py`.
- Error messages never contain paths, URLs or upstream text. Result events end with their text field.
- Shared admin files (`web/index.html`, `web/playground.js`, `src/admin_api.py`, `src/tokens.py`, `src/middleware.py`, `tests/test_admin_api.py`, `tests/test_tokens.py`, `tests/seed.py`, `tools/check_sync.py`) are byte-identical in the tool services. Run `python tools/check_sync.py` after changing one; it must exit 0.
- Behaviour changes update `README.md`, `deployment.md`, the guides in `docs/`, `.env.example`, `AGENTS.md` and `CHANGELOG.md` in the same commit.
- Commit with the noreply author email `214214011+scutiii2@users.noreply.github.com`. This repo has no remote yet: do not push until the user creates `ScutiToolServices/Converse`.
