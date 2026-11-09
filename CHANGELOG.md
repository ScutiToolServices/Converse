# Changelog

## Unreleased

### Model connections page redesign

Each model slot now shows its state first (saved connection, direct address, runs in this service, or not connected) with the address and whether a token is saved. Editing opens in place: pick a source (saved connection, direct address or in this service) and only the fields for that source appear. A slot that has not been connected opens its editor. Test connection also updates the slot's state. Saved connections are a table with credentials and the slots using them; Add connection opens the form only on request, and a connection in use has its Delete button disabled. The admin API is unchanged.

### Added

Optional transcript cleanup: a fourth model slot, `s1mini` (the `STC_S1Mini_Model` service, default `http://127.0.0.1:29280`), and two settings, **Clean what I say** (`cleanup`, off by default) and **Cleanup tone** (`cleanup_styling`, default `semi-formal`). When on, each transcript goes through `POST /v1/normalize` before the `transcript` event and the chat model, so both see the cleaned text. With no `s1mini` address, or on any failure, the raw transcript is used and the turn goes on. `ready` in `/health` still needs only `stt`, `cnv` and `tts`. Structure and context are fixed at S1Mini's defaults (`prose`, `general`); the cleanup cannot use text from the screen.


First version. Live voice conversation over `WS /api/converse`: speech to text, a streaming chat model and streaming text to speech, with barge-in (the user can talk over the reply and it stops). Browser client at `/talk/`. Three model slots on the admin page (`stt`, `cnv`, `tts`). Voice detection is a loudness gate. Latency not measured against real models.
