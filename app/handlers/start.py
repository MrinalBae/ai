from telegram import Update
from telegram.ext import ContextTypes
from app.database import ensure_user

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update.effective_user.id)
    await update.message.reply_text(
        "<b>Image AI</b>\n\nSend your image or document to get started.\n"
        "Supported: JPG, JPEG, PNG.\nMaximum size is controlled by admin settings.",
        parse_mode="HTML",
    )
