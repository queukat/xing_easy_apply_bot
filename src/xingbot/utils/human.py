from __future__ import annotations

import asyncio
import random
from typing import Any


async def ahuman_delay(min_s: float = 0.6, max_s: float = 1.4) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


async def move_cursor_to_element(page: Any, element: Any) -> None:
    try:
        box = await element.bounding_box()
        if not box:
            return
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        await page.mouse.move(x, y)
    except Exception:
        return
