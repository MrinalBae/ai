from .pixelcut import run

def sides_from_selection(selection, amount):
    amount = int(amount)
    if amount < 0 or amount > 10000:
        raise ValueError("Expand amount must be between 0 and 10000 pixels.")
    return {
        "top": amount if selection in ("top", "all") else 0,
        "bottom": amount if selection in ("bottom", "all") else 0,
        "left": amount if selection in ("left", "all") else 0,
        "right": amount if selection in ("right", "all") else 0,
    }

async def expand(image_url: str, selection: str, amount: int, scale: int):
    if scale not in (1, 2, 4):
        raise ValueError("Scale must be 1, 2 or 4.")
    data = {"image_url": image_url, **{k: str(v) for k,v in sides_from_selection(selection, amount).items()}}
    if scale != 1:
        data["scale"] = str(scale)
    return await run("/v1/outpaint", data)
