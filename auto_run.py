import random
import asyncio

from main import run_all_stages
from core.config import init_browser
from core.logger import logger  # если хочешь логировать, а не print


async def auto_run():
    # Открываем браузер один раз, headless-режим
    pw, context, page = await init_browser(headless=True)

    try:
        while True:
            logger.info("[auto_run] Запускаем все этапы в авто-режиме...")
            await run_all_stages(page)

            sleep_seconds = random.uniform(4 * 3600, 6 * 3600)
            logger.info(f"[auto_run] Засыпаем на {int(sleep_seconds)} секунд...")
            await asyncio.sleep(sleep_seconds)
    finally:
        logger.info("[auto_run] Закрываем браузер...")
        await context.close()
        await pw.stop()


def main():
    asyncio.run(auto_run())


if __name__ == "__main__":
    main()
