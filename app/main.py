import asyncio
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError

from .pixelcut import PixelcutClient, PixelcutError, KeyPool

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("image-ai-bot")

APP_NAME = "Image AI Bot"
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "bot.db"
DATA_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
WEBHOOK_SETUP_TOKEN = os.getenv("WEBHOOK_SETUP_TOKEN", "").strip()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 6000 * 6000
SESSION_TTL = 30 * 60

ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}

PRESETS = {
    "ig_story": ("Instagram Story", 1080, 1920, "9:16"),
    "ig_post": ("Instagram Post", 1080, 1350, "4:5"),
    "fb_post": ("Facebook Post", 940, 788, None),
    "presentation": ("Presentation", 1920, 1080, "16:9"),
    "a4": ("A4 Portrait", 2480, 3508, "A4"),
    "mobile_video": ("Mobile Video", 1080, 1920, "9:16"),
    "us_letter": ("Document (US Letter)", 2550, 3300, "8.5×11 in"),
    "x_post": ("Twitter / X Post", 1600, 900, "16:9"),
    "cinema": ("Cinema / Widescreen", None, None, "2.39:1"),
}

RATIOS = {
    "1:1": 1 / 1,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "2.39:1": 2.39,
}

app = FastAPI(title=APP_NAME, version="1.0.0")


