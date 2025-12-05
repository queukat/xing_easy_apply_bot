# xing_o1_02_2025/services/scraping/base_scraper.py

import os
import pickle
from playwright.async_api import Page
from core.logger import logger


class BaseScraper:
    """
    Базовый скрапер: умеет грузить/сохранять куки, проверять авторизацию и т.п.
    Унаследуются xing_scraper.py, join_scraper.py и т.д.
    """

    def __init__(self, cookies_file_path: str = ""):
        """
        :param cookies_file_path: Путь к файлу cookies, если требуется сохранять/загружать их.
        """
        self.cookies_file = cookies_file_path

    async def load_cookies(self, page: Page) -> None:
        """
        Загружает cookies из файла и добавляет их в контекст страницы.
        Отсутствие файла не считается ошибкой — просто пропускаем.
        """
        if not self.cookies_file:
            logger.debug("[BaseScraper] Cookies file path is empty, skip loading.")
            return

        if not os.path.exists(self.cookies_file):
            logger.debug(f"[BaseScraper] Cookies file '{self.cookies_file}' not found, skip loading.")
            return

        try:
            with open(self.cookies_file, "rb") as f:
                cookies = pickle.load(f)

            await page.context.add_cookies(cookies)
            logger.info(f"[BaseScraper] Cookies loaded from '{self.cookies_file}'")

        except Exception as e:
            # сюда попадём, если файл битый, формат не тот и т.п.
            logger.warning(f"[BaseScraper] Cannot load cookies from '{self.cookies_file}': {e}")

    async def save_cookies(self, page: Page) -> None:
        """
        Сохраняет cookies из контекста страницы в файл.
        """
        if not self.cookies_file:
            logger.debug("[BaseScraper] Cookies file path is empty, skip saving.")
            return

        try:
            # Get cookies from page context (async call)
            cookies = await page.context.cookies()

            with open(self.cookies_file, "wb") as f:
                pickle.dump(cookies, f)

            logger.info(f"[BaseScraper] Cookies saved to '{self.cookies_file}'")

        except Exception as e:
            logger.warning(f"[BaseScraper] Cannot save cookies: {e}")
