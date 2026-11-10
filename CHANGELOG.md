# Changelog

## Unreleased

### Playground works behind a path-prefix proxy

The Try it panel built its request URLs from the page origin, so behind ServiceHub (`/s/<id>/`) it called the hub's root and got 404 Not Found. It now resolves routes against the service root (`../` from the admin page). Same-origin checking is unchanged.


### Playground: no token to paste, model picker, autoplay and batch

The playground signs in with a temporary caller token made from the admin session (named `playground (temporary)`, revoked on sign-out), so the service token field is gone. Choices such as voices load by themselves, and a strip above the form shows which models are connected. Services whose lookup reply carries `models` get a Model picker that narrows the choices. Operations with a text field and audio back get an Autoplay toggle and a "One request per line" toggle that sends each line as its own request and plays the results in order.

### Model connections page redesign

Each model slot now shows its state first (saved connection, direct address, runs in this service, or not connected) with the address and whether a token is saved. Editing opens in place: pick a source (saved connection, direct address or in this service) and only the fields for that source appear. A slot that has not been connected opens its editor. Test connection also updates the slot's state. Saved connections are a table with credentials and the slots using them; Add connection opens the form only on request, and a connection in use has its Delete button disabled. The admin API is unchanged.

### Added

Optional transcript cleanup: a fourth model slot, `s1mini` (the `STC_S1Mini_Model` service, default `http://127.0.0.1:29280`), and two settings, **Clean what I say** (`cleanup`, off by default) and **Cleanup tone** (`cleanup_styling`, default `semi-formal`). When on, each transcript goes through `POST /v1/normalize` before the `transcript` event and the chat model, so both see the cleaned text. With no `s1mini` address, or on any failure, the raw transcript is used and the turn goes on. `ready` in `/health` still needs only `stt`, `cnv` and `tts`. Structure and context are fixed at S1Mini's defaults (`prose`, `general`); the cleanup cannot use text from the screen.


First version. Live voice conversation over `WS /api/converse`: speech to text, a streaming chat model and streaming text to speech, with barge-in (the user can talk over the reply and it stops). Browser client at `/talk/`. Three model slots on the admin page (`stt`, `cnv`, `tts`). Voice detection is a loudness gate. Latency not measured against real models.
