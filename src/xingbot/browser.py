from __future__ import annotations

import os
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from xingbot.logging import logger
from xingbot.settings import Settings


@dataclass(frozen=True)
class BrowserSession:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


def _has_display() -> bool:
    if os.name == "nt":
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY") or os.getenv("MIR_SOCKET"))


def _effective_headless(requested_headless: bool) -> bool:
    if requested_headless:
        return True
    if _has_display():
        return False
    logger.warning("[browser] No display detected, forcing headless mode.")
    return True


async def open_browser(settings: Settings) -> BrowserSession:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=_effective_headless(bool(settings.headless)))
        context_kwargs: dict[str, object] = {}
        user_agent = (settings.user_agent or "").strip()
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        return BrowserSession(playwright=playwright, browser=browser, context=context, page=page)
    except Exception:
        logger.exception("[browser] Failed to open browser session.")
        try:
            await playwright.stop()
        except Exception:
            logger.exception("[browser] Failed to stop Playwright after open error.")
        raise


async def close_browser(session: BrowserSession | None) -> None:
    if session is None:
        return

    try:
        await session.context.close()
    except Exception:
        logger.exception("[browser] Failed to close browser context.")

    try:
        await session.browser.close()
    except Exception:
        logger.exception("[browser] Failed to close browser instance.")

    try:
        await session.playwright.stop()
    except Exception:
        logger.exception("[browser] Failed to stop Playwright.")


__all__ = ["BrowserSession", "open_browser", "close_browser"]

