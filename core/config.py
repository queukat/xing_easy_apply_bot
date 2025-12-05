import os
from playwright.async_api import async_playwright
from core.logger import logger

async def init_browser(headless: bool = False):
    """
    Инициализирует Playwright-браузер (async) в режиме persistent_context.
    Возвращает (playwright, context, page).
    """
    user_data_dir = os.path.join(os.getcwd(), "user_data")
    os.makedirs(user_data_dir, exist_ok=True)

    # Запускаем Playwright вручную (без async with),
    # чтобы браузер не закрывался сразу при выходе из блока.
    playwright = await async_playwright().start()

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=headless,
        viewport=None,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/110.0.0.0 Safari/537.36"
        ),
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1920,1080",
        ]
    )

    page = await context.new_page()
    logger.info(f"[Config] Browser init: headless={headless}")

    return playwright, context, page
