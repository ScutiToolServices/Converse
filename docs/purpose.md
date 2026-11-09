# Purpose

**Kind:** live microphone audio → live spoken reply

**Tags:** `cpu`, `websocket`, `streaming`

| | |
|---|---|
| Input | Over `WS /api/converse`: 16 kHz mono signed 16-bit PCM from a microphone, sent continuously in any frame size up to 64,000 bytes, and `{"type":"stop"}` to end. The asking user comes from `X-Requester-Username` (a browser sends `?username=`). A session lasts at most 15 minutes (setting) and closes after 60 s without audio. |
| Output | JSON events (`ready`, `speech_start`, `transcript`, `reply_text`, `audio`, `interrupted`, `turn_end`, `error`) and binary 16-bit mono PCM of the spoken reply, sent sentence by sentence while the chat model is still writing. Nothing is stored. |
| Needs | `STT_Whisper_Model` (or `STT_Moonshine_Model`), a chat service that streams `POST /v1/chat`, such as `CNV_LFM3_Model`, and `TTS_Piper_Model` (streaming `POST /v1/speak`): one connection each on the admin page. With any missing, a turn fails with a hint and `/health` reports `ready: false`. |
| Runs on | CPU. Holds no model. Voice detection is a loudness gate, not a trained model. |

**Use for:** a voice conversation where the user can talk over the reply and it stops (barge-in), built from the STT, CNV and TTS services you already run. The page at `/talk/` is a ready client for it.
**Not for:** hearing tone, laughter or two people at once (the models see only text); deciding on its own when to speak up; voice cloning (see `Mimic`); transcribing files (see `Scribe`); a reply that is not spoken. The browser page needs no token, so it works only with no admin password (loopback). Latency has not been measured (`not yet run` against real models).
