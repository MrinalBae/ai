from io import BytesIO
from pathlib import Path
import re
from PIL import Image

ALLOWED = {"image/jpeg", "image/png"}

def validate_image(data: bytes, max_bytes: int):
    if not data:
        raise ValueError("Empty image.")
    if len(data) > max_bytes:
        raise ValueError("Image exceeds the configured size limit.")
    try:
        im = Image.open(BytesIO(data))
        im.verify()
    except Exception as exc:
        raise ValueError("Unsupported or corrupt image.") from exc

def normalize_filename(name: str, prefix: str, suffix: str, scale, ext: str):
    stem = Path(name or "image").stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] or "image"
    scale_part = f"_{scale}x" if scale in (2, 4) else ""
    return f"{prefix}{stem}{scale_part}{suffix}.{ext.lower()}"
