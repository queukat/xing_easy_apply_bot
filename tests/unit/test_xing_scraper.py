from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from xingbot.settings import Settings
from xingbot.scraping import xing_scraper


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        job_listings_csv=tmp_path / "job_listings.csv",
        stats_csv=tmp_path / "stats.csv",
        xing_cookies_file=tmp_path / "xing_storage_state.json",
        debug_dir=tmp_path / "debug",
        user_data_dir=tmp_path / "user_data",
        resume_yaml=tmp_path / "resume.yaml",
        styles_css=tmp_path / "styles.css",
        xing_email="",
        xing_password="",
        openai_api_key="",
        gpt_eval_model="gpt-5-mini",
        initial_xing_urls=[],
        relevance_threshold=8.0,
        max_scrolls=1,
        max_jobs_collected=10,
        filter_by_description_lang=False,
        allowed_langs={"en"},
        keep_unknown_lang=True,
        headless=True,
        user_agent="unit-test",
        xing_http_timeout_s=2.0,
        xing_retries=1,
        xing_backoff_base_s=0.0,
        xing_backoff_max_s=0.0,
        xing_retry_statuses=(429, 500),
        xing_action_interval_s=0.0,
        xing_max_actions_per_run=1,
        xing_dry_run_default=False,
        xing_rate_limit_enabled=False,
        xing_confirm_send_default=False,
        xing_proxy=None,
    )


@pytest.mark.asyncio
async def test_scrape_and_apply_use_async_context_manager(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []

    class _FakeClient:
        def __init__(self, *_: Any, **__: Any) -> None:
            return None

        async def __aenter__(self) -> "_FakeClient":
            events.append("enter")
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            events.append("exit")

        async def collect_jobs(self, page: Any) -> None:
            events.append("collect")

        async def apply_to_relevant_jobs(self, page: Any, **kwargs: Any) -> None:
            events.append("apply")

    monkeypatch.setattr(xing_scraper, "XingClient", _FakeClient)
    settings = _settings(tmp_path)

    await xing_scraper.scrape_xing_jobs(page=object(), settings=settings)
    await xing_scraper.apply_to_relevant_jobs(page=object(), settings=settings, dry_run=True)

    assert events == ["enter", "collect", "exit", "enter", "apply", "exit"]

