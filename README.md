# Image AI Telegram Bot v5

## Commands
/start — start only
/us — user settings
/bs — admin settings

## Required environment variables
TELEGRAM_BOT_TOKEN
MONGODB_URI
ADMIN_IDS
SETTINGS_ENCRYPTION_KEY
PUBLIC_BASE_URL
WEBHOOK_SECRET

## Render
Build: `pip install -r requirements.txt`
Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

The bot stores temporary uploaded images in MongoDB with a TTL index and exposes them only through a no-cache temporary URL for Pixelcut processing. The result is sent back to Telegram and the temporary image is deleted.
