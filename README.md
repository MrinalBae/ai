# Image AI Telegram Bot

A single Python FastAPI Telegram bot for:

- Remove Background
- Upscale 2x / 4x
- AI Expand / Outpaint
- Professional Telegram inline-button UI
- Per-user settings
- JPG/PNG Document output
- Optional result thumbnail
- 10 Pixelcut API keys with round-robin allocation
- SQLite settings only; no permanent user-image storage

## Pixelcut API

Uses the current official Pixelcut API:

- `POST /v1/upscale`
- `POST /v1/remove-background`
- `POST /v1/outpaint`
- `X-API-Key`
- JSON `image_url` requests returning `result_url`

The bot temporarily exposes the downloaded Telegram image through a random, short-lived `/media/<token>` URL so Pixelcut can fetch it. The file is deleted after processing/expiry.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Set all secrets as environment variables. `PUBLIC_BASE_URL` must be the public HTTPS URL of the running service.

## Render

Use the included `render.yaml` or create a Web Service:

Build:
```bash
pip install -r requirements.txt
```

Start:
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set:
- TELEGRAM_BOT_TOKEN
- PUBLIC_BASE_URL
- WEBHOOK_SECRET
- WEBHOOK_SETUP_TOKEN
- PIXELCUT_API_KEY_1 ... PIXELCUT_API_KEY_10

The bot automatically calls Telegram `setWebhook` on startup when these are configured.

## Important limits

Telegram Bot API downloads are limited to 20 MB, so the bot intentionally caps incoming files at 20 MB. Pixelcut itself supports up to 25 MB for the image APIs.

Pixelcut outpaint allows 0–2000 pixels per direction. The bot validates this before making the API request.

## Security

Never commit real Telegram or Pixelcut keys. Put them only in the hosting provider's secret/environment-variable store.
