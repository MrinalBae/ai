import os
import asyncio
import random
from dataclasses import dataclass

import httpx

BASE_URL = "https://api.developer.pixelcut.ai"
TIMEOUT = httpx.Timeout(90.0, connect=15.0)


class PixelcutError(Exception):
    def __init__(self, safe_message: str, status: int | None = None):
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.status = status


class KeyPool:
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.count = len(keys)
        self._index = 0
        self._lock = asyncio.Lock()

    @classmethod
    def from_environment(cls):
        keys = []
        for i in range(1, 11):
            value = os.getenv(f"PIXELCUT_API_KEY_{i}", "").strip()
            if value:
                keys.append(value)
        # Backward-compatible single-key option for testing.
        if not keys:
            value = os.getenv("PIXELCUT_API_KEY", "").strip()
            if value:
                keys.append(value)
        return cls(keys)

    async def next(self) -> str:
        if not self.keys:
            raise PixelcutError("Pixelcut API is not configured. Add a Pixelcut API key in the server secrets.")
        async with self._lock:
            key = self.keys[self._index % len(self.keys)]
            self._index += 1
            return key


@dataclass
class DownloadedResult:
    data: bytes
    content_type: str


class PixelcutClient:
    def __init__(self, pool: KeyPool):
        self.pool = pool

    async def _post(self, endpoint: str, payload: dict):
        key = await self.pool.next()
        headers = {
            "X-API-Key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(f"{BASE_URL}{endpoint}", headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise PixelcutError("Pixelcut timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise PixelcutError("Pixelcut could not be reached. Please try again.") from exc

        if r.status_code in (401, 403):
            raise PixelcutError("Pixelcut authentication failed. Check the configured API key.", r.status_code)
        if r.status_code == 429:
            raise PixelcutError("Pixelcut rate limit was reached. Please try again shortly.", r.status_code)
        if r.status_code >= 400:
            raise PixelcutError("Pixelcut rejected the image or request. Please try another image.", r.status_code)
        try:
            body = r.json()
            result_url = body["result_url"]
        except Exception as exc:
            raise PixelcutError("Pixelcut returned an unexpected response.") from exc
        return result_url

    async def upscale(self, image_url: str, scale: int) -> str:
        if scale not in (2, 4):
            raise PixelcutError("Upscale scale must be 2x or 4x.")
        return await self._post("/v1/upscale", {"image_url": image_url, "scale": scale})

    async def remove_background(self, image_url: str) -> str:
        return await self._post("/v1/remove-background", {"image_url": image_url, "format": "png"})

    async def outpaint(self, image_url: str, left: int, top: int, right: int, bottom: int,
                       creativity: float = 0.25, output_format: str = "jpeg") -> str:
        if not any((left, top, right, bottom)):
            raise PixelcutError("At least one expansion direction is required.")
        if any(x < 0 or x > 2000 for x in (left, top, right, bottom)):
            raise PixelcutError("Each expansion direction must be between 0 and 2000 pixels.")
        if output_format not in ("jpeg", "png"):
            output_format = "jpeg"
        return await self._post("/v1/outpaint", {
            "image_url": image_url,
            "left": int(left), "top": int(top), "right": int(right), "bottom": int(bottom),
            "creativity": max(0.0, min(1.0, float(creativity))),
            "output_format": output_format,
        })

    async def download_result(self, url: str) -> DownloadedResult:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
                r = await client.get(url)
                r.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PixelcutError("Downloading the Pixelcut result timed out.") from exc
        except httpx.HTTPError as exc:
            raise PixelcutError("The Pixelcut result could not be downloaded.") from exc
        ctype = r.headers.get("content-type", "").split(";")[0].lower()
        if ctype not in {"image/jpeg", "image/png"}:
            raise PixelcutError("Pixelcut returned an unsupported output format.")
        return DownloadedResult(r.content, ctype)
