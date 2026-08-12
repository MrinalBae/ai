from .pixelcut import run
async def remove_background(image_url: str, scale: int):
    if scale not in (1, 2, 4):
        raise ValueError("Scale must be 1, 2 or 4.")
    data = {"image_url": image_url, "format": "png"}
    if scale != 1:
        data["scale"] = str(scale)
    return await run("/v1/remove-background", data)
