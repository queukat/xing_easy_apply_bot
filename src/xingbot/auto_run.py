from __future__ import annotations

import asyncio
import random

from xingbot.browser import close_browser, open_browser
from xingbot.gpt.evaluator import evaluate_jobs
from xingbot.logging import logger
from xingbot.scraping.xing_scraper import apply_to_relevant_jobs, scrape_xing_jobs
from xingbot.settings import Settings


def _sleep_seconds(min_hours: float = 4.0, max_hours: float = 6.0) -> float:
    return random.uniform(min_hours * 3600.0, max_hours * 3600.0)


async def auto_run_forever() -> None:
    settings = Settings.load()
    session = await open_browser(settings)
    try:
        while True:
            logger.info("[auto] Run pipeline: collect -> evaluate -> apply")
            await scrape_xing_jobs(session.page, settings)
            await evaluate_jobs(settings)
            await apply_to_relevant_jobs(session.page, settings, min_score=None)

            s = _sleep_seconds(4.0, 6.0)
            logger.info("[auto] Sleep {} seconds", int(s))
            await asyncio.sleep(s)
    finally:
        await close_browser(session)


def main() -> None:
    asyncio.run(auto_run_forever())