class SettingsDB:
    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()
        conn = sqlite3.connect(self.path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                prefix TEXT NOT NULL DEFAULT 'AI_',
                suffix TEXT NOT NULL DEFAULT '',
                include_scale INTEGER NOT NULL DEFAULT 1,
                thumbnail INTEGER NOT NULL DEFAULT 1,
                output_format TEXT NOT NULL DEFAULT 'original',
                jpeg_quality INTEGER NOT NULL DEFAULT 95
            )
        """)
        conn.commit()
        conn.close()

    async def get(self, user_id: int) -> dict[str, Any]:
        async with self.lock:
            conn = sqlite3.connect(self.path)
            row = conn.execute(
                "SELECT prefix,suffix,include_scale,thumbnail,output_format,jpeg_quality "
                "FROM settings WHERE user_id=?", (user_id,)
            ).fetchone()
            if row is None:
                conn.execute("INSERT INTO settings(user_id) VALUES(?)", (user_id,))
                conn.commit()
                row = ("AI_", "", 1, 1, "original", 95)
            conn.close()
        return {
            "prefix": row[0], "suffix": row[1],
            "include_scale": bool(row[2]), "thumbnail": bool(row[3]),
            "output_format": row[4], "jpeg_quality": int(row[5])
        }

    async def update(self, user_id: int, **values):
        allowed = {"prefix", "suffix", "include_scale", "thumbnail", "output_format", "jpeg_quality"}
        values = {k: v for k, v in values.items() if k in allowed}
        if not values:
            return
        async with self.lock:
            conn = sqlite3.connect(self.path)
            conn.execute("INSERT OR IGNORE INTO settings(user_id) VALUES(?)", (user_id,))
            cols = ", ".join(f"{k}=?" for k in values)
            conn.execute(f"UPDATE settings SET {cols} WHERE user_id=?",
                         (*values.values(), user_id))
            conn.commit()
            conn.close()


settings_db = SettingsDB(DB_PATH)
key_pool = KeyPool.from_environment()
pixelcut = PixelcutClient(key_pool)

sessions: dict[int, dict[str, Any]] = {}
sessions_lock = asyncio.Lock()
user_locks: dict[int, asyncio.Lock] = {}
media_lock = asyncio.Lock()
media_tokens: dict[str, tuple[Path, float, str]] = {}


def user_lock(user_id: int) -> asyncio.Lock:
    lock = user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        user_locks[user_id] = lock
    return lock


def safe_name(value: str) -> str:
    value = Path(value).stem
    value = re.sub(r"[^\w\- .]+", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value).strip("._- ")
    return value[:80] or "image"


def extension_for_format(fmt: str, original_ext: str) -> str:
    if fmt == "png":
        return ".png"
    if fmt == "jpeg":
        return ".jpg"
    return original_ext if original_ext in {".jpg", ".jpeg", ".png"} else ".jpg"


def validate_image_bytes(data: bytes) -> tuple[str, int, int]:
    if not data:
        raise ValueError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("The file is larger than the 20 MB Telegram bot limit.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
            im.verify()
        if fmt not in {"JPEG", "PNG"}:
            raise ValueError("Only JPG/JPEG and PNG images are supported.")
        if width < 64 or height < 64:
            raise ValueError("Image must be at least 64×64 pixels.")
        if width > 6000 or height > 6000 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError("Image dimensions exceed the supported 6000×6000 limit.")
        mime = "image/jpeg" if fmt == "JPEG" else "image/png"
        return mime, width, height
    except UnidentifiedImageError as exc:
        raise ValueError("The uploaded file is not a valid image.") from exc


async def telegram_api(method: str, payload: dict[str, Any] | None = None,
                       files: dict[str, Any] | None = None) -> dict[str, Any]:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        if files:
            r = await client.post(url, data=payload or {}, files=files)
        else:
            r = await client.post(url, json=payload or {})
    if r.status_code >= 400:
        raise RuntimeError(f"Telegram API returned HTTP {r.status_code}.")
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram API request failed.")
    return body["result"]


async def tg_send_message(chat_id: int, text: str, keyboard: list[list[dict[str, str]]] | None = None,
                          parse_mode: str = "HTML") -> dict[str, Any]:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if keyboard is not None:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return await telegram_api("sendMessage", payload)


async def tg_edit_message(chat_id: int, message_id: int, text: str,
                          keyboard: list[list[dict[str, str]]] | None = None) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if keyboard is not None:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        await telegram_api("editMessageText", payload)
    except Exception:
        pass


async def tg_answer_callback(callback_id: str, text: str = "") -> None:
    try:
        await telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
    except Exception:
        pass


async def tg_send_document(chat_id: int, path: Path, filename: str, caption: str = "") -> dict[str, Any]:
    with path.open("rb") as f:
        return await telegram_api(
            "sendDocument",
            {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"},
            {"document": (filename, f, mimetypes.guess_type(filename)[0] or "application/octet-stream")}
        )


async def tg_send_photo(chat_id: int, path: Path, caption: str = "") -> dict[str, Any]:
    with path.open("rb") as f:
        return await telegram_api(
            "sendPhoto",
            {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"},
            {"photo": (path.name, f, "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png")}
        )


async def telegram_download(file_id: str) -> bytes:
    meta = await telegram_api("getFile", {"file_id": file_id})
    file_path = meta.get("file_path")
    if not file_path:
        raise RuntimeError("Telegram did not return a file path.")
    url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        r = await client.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_UPLOAD_BYTES:
            raise ValueError("The file is larger than the 20 MB Telegram bot limit.")
        return r.content


async def register_media(path: Path, mime: str) -> str:
    token = secrets.token_urlsafe(32)
    async with media_lock:
        media_tokens[token] = (path, time.time() + 10 * 60, mime)
    return token


async def media_cleanup_loop():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        async with media_lock:
            expired = [k for k, (_, expiry, _) in media_tokens.items() if expiry < now]
            for k in expired:
                path, _, _ = media_tokens.pop(k)
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass


async def session_cleanup_loop():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        async with sessions_lock:
            expired = [uid for uid, s in sessions.items() if now - s["updated"] > SESSION_TTL]
            for uid in expired:
                s = sessions.pop(uid)
                try:
                    Path(s["path"]).unlink(missing_ok=True)
                except Exception:
                    pass


def main_menu():
    return [
        [{"text": "✂️ REMOVE BG", "callback_data": "op:bg"},
         {"text": "✨ UPSCALE", "callback_data": "op:up"}],
        [{"text": "🖼️ EXPAND", "callback_data": "op:expand"},
         {"text": "⚙️ SETTINGS", "callback_data": "settings"}],
    ]


def back_menu(callback="menu"):
    return [[{"text": "← Back", "callback_data": callback},
             {"text": "🏠 Main Menu", "callback_data": "menu"}]]


def ratio_keyboard():
    rows = [
        [("Instagram Story", "1080×1920 • 9:16", "ex:ig_story"),
         ("Instagram Post", "1080×1350 • 4:5", "ex:ig_post")],
        [("Facebook Post", "940×788", "ex:fb_post"),
         ("Presentation", "1920×1080 • 16:9", "ex:presentation")],
        [("A4 Portrait", "2480×3508", "ex:a4"),
         ("Mobile Video", "1080×1920 • 9:16", "ex:mobile_video")],
        [("US Letter", "2550×3300", "ex:us_letter"),
         ("Twitter / X Post", "1600×900 • 16:9", "ex:x_post")],
        [("Cinema / Widescreen", "2.39:1", "ex:cinema")],
        [("⚙️ Custom Size", "Enter width & height", "ex:custom")],
    ]
    return [[{"text": f"{a}\n{b}", "callback_data": c} for a, b, c in row] for row in rows] + back_menu("menu")


def side_keyboard():
    return [
        [{"text": "⬆️ TOP", "callback_data": "side:top"},
         {"text": "⬇️ BOTTOM", "callback_data": "side:bottom"}],
        [{"text": "⬅️ LEFT", "callback_data": "side:left"},
         {"text": "➡️ RIGHT", "callback_data": "side:right"}],
        [{"text": "🔲 ALL SIDES", "callback_data": "side:all"}],
        *back_menu("op:expand"),
    ]


def scale_keyboard(back="menu", include_original=False):
    if include_original:
        row = [{"text": "Original", "callback_data": "scale:1"},
               {"text": "2×", "callback_data": "scale:2"},
               {"text": "4×", "callback_data": "scale:4"}]
    else:
        row = [{"text": "2×", "callback_data": "scale:2"},
               {"text": "4×", "callback_data": "scale:4"}]
    return [row, *back_menu(back)]


def settings_keyboard(s: dict[str, Any]):
    fmt = s["output_format"].upper()
    return [
        [{"text": f"📄 Prefix: {s['prefix'] or 'None'}", "callback_data": "set:prefix"},
         {"text": f"🏷️ Suffix: {s['suffix'] or 'None'}", "callback_data": "set:suffix"}],
        [{"text": f"🔢 Scale in name: {'ON' if s['include_scale'] else 'OFF'}", "callback_data": "set:scale_name"},
         {"text": f"🖼️ Thumbnail: {'ON' if s['thumbnail'] else 'OFF'}", "callback_data": "set:thumb"}],
        [{"text": f"📦 Format: {fmt}", "callback_data": "set:format"},
         {"text": f"🎚️ JPEG quality: {s['jpeg_quality']}", "callback_data": "set:quality"}],
        *back_menu("menu"),
    ]


async def show_settings(chat_id: int):
    s = await settings_db.get(chat_id)
    await tg_send_message(chat_id, "⚙️ <b>Settings</b>\n\nCustomize your output preferences.", settings_keyboard(s))


async def send_start(chat_id: int):
    await tg_send_message(
        chat_id,
        "👋 <b>Welcome to Image AI</b>\n\n"
        "Send your <b>image or document</b> to get started.\n\n"
        "Supported: JPG / PNG\n"
        "Maximum: 20 MB",
    )


async def handle_new_image(user_id: int, chat_id: int, data: bytes, original_name: str):
    try:
        mime, width, height = validate_image_bytes(data)
    except ValueError as exc:
        await tg_send_message(chat_id, f"❌ <b>Invalid image</b>\n\n{exc}")
        return

    old = None
    async with sessions_lock:
        old = sessions.get(user_id)
        path = TMP_DIR / f"{secrets.token_hex(16)}{ALLOWED_MIME[mime]}"
        path.write_bytes(data)
        sessions[user_id] = {
            "path": str(path), "name": original_name, "mime": mime,
            "width": width, "height": height, "updated": time.time(),
            "expand": {}
        }
    if old:
        try:
            Path(old["path"]).unlink(missing_ok=True)
        except Exception:
            pass

    await tg_send_message(
        chat_id,
        f"🖼️ <b>Image received</b>\n\n"
        f"📐 {width} × {height} px\n"
        f"📦 {len(data) / 1024 / 1024:.2f} MB\n\n"
        f"What would you like to do?",
        main_menu()
    )


def session_for(user_id: int):
    return sessions.get(user_id)


def calculate_expansion(width: int, height: int, target_w: int, target_h: int, side: str):
    # If a preset gives exact target dimensions, use them when ALL is selected.
    # For a single side, preserve the other dimension and compute the needed dimension.
    if side == "all":
        return max(0, target_w - width) // 2, max(0, target_h - height) // 2, \
               max(0, target_w - width) - max(0, target_w - width) // 2, \
               max(0, target_h - height) - max(0, target_h - height) // 2

    if side in {"left", "right"}:
        new_w = target_w
        add = max(0, new_w - width)
        if side == "left":
            return add, 0, 0, 0
        return 0, 0, add, 0

    new_h = target_h
    add = max(0, new_h - height)
    if side == "top":
        return 0, add, 0, 0
    return 0, 0, 0, add


def ratio_target(width: int, height: int, ratio: float, side: str):
    if side in {"left", "right"}:
        target_w = max(width, int(round(height * ratio)))
        return target_w, height
    if side in {"top", "bottom"}:
        target_h = max(height, int(round(width / ratio)))
        return width, target_h
    scale = max(width / (width), height / (width / ratio))
    target_w = max(width, int(round(height * ratio)))
    target_h = max(height, int(round(width / ratio)))
    # Use the smallest canvas with the target ratio containing the original.
    if target_w / target_h > ratio:
        target_h = int(round(target_w / ratio))
    else:
        target_w = int(round(target_h * ratio))
    return target_w, target_h


async def process_image(chat_id: int, user_id: int, operation: str, scale: int,
                        expand_spec: dict[str, Any] | None = None):
    async with user_lock(user_id):
        s = session_for(user_id)
        if not s:
            await tg_send_message(chat_id, "⚠️ Please send an image or document first.")
            return
        s["updated"] = time.time()
        await tg_send_message(chat_id, "⏳ <b>Processing...</b>\n\nPlease wait while AI processes your image.")

        try:
            path = Path(s["path"])
            # A temporary signed/public URL is exposed only while Pixelcut is processing.
            token = await register_media(path, s["mime"])
            image_url = f"{PUBLIC_BASE_URL}/media/{token}"
            current_url = image_url
            current_mime = s["mime"]

            if operation == "bg":
                current_url = await pixelcut.remove_background(current_url)
                current_mime = "image/png"

            elif operation == "expand":
                current_url = await pixelcut.outpaint(current_url, expand_spec["left"],
                                                      expand_spec["top"], expand_spec["right"],
                                                      expand_spec["bottom"],
                                                      expand_spec.get("creativity", 0.25),
                                                      expand_spec.get("format", "jpeg"))
                current_mime = "image/png" if expand_spec.get("format") == "png" else "image/jpeg"

            if scale in (2, 4):
                current_url = await pixelcut.upscale(current_url, scale)
                # Pixelcut returns PNG when alpha is present; keep PNG for BG workflows.
                if operation == "bg":
                    current_mime = "image/png"

            result = await pixelcut.download_result(current_url)
            ext = ".png" if current_mime == "image/png" or result["content_type"] == "image/png" else ".jpg"
            out_path = TMP_DIR / f"result_{secrets.token_hex(16)}{ext}"
            out_path.write_bytes(result["data"])

            # Apply user-selected final output format only where safe.
            st = await settings_db.get(user_id)
            final_ext = extension_for_format(st["output_format"], ext)
            if operation == "bg":
                final_ext = ".png"

            if final_ext != ext or (final_ext == ".jpg" and st["jpeg_quality"] != 95):
                with Image.open(out_path) as im:
                    if final_ext == ".jpg":
                        if im.mode in ("RGBA", "LA", "P"):
                            bg = Image.new("RGB", im.size, "white")
                            if "A" in im.getbands():
                                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").getchannel("A"))
                            else:
                                bg.paste(im.convert("RGB"))
                            im = bg
                        else:
                            im = im.convert("RGB")
                        converted = out_path.with_suffix(".jpg")
                        im.save(converted, "JPEG", quality=st["jpeg_quality"], optimize=True)
                    else:
                        converted = out_path.with_suffix(".png")
                        im.save(converted, "PNG", optimize=True)
                out_path.unlink(missing_ok=True)
                out_path = converted

            base = safe_name(s["name"])
            prefix = safe_name(st["prefix"]) if st["prefix"] else ""
            suffix = safe_name(st["suffix"]) if st["suffix"] else ""
            scale_tag = f"_{scale}x" if st["include_scale"] and scale in (2, 4) else ""
            if operation == "bg":
                op_tag = "_bg_removed"
            elif operation == "expand":
                op_tag = "_expanded"
            else:
                op_tag = ""
            filename = f"{prefix}{base}{op_tag}{scale_tag}{suffix}{out_path.suffix}".replace("__", "_")

            # Optional thumbnail; Telegram photo preview is sent separately, original result is always a Document.
            if st["thumbnail"]:
                thumb_path = TMP_DIR / f"thumb_{secrets.token_hex(12)}.jpg"
                with Image.open(out_path) as im:
                    im.thumbnail((900, 900))
                    if im.mode in ("RGBA", "LA", "P"):
                        bg = Image.new("RGB", im.size, "white")
                        rgba = im.convert("RGBA")
                        bg.paste(rgba, mask=rgba.getchannel("A"))
                        im = bg
                    else:
                        im = im.convert("RGB")
                    im.save(thumb_path, "JPEG", quality=88, optimize=True)
                await tg_send_photo(chat_id, thumb_path, "🖼️ <b>Result preview</b>")
                thumb_path.unlink(missing_ok=True)

            with Image.open(out_path) as im:
                rw, rh = im.size

            await tg_send_document(
                chat_id, out_path, filename,
                f"✅ <b>Processing complete</b>\n\n"
                f"📐 Original: {s['width']} × {s['height']} px\n"
                f"📐 Result: {rw} × {rh} px\n"
                f"✨ Scale: {scale}×\n"
                f"📦 Format: {out_path.suffix.upper().replace('.', '')}"
            )
            out_path.unlink(missing_ok=True)

            await tg_send_message(
                chat_id,
                "What would you like to do next?",
                [[{"text": "🔄 Process Same Image", "callback_data": "menu"},
                  {"text": "🆕 New Image", "callback_data": "new"}]]
            )
        except PixelcutError as exc:
            logger.warning("Pixelcut operation failed: %s", exc.safe_message)
            await tg_send_message(chat_id, f"❌ <b>Pixelcut error</b>\n\n{exc.safe_message}")
        except Exception:
            logger.exception("Unexpected processing error")
            await tg_send_message(chat_id, "❌ Something went wrong while processing the image. Please try again.")
        finally:
            async with media_lock:
                for token, (p, _, _) in list(media_tokens.items()):
                    if p == Path(s["path"]):
                        media_tokens.pop(token, None)


async def handle_callback(cb: dict[str, Any]):
    callback_id = cb["id"]
    data = cb.get("data", "")
    message = cb.get("message") or {}
    chat = message.get("chat") or {}
    user = cb.get("from") or {}
    chat_id = int(chat.get("id"))
    user_id = int(user.get("id"))
    await tg_answer_callback(callback_id)

    s = session_for(user_id)
    if s:
        s["updated"] = time.time()

    if data == "menu":
        if not s:
            await send_start(chat_id)
        else:
            await tg_edit_message(chat_id, message["message_id"], "🖼️ <b>Choose an action</b>", main_menu())
        return

    if data == "new":
        async with sessions_lock:
            old = sessions.pop(user_id, None)
        if old:
            Path(old["path"]).unlink(missing_ok=True)
        await send_start(chat_id)
        return

    if data == "settings":
        await show_settings(chat_id)
        return

    if data == "op:up":
        if not s:
            await tg_send_message(chat_id, "Please send an image first.")
            return
        s["pending"] = "up"
        await tg_edit_message(chat_id, message["message_id"], "✨ <b>Choose Upscale</b>\n\nSelect the final resolution.", scale_keyboard("menu"))
        return

    if data == "op:bg":
        if not s:
            await tg_send_message(chat_id, "Please send an image first.")
            return
        await tg_edit_message(chat_id, message["message_id"], "✂️ <b>Remove Background</b>\n\nChoose the final resolution.", scale_keyboard("menu", include_original=True))
        # distinguish BG scale choice via session
        s["pending"] = "bg"
        return

    if data == "op:expand":
        if not s:
            await tg_send_message(chat_id, "Please send an image first.")
            return
        await tg_edit_message(chat_id, message["message_id"], "🖼️ <b>Expand Image</b>\n\nChoose a target format.", ratio_keyboard())
        s["pending"] = "expand"
        return

    if data.startswith("scale:"):
        scale = int(data.split(":")[1])
        pending = s.get("pending") if s else None
        if pending == "bg":
            await process_image(chat_id, user_id, "bg", scale)
        elif pending == "up":
            await process_image(chat_id, user_id, "up", scale)
        else:
            await tg_send_message(chat_id, "Please choose an operation first.")
        return

    if data.startswith("ex:"):
        if not s:
            await tg_send_message(chat_id, "Please send an image first.")
            return
        key = data.split(":", 1)[1]
        s["pending"] = "expand"
        s["expand"] = {"preset": key}
        if key == "custom":
            s["awaiting"] = "custom_width"
            await tg_edit_message(chat_id, message["message_id"],
                                   "⚙️ <b>Custom Size</b>\n\nEnter the target <b>width in pixels</b>.", back_menu("op:expand"))
            return
        await tg_edit_message(chat_id, message["message_id"],
                               f"🖼️ <b>{PRESETS[key][0]}</b>\n\nChoose where the AI should expand the image.",
                               side_keyboard())
        return

    if data.startswith("side:"):
        if not s or s.get("pending") != "expand":
            await tg_send_message(chat_id, "Please choose Expand first.")
            return
        side = data.split(":")[1]
        ex = s["expand"]
        ex["side"] = side
        preset = ex.get("preset")
        if preset == "custom":
            target_w, target_h = ex["width"], ex["height"]
        else:
            _, pw, ph, ratio_label = PRESETS[preset]
            if pw is None:
                target_w, target_h = ratio_target(s["width"], s["height"], RATIOS["2.39:1"], side)
            else:
                target_w, target_h = pw, ph
        left, top, right, bottom = calculate_expansion(s["width"], s["height"], target_w, target_h, side)
        if max(left, top, right, bottom) > 2000:
            await tg_send_message(chat_id, "❌ The selected format requires more than Pixelcut's 2000 px per-side expansion limit. Choose another format or use a smaller custom target.")
            return
        ex.update({"left": left, "top": top, "right": right, "bottom": bottom, "target_w": target_w, "target_h": target_h})
        s["awaiting"] = None
        await tg_edit_message(chat_id, message["message_id"],
                               f"🖼️ <b>Target: {target_w} × {target_h} px</b>\n\n"
                               "Choose final resolution.", scale_keyboard("op:expand", include_original=True))
        return

    if data.startswith("set:"):
        what = data.split(":")[1]
        if what == "prefix":
            s["awaiting"] = "prefix"
            await tg_send_message(chat_id, "📄 Send the new <b>prefix</b>.\nSend <code>-</code> for empty.", back_menu("settings"))
        elif what == "suffix":
            s["awaiting"] = "suffix"
            await tg_send_message(chat_id, "🏷️ Send the new <b>suffix</b>.\nSend <code>-</code> for empty.", back_menu("settings"))
        elif what == "scale_name":
            cur = await settings_db.get(user_id)
            await settings_db.update(user_id, include_scale=not cur["include_scale"])
            await show_settings(chat_id)
        elif what == "thumb":
            cur = await settings_db.get(user_id)
            await settings_db.update(user_id, thumbnail=not cur["thumbnail"])
            await show_settings(chat_id)
        elif what == "format":
            await tg_edit_message(chat_id, message["message_id"], "📦 <b>Output Format</b>", [
                [{"text": "Keep original", "callback_data": "fmt:original"},
                 {"text": "JPG", "callback_data": "fmt:jpeg"}],
                [{"text": "PNG", "callback_data": "fmt:png"}],
                *back_menu("settings"),
            ])
        elif what == "quality":
            await tg_edit_message(chat_id, message["message_id"], "🎚️ <b>JPEG Quality</b>", [
                [{"text": "80", "callback_data": "q:80"}, {"text": "90", "callback_data": "q:90"}],
                [{"text": "95", "callback_data": "q:95"}, {"text": "100", "callback_data": "q:100"}],
                *back_menu("settings"),
            ])
        return

    if data.startswith("fmt:"):
        await settings_db.update(user_id, output_format=data.split(":")[1])
        await show_settings(chat_id)
        return

    if data.startswith("q:"):
        await settings_db.update(user_id, jpeg_quality=int(data.split(":")[1]))
        await show_settings(chat_id)
        return

    await tg_send_message(chat_id, "Unknown action. Please use the menu.")


async def handle_message(update: dict[str, Any]):
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    if not chat or not user:
        return
    chat_id = int(chat["id"])
    user_id = int(user["id"])

    text = message.get("text")
    if text and text.startswith("/start"):
        await send_start(chat_id)
        return
    if text and text.startswith("/settings"):
        await show_settings(chat_id)
        return

    # Settings text input
    s = session_for(user_id)
    if text and s and s.get("awaiting") in {"prefix", "suffix", "custom_width", "custom_height"}:
        awaiting = s["awaiting"]
        if awaiting in {"prefix", "suffix"}:
            value = "" if text.strip() == "-" else text.strip()[:40]
            await settings_db.update(user_id, **{awaiting: value})
            s["awaiting"] = None
            await show_settings(chat_id)
            return
        try:
            value = int(text.strip())
            if not 1 <= value <= 6000:
                raise ValueError
        except ValueError:
            await tg_send_message(chat_id, "❌ Please enter a valid pixel value between 1 and 6000.")
            return
        if awaiting == "custom_width":
            s["expand"]["width"] = value
            s["awaiting"] = "custom_height"
            await tg_send_message(chat_id, "Enter the target <b>height in pixels</b>.", back_menu("op:expand"))
        else:
            s["expand"]["height"] = value
            s["awaiting"] = None
            await tg_send_message(chat_id, "🖼️ <b>Custom target saved</b>\n\nChoose where the AI should expand the image.", side_keyboard())
        return

    # Photo or document
    if "photo" in message:
        photos = message["photo"]
        if not photos:
            return
        file_id = photos[-1]["file_id"]
        original_name = "image.jpg"
    elif "document" in message:
        doc = message["document"]
        mime = doc.get("mime_type", "")
        name = doc.get("file_name", "image")
        if mime not in ALLOWED_MIME and Path(name).suffix.lower() not in ALLOWED_EXT:
            await tg_send_message(chat_id, "❌ Only JPG/JPEG and PNG files are supported.")
            return
        file_id = doc["file_id"]
        original_name = name
    else:
        return

    try:
        data = await telegram_download(file_id)
        await handle_new_image(user_id, chat_id, data, original_name)
    except ValueError as exc:
        await tg_send_message(chat_id, f"❌ {exc}")
    except Exception:
        logger.exception("Telegram file download failed")
        await tg_send_message(chat_id, "❌ I could not download that file. Please try again.")


@app.on_event("startup")
async def startup():
    asyncio.create_task(media_cleanup_loop())
    asyncio.create_task(session_cleanup_loop())
    if TELEGRAM_TOKEN and PUBLIC_BASE_URL:
        asyncio.create_task(set_webhook())


@app.get("/")
async def root():
    return {"service": APP_NAME, "status": "ok"}


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok", "telegram_configured": bool(TELEGRAM_TOKEN),
            "pixelcut_keys_configured": key_pool.count, "public_base_url_configured": bool(PUBLIC_BASE_URL)}


@app.get("/media/{token}")
async def temporary_media(token: str):
    async with media_lock:
        item = media_tokens.get(token)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    path, expiry, mime = item
    if expiry < time.time() or not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store, max-age=0"})


@app.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if not WEBHOOK_SECRET or not secrets.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=404, detail="Not found")
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    update = await request.json()
    try:
        if update.get("callback_query"):
            await handle_callback(update["callback_query"])
        elif update.get("message"):
            await handle_message(update)
    except Exception:
        logger.exception("Webhook update failed")
    return {"ok": True}


@app.post("/api/setup-webhook")
async def setup_webhook(request: Request):
    if not WEBHOOK_SETUP_TOKEN or request.headers.get("X-Setup-Token") != WEBHOOK_SETUP_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return await set_webhook()


async def set_webhook():
    if not TELEGRAM_TOKEN or not PUBLIC_BASE_URL or not WEBHOOK_SECRET:
        return {"configured": False, "reason": "Missing Telegram token, public URL, or webhook secret."}
    url = f"{PUBLIC_BASE_URL}/telegram/webhook/{WEBHOOK_SECRET}"
    try:
        result = await telegram_api("setWebhook", {
            "url": url,
            "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        })
        return {"configured": True, "telegram": result}
    except Exception:
        logger.exception("Webhook setup failed")
        return {"configured": False, "reason": "Telegram webhook setup failed."}
