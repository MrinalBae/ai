from telegram import Update
from telegram.ext import ContextTypes
from app.config import settings
from app.database import get_bot_settings, list_apis, add_api, toggle_api, delete_api, set_bot
from app.security import encrypt_secret, decrypt_secret, mask_secret
from app.keyboards import bs, api_menu, api_list, privacy, processing, output, rotation

def is_admin(uid): return uid in settings.admin_ids

async def show(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin access only.")
        return
    await update.message.reply_text("<b>Admin Settings</b>", parse_mode="HTML", reply_markup=bs())

async def callback(update, context):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Admin only.", show_alert=True); return
    await q.answer()
    parts = q.data.split(":"); action = parts[1]
    if action == "apis":
        await q.edit_message_text("🔑 Pixelcut APIs", reply_markup=api_menu())
    elif action == "privacy":
        s=await get_bot_settings()
        await q.edit_message_text("🔐 Privacy", reply_markup=privacy(s["privacy"]["encryption"],s["privacy"]["show_api_keys"]))
    elif action == "processing":
        await q.edit_message_text("⚙️ Processing", reply_markup=processing())
    elif action == "output":
        await q.edit_message_text("📁 Output", reply_markup=output())
    elif action == "rotation":
        s=await get_bot_settings()
        await q.edit_message_text("🔄 API Rotation", reply_markup=rotation(s["rotation"]["enabled"]))
    elif action == "rotation_toggle":
        s=await get_bot_settings(); await set_bot("rotation.enabled", not s["rotation"]["enabled"])
        s=await get_bot_settings(); await q.edit_message_reply_markup(reply_markup=rotation(s["rotation"]["enabled"]))
    elif action == "back":
        await q.edit_message_text("<b>Admin Settings</b>", parse_mode="HTML", reply_markup=bs())
    elif action == "format":
        s=await get_bot_settings(); await set_bot("output.format", "JPG" if s["output"]["format"]=="PNG" else "PNG")
        await q.edit_message_reply_markup(reply_markup=output())
    elif action == "thumbnail":
        s=await get_bot_settings(); await set_bot("output.thumbnail", not s["output"]["thumbnail"])
        await q.edit_message_reply_markup(reply_markup=output())
    elif action in ("timeout","maxupload","quality"):
        context.user_data["admin_wait"]=action
        await q.message.reply_text({"timeout":"Timeout seconds 10–600.","maxupload":"Max upload MB 1–25.","quality":"JPG quality 1–100."}[action])
    elif action == "enc":
        s=await get_bot_settings(); new=not s["privacy"]["encryption"]
        await set_bot("privacy.encryption",new)
        if new: await set_bot("privacy.show_api_keys",False)
        s=await get_bot_settings()
        await q.edit_message_reply_markup(reply_markup=privacy(s["privacy"]["encryption"],s["privacy"]["show_api_keys"]))
    elif action == "show":
        s=await get_bot_settings()
        if s["privacy"]["encryption"]:
            await q.answer("Turn Encryption OFF before showing API keys.", show_alert=True); return
        await set_bot("privacy.show_api_keys", not s["privacy"]["show_api_keys"])
        s=await get_bot_settings()
        await q.edit_message_reply_markup(reply_markup=privacy(s["privacy"]["encryption"],s["privacy"]["show_api_keys"]))
    elif action == "add":
        context.user_data["admin_wait"]="api"
        await q.message.reply_text("Send: Label | API_KEY")
    elif action == "list":
        docs=await list_apis(); s=await get_bot_settings()
        await q.edit_message_text(
            "No APIs configured." if not docs else "Configured APIs:",
            reply_markup=api_list([(str(d["_id"]),d["label"],d["enabled"]) for d in docs])
        )
        if docs:
            lines=[]
            for d in docs:
                key=decrypt_secret(d["key"],settings.settings_encryption_key)
                lines.append(f"<b>{d['label']}</b> — {mask_secret(key) if s['privacy']['encryption'] or not s['privacy']['show_api_keys'] else key}")
            await q.message.reply_text("\n".join(lines),parse_mode="HTML")
    elif action == "toggle":
        await toggle_api(parts[2]); await q.answer("API status updated.")
    elif action == "delete":
        await delete_api(parts[2]); await q.answer("API deleted.")
    # Refresh API list after mutations
    if action in ("toggle","delete"):
        docs=await list_apis()
        await q.edit_message_reply_markup(reply_markup=api_list([(str(d["_id"]),d["label"],d["enabled"]) for d in docs]))

async def text(update, context):
    action=context.user_data.get("admin_wait")
    if not action or not is_admin(update.effective_user.id): return False
    value=update.message.text.strip()
    try:
        if action=="api":
            if "|" not in value: raise ValueError
            label,key=[x.strip() for x in value.split("|",1)]
            if not label or not key: raise ValueError
            await add_api(label,encrypt_secret(key,settings.settings_encryption_key))
        elif action=="timeout":
            v=int(value); assert 10<=v<=600; await set_bot("processing.timeout",v)
        elif action=="maxupload":
            v=int(value); assert 1<=v<=25; await set_bot("processing.max_upload_mb",v)
        elif action=="quality":
            v=int(value); assert 1<=v<=100; await set_bot("output.jpeg_quality",v)
        else: raise ValueError
    except Exception:
        await update.message.reply_text("Invalid value.")
        return True
    context.user_data.pop("admin_wait",None)
    await update.message.reply_text("✅ Saved to MongoDB.")
    return True
