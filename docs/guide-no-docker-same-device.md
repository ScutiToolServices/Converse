# Converse: without Docker, on Windows

Run Converse directly with Python: one process, no load balancer, listening on `127.0.0.1:29405`.

## Requirements

- Windows with uv (`winget install astral-sh.uv`) and ffmpeg.
- Running speech-to-text, chat and text-to-speech model services, and a token for each made on its own `/admin/` page.

## Start

`run.bat` loads `.env` in this folder (copy `.env.example`) through `--dotenv` and prints the names it loaded, never the values; a real environment variable wins over it. A plain `uv run python -m src.run` does not read `.env`. The variables are listed under Settings in [guide-docker-same-device.md](guide-docker-same-device.md#settings); the ones that name Docker or Compose do not apply here.

Double-click `run.bat`, or run it in a terminal from `Converse\`. Choose **1 Run the service** in the menu, or run `run.bat run` to skip the menu. It runs `uv sync` to create or update `.venv`, then starts `python -m src.run`.

```bash
uv sync
uv run python -m src.run
```

## Check

```bash
curl http://127.0.0.1:29405/health
```

Then open `/admin/`, save a connection for each of the three slots (**Speech to text**, **Chat**, **Text to speech**) under **Model connections**, and press **Test connection** on each.

## Stop

Ctrl+C in the terminal. Do not run this and the Docker stack together: both use port 29405.

## Tests

```bash
uv run pytest -q
```

The dependency-free admin browser check needs Node.js 22 or newer and an installed Chromium browser. Set `CHROMIUM_PATH` to its executable if it is not found in the Playwright cache. Run from this service's folder:

```bash
node tests/admin_shell_browser.cjs
```

It uses synthetic HTTP fixtures; a running service or model is not required.
