# Changelog

## Unreleased

### Added

Optional transcript cleanup: a fourth model slot, `s1mini` (the `STC_S1Mini_Model` service, default `http://127.0.0.1:29280`), and two settings, **Clean what I say** (`cleanup`, off by default) and **Cleanup tone** (`cleanup_styling`, default `semi-formal`). When on, each transcript goes through `POST /v1/normalize` before the `transcript` event and the chat model, so both see the cleaned text. With no `s1mini` address, or on any failure, the raw transcript is used and the turn goes on. `ready` in `/health` still needs only `stt`, `cnv` and `tts`. Structure and context are fixed at S1Mini's defaults (`prose`, `general`); the cleanup cannot use text from the screen.


First version. Live voice conversation over `WS /api/converse`: speech to text, a streaming chat model and streaming text to speech, with barge-in (the user can talk over the reply and it stops). Browser client at `/talk/`. Three model slots on the admin page (`stt`, `cnv`, `tts`). Voice detection is a loudness gate. Latency not measured against real models.
