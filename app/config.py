import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_database: str = os.getenv("MONGODB_DATABASE", "image_ai_bot")
    admin_ids: tuple[int, ...] = tuple(
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
        if x.strip().isdigit()
    )
    settings_encryption_key: str = os.getenv("SETTINGS_ENCRYPTION_KEY", "")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    port: int = int(os.getenv("PORT", "8000"))
    default_max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "20"))
    default_timeout: int = int(os.getenv("PIXELCUT_TIMEOUT", "120"))

settings = Settings()
