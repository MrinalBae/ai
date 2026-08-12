from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from app.config import settings

client = None
db = None

DEFAULT_USER = {
    "format": "PNG",
    "jpeg_quality": 95,
    "prefix": "",
    "suffix": "",
    "scale_in_filename": True,
    "thumbnail": True,
}

DEFAULT_BOT = {
    "_id": "main",
    "privacy": {"encryption": True, "show_api_keys": False},
    "processing": {"timeout": 120, "max_upload_mb": 20},
    "output": {"format": "PNG", "jpeg_quality": 95, "thumbnail": True},
    "rotation": {"enabled": True},
}

async def connect():
    global client, db
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not configured.")
    client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=10000)
    await client.admin.command("ping")
    db = client[settings.mongodb_database]
    await db.users.create_index("telegram_id", unique=True)
    await db.apis.create_index("created_at")
    await db.temp_files.create_index("expires_at", expireAfterSeconds=0)

async def close():
    global client
    if client:
        client.close()

def get_db():
    if db is None:
        raise RuntimeError("MongoDB is not connected.")
    return db

async def ensure_user(uid):
    await get_db().users.update_one(
        {"telegram_id": uid},
        {"$setOnInsert": {"telegram_id": uid, "settings": DEFAULT_USER.copy(),
                          "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

async def get_user_settings(uid):
    await ensure_user(uid)
    return (await get_db().users.find_one({"telegram_id": uid}))["settings"]

async def update_user_settings(uid, values):
    await ensure_user(uid)
    await get_db().users.update_one(
        {"telegram_id": uid},
        {"$set": {f"settings.{k}": v for k, v in values.items()}},
    )

async def reset_user_settings(uid):
    await get_db().users.update_one({"telegram_id": uid},
                                    {"$set": {"settings": DEFAULT_USER.copy()}},
                                    upsert=True)

async def get_bot_settings():
    d = await get_db().bot_settings.find_one({"_id": "main"})
    if not d:
        await get_db().bot_settings.insert_one(DEFAULT_BOT.copy())
        d = await get_db().bot_settings.find_one({"_id": "main"})
    return d

async def set_bot(path, value):
    await get_db().bot_settings.update_one({"_id": "main"}, {"$set": {path: value}}, upsert=True)

async def add_api(label, encrypted):
    await get_db().apis.insert_one({
        "label": label, "key": encrypted, "enabled": True,
        "created_at": datetime.now(timezone.utc), "last_used": None,
    })

async def list_apis():
    return await get_db().apis.find().sort("created_at", 1).to_list(length=10000)

async def toggle_api(oid):
    d = await get_db().apis.find_one({"_id": ObjectId(oid)})
    if d:
        await get_db().apis.update_one({"_id": ObjectId(oid)}, {"$set": {"enabled": not d["enabled"]}})

async def delete_api(oid):
    await get_db().apis.delete_one({"_id": ObjectId(oid)})

async def next_api():
    return await get_db().apis.find_one_and_update(
        {"enabled": True},
        {"$set": {"last_used": datetime.now(timezone.utc)}},
        sort=[("last_used", 1), ("created_at", 1)],
    )

async def save_temp_file(file_id, data, content_type, filename, expires_at):
    await get_db().temp_files.update_one(
        {"file_id": file_id},
        {"$set": {"file_id": file_id, "data": data, "content_type": content_type,
                  "filename": filename, "expires_at": expires_at}},
        upsert=True,
    )

async def get_temp_file(file_id):
    return await get_db().temp_files.find_one({"file_id": file_id})

async def delete_temp_file(file_id):
    await get_db().temp_files.delete_one({"file_id": file_id})
