import httpx
from app.config import settings
from app.database import next_api, get_bot_settings
from app.security import decrypt_secret

BASE_URL = "https://api.developer.pixelcut.ai"

async def post(endpoint: str, data: dict):
    api = await next_api()
    if not api:
        raise RuntimeError("No enabled Pixelcut API key is configured.")
    bot = await get_bot_settings()
    timeout = int(bot["processing"].get("timeout", settings.default_timeout))
    key = decrypt_secret(api["key"], settings.settings_encryption_key)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                BASE_URL + endpoint,
                headers={"X-API-Key": key, "Accept": "application/json"},
                data=data,
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError("Pixelcut request timed out.") from exc
    if response.status_code in (401, 403):
        raise RuntimeError("Pixelcut authentication failed.")
    if response.status_code == 429:
        raise RuntimeError("Pixelcut rate limit reached.")
    if response.status_code >= 500:
        raise RuntimeError("Pixelcut service error.")
    response.raise_for_status()
    return response.json()

async def download(url: str):
    if not url.startswith(("https://", "http://")):
        raise RuntimeError("Invalid Pixelcut result URL.")
    async with httpx.AsyncClient(timeout=settings.default_timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "image/png")

async def run(endpoint, data):
    result = await post(endpoint, data)
    url = result.get("result_url") or result.get("url") or result.get("output_url")
    if not url:
        raise RuntimeError("Pixelcut returned no output image URL.")
    return await download(url)
