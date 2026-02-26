from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from xingbot.logging import logger


class CookieScraper:
    """
    Base: load/save Playwright storage state in JSON format.
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
            payload = json.loads(self.cookies_file.read_text(encoding="utf-8"))
            cookies = payload.get("cookies")
            if not isinstance(payload, dict) or not isinstance(cookies, list):
                raise ValueError("storage_state payload is invalid")
            sanitized: list[dict[str, Any]] = []
            for item in cookies:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                value = str(item.get("value", ""))
                domain = str(item.get("domain", "")).strip()
                path = str(item.get("path", "")).strip() or "/"
                if not (name and domain):
                    continue
                sanitized.append(
                    {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": path,
                        "expires": item.get("expires", -1),
                        "httpOnly": bool(item.get("httpOnly", False)),
                        "secure": bool(item.get("secure", False)),
                        "sameSite": item.get("sameSite", "Lax"),
                    }
                )
            if sanitized:
                await page.context.add_cookies(sanitized)
            logger.info(
                "[cookies] loaded storage_state: {} (count={})",
                self.cookies_file,
                len(sanitized),
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
            payload = await page.context.storage_state()
            if not isinstance(payload, dict) or "cookies" not in payload:
                raise ValueError("invalid storage_state payload from context")
            self._ensure_parent(self.cookies_file)
            tmp = self.cookies_file.with_suffix(self.cookies_file.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.cookies_file)
            try:
                os.chmod(self.cookies_file, 0o600)
            except Exception:
                logger.debug("[cookies] cannot tighten file permissions: {}", self.cookies_file)
            logger.info(
                "[cookies] saved storage_state: {} (count={})",
                self.cookies_file,
                len(payload.get("cookies") or []),
            )
        except Exception as e:
            logger.warning("[cookies] failed to save {}: {}", self.cookies_file, e)
