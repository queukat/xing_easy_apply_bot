from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from xingbot.logging import logger


class CookieScraper:
    """
    База: загрузка/сохранение cookies в pickle.
    """

    def __init__(self, cookies_file: Path):
        self.cookies_file = cookies_file

    @staticmethod
    def _ensure_parent(path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    async def load_cookies(self, page: Page) -> bool:
        if not self.cookies_file:
            return False
        if not self.cookies_file.exists():
            return False

        try:
            with self.cookies_file.open("rb") as f:
                cookies = pickle.load(f)
                if not isinstance(cookies, list):
                    raise ValueError("cookies payload is not list")
                await page.context.add_cookies(cookies)
            logger.info(
                "[cookies] loaded: {} (count={})",
                self.cookies_file,
                len(cookies),
            )
            return True
        except Exception as e:
            logger.warning("[cookies] failed to load {}: {}", self.cookies_file, e)
            try:
                bad = self.cookies_file.with_suffix(self.cookies_file.suffix + ".corrupt")
                os.replace(self.cookies_file, bad)
                logger.warning("[cookies] moved corrupt file to {}", bad)
            except Exception:
                pass
            return False

    async def save_cookies(self, page: Page) -> None:
        if not self.cookies_file:
            return
        try:
            cookies = await page.context.cookies()
            self._ensure_parent(self.cookies_file)
            with self.cookies_file.open("wb") as f:
                pickle.dump(cookies, f)
            logger.info(
                "[cookies] saved: {} (count={})",
                self.cookies_file,
                len(cookies),
            )
        except Exception as e:
            logger.warning("[cookies] failed to save {}: {}", self.cookies_file, e)
