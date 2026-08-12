from datetime import datetime, timedelta, timezone
from io import BytesIO
from telegram import Update
from telegram.ext import ContextTypes
from PIL import Image
from app.config import settings
from app.database import get_bot_settings, save_temp_file, get_temp_file, delete_temp_file
from app.image_utils import validate_image, normalize_filename
from app.keyboards import operations, scales, ratios, sides
from app.services.upscale import upscale
from app.services.remove_bg import remove_background
from app.services.expand import expand

async def receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await get_bot_settings()
    limit = int(bot["processing"].get("max_upload_mb", settings.default_max_upload_mb))*1024*1024
    doc=update.message.document
    photo=update.message.photo[-1] if update.message.photo else None
    try:
        if doc:
            if doc.mime_type not in ("image/jpeg","image/png"):
                raise ValueError("Only JPG/PNG images are supported.")
            if doc.file_size and doc.file_size > limit:
                raise ValueError("Image exceeds the upload limit.")
            tg_file=await doc.get_file()
            data=bytes(await tg_file.download_as_bytearray())
            name=doc.file_name or "image.png"
        elif photo:
            tg_file=await photo.get_file()
            data=bytes(await tg_file.download_as_bytearray())
            name="image.jpg"
        else:
            return
        validate_image(data,limit)
        file_id=f"{update.effective_user.id}_{update.message.message_id}"
        await save_temp_file(file_id,data,"image/png" if name.lower().endswith(".png") else "image/jpeg",
                             name,datetime.now(timezone.utc)+timedelta(minutes=10))
        context.user_data["file_id"]=file_id
        context.user_data["name"]=name
        await update.message.reply_text("Choose an operation:",reply_markup=operations())
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")

async def callback(update, context):
    q=update.callback_query; await q.answer()
    d=q.data
    if d=="op:remove":
        context.user_data["operation"]="remove"; await q.edit_message_text("Remove BG — choose output scale.",reply_markup=scales("remove"))
    elif d=="op:upscale":
        context.user_data["operation"]="upscale"; await q.edit_message_text("Upscale — choose scale.",reply_markup=scales("upscale"))
    elif d=="op:expand":
        context.user_data["operation"]="expand"; await q.edit_message_text("Expand — choose target ratio.",reply_markup=ratios())
    elif d.startswith("upscale:"):
        await run_operation(update,context,int(d.split(":")[1]),"upscale")
    elif d.startswith("remove:"):
        await run_operation(update,context,int(d.split(":")[1]),"remove")
    elif d.startswith("ratio:"):
        r=d.split(":",1)[1]
        if r=="custom":
            context.user_data["expand_wait"]="custom"
            await q.message.reply_text("Send custom width × height, e.g. 1920 x 1080.")
        else:
            context.user_data["ratio"]=r
            context.user_data["ratio_size"]=r
            await q.edit_message_text("Choose which side to expand.",reply_markup=sides())
    elif d.startswith("side:"):
        context.user_data["side"]=d.split(":")[1]
        await q.edit_message_text("Send the expansion amount in pixels.",reply_markup=None)
        await q.message.reply_text("Example: 500")
        context.user_data["expand_wait"]="amount"
    elif d.startswith("expandscale:"):
        await run_operation(update,context,int(d.split(":")[1]),"expand")
    elif d=="cancel":
        context.user_data.clear(); await q.edit_message_text("Cancelled. Send another image.")

async def text(update,context):
    wait=context.user_data.get("expand_wait")
    if not wait:return False
    try:
        value=update.message.text.strip().lower().replace(" ","")
        if wait=="custom":
            w,h=map(int,value.split("x",1))
            if not (1<=w<=12000 and 1<=h<=12000):raise ValueError
            context.user_data["custom_size"]=(w,h)
            context.user_data.pop("expand_wait")
            await update.message.reply_text("Choose which side to expand.",reply_markup=sides())
        elif wait=="amount":
            amount=int(value)
            if not 0<=amount<=10000:raise ValueError
            context.user_data["expand_amount"]=amount
            context.user_data.pop("expand_wait")
            await update.message.reply_text("Choose result scale.",reply_markup=scales("expandscale"))
    except Exception:
        await update.message.reply_text("Invalid value.")
    return True

async def run_operation(update,context,scale,operation):
    q=update.callback_query
    record=await get_temp_file(context.user_data.get("file_id",""))
    if not record:
        await q.message.reply_text("Image expired. Send it again."); return
    try:
        # Public URL is only used temporarily by Pixelcut.
        if not settings.public_base_url:
            raise RuntimeError("PUBLIC_BASE_URL is not configured.")
        image_url=f"{settings.public_base_url}/media/{record['file_id']}"
        if operation=="upscale":
            result,ctype=await upscale(image_url,scale)
        elif operation=="remove":
            result,ctype=await remove_background(image_url,scale)
        else:
            side=context.user_data.get("side")
            amount=int(context.user_data.get("expand_amount",0))
            result,ctype=await expand(image_url,side,amount,scale)
        user=context.user_data.get("name","image.png")
        ext="jpg" if ctype.startswith("image/jpeg") else "png"
        output=normalize_filename(user,"","",scale if operation!="remove" else scale,ext)
        await q.message.reply_document(document=BytesIO(result),filename=output,
                                        caption=f"✅ {operation.replace('_',' ').title()} complete.")
    except Exception as exc:
        await q.message.reply_text(f"❌ {exc}")
    finally:
        await delete_temp_file(record["file_id"])
        context.user_data.clear()
