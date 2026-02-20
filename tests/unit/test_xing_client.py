from __future__ import annotations

import csv
from pathlib import Path

import pytest

from xingbot.settings import Settings
from xingbot.xing.client import XingClient


class FakeButton:
    def __init__(self) -> None:
        self.clicked = 0

    async def click(self) -> None:
        self.clicked += 1


def test_build_payload_takes_message_and_attachments(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = XingClient(settings)
    payload = client._build_payload(
        job_url="https://www.xing.com/jobs/demo",
        message="Hello",
        attachments=(tmp_path / "a.txt", tmp_path / "b.txt"),
        metadata={"note": "x"},
    )

    assert payload.url == "https://www.xing.com/jobs/demo"
    assert payload.message == "Hello"
    assert payload.attachments == (str(tmp_path / "a.txt"), str(tmp_path / "b.txt"))
    assert ("note", "x") in payload.meta




class FakePage:
    def __init__(self, button: FakeButton | None = None) -> None:
        self.gotos: list[str] = []
        self.button = button

    async def goto(self, url: str, **_: object) -> None:
        self.gotos.append(url)

    async def query_selector(self, _: str) -> FakeButton | None:
        return self.button


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        job_listings_csv=tmp_path / "job_listings.csv",
        stats_csv=tmp_path / "stats.csv",
        xing_cookies_file=tmp_path / "xing_cookies.pkl",
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


def _prepare_csv(path: Path) -> None:
    path.write_text(
        "URL,ApplyStatus,ExternalURL,Description,GPT_Score,GPT_Reason,InsertionDate\n"
        "https://www.xing.com/jobs/one,, , ,9, ,2026-01-01\n"
    )


def _prepare_two_csv(path: Path) -> None:
    path.write_text(
        "URL,ApplyStatus,ExternalURL,Description,GPT_Score,GPT_Reason,InsertionDate\n"
        "https://www.xing.com/jobs/one,, , ,9, ,2026-01-01\n"
        "https://www.xing.com/jobs/two,, , ,9, ,2026-01-01\n"
    )


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    return rows[0], rows[1:]


@pytest.mark.asyncio
async def test_xing_client_apply_dry_run_and_updates_status(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _prepare_csv(settings.job_listings_csv)
    page = FakePage()
    client = XingClient(settings, dry_run=True, max_actions_per_run=1, action_interval_s=0.0)

    async def _ensure_logged_in(_: object) -> bool:
        return True

    async def _is_logged_in(_: object) -> bool:
        return True

    async def _check(*_) -> None:
        return None

    monkeypatch.setattr(client.auth, "ensure_logged_in", _ensure_logged_in)
    monkeypatch.setattr(client.auth, "is_logged_in", _is_logged_in)
    monkeypatch.setattr("xingbot.xing.client._check_for_manual_gate", _check)
    monkeypatch.setattr(client, "_extract_external_apply_url", lambda _: "")

    touched = await client.apply_to_relevant_jobs(page)
    assert touched == 1

    _, rows = _read_csv_rows(settings.job_listings_csv)
    assert rows[0][1] == "pending"


@pytest.mark.asyncio
async def test_xing_client_apply_respects_max_actions_and_confirm(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _prepare_two_csv(settings.job_listings_csv)
    button = FakeButton()
    page = FakePage(button=button)
    client = XingClient(settings, dry_run=False, max_actions_per_run=1, action_interval_s=0.0, confirm_send=True)

    async def _ensure_logged_in(_: object) -> bool:
        return True

    async def _is_logged_in(_: object) -> bool:
        return True

    async def _check(*_) -> None:
        return None

    monkeypatch.setattr(client.auth, "ensure_logged_in", _ensure_logged_in)
    monkeypatch.setattr(client.auth, "is_logged_in", _is_logged_in)
    monkeypatch.setattr("xingbot.xing.client._check_for_manual_gate", _check)
    monkeypatch.setattr(client, "_extract_external_apply_url", lambda _: "")

    monkeypatch.setattr("builtins.input", lambda _: "y")
    touched = await client.apply_to_relevant_jobs(page)

    assert touched == 1
    assert button.clicked == 1
    _, rows = _read_csv_rows(settings.job_listings_csv)
    assert rows[0][1] == "done"
