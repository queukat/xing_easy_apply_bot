from __future__ import annotations

from pathlib import Path
from playwright.async_api import Page

from xingbot.settings import Settings
from xingbot.xing.client import XingClient, detect_lang


async def scrape_xing_jobs(page: Page, settings: Settings) -> None:
    client = XingClient(settings)
    await client.collect_jobs(page)


async def apply_to_relevant_jobs(
    page: Page,
    settings: Settings,
    min_score: float | None = None,
    message: str = "",
    attachments: tuple[str, ...] = (),
    *,
    dry_run: bool | None = None,
    confirm_send: bool = False,
    max_actions: int | None = None,
    action_interval_s: float | None = None,
) -> None:
    client = XingClient(
        settings,
        dry_run=dry_run,
        confirm_send=confirm_send,
        max_actions_per_run=max_actions,
        action_interval_s=action_interval_s,
    )
    await client.apply_to_relevant_jobs(
        page,
        min_score=min_score,
        message=message,
        attachments=tuple(Path(p) for p in attachments),
    )


__all__ = ["scrape_xing_jobs", "apply_to_relevant_jobs", "detect_lang"]
