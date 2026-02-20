from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _getenv(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v


def _getenv_int(name: str, default: int) -> int:
    try:
        return int(_getenv(name, str(default)).strip())
    except Exception:
        return default


def _getenv_float(name: str, default: float) -> float:
    try:
        return float(_getenv(name, str(default)).strip().replace(",", "."))
    except Exception:
        return default


def _getenv_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _parse_env_file(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip().strip("'\"")
        if not k:
            continue
        os.environ.setdefault(k, v)


def _default_int(name: str, default: int) -> int:
    try:
        return _getenv_int(name, default)
    except Exception:
        return default


def _default_float(name: str, default: float) -> float:
    try:
        return _getenv_float(name, default)
    except Exception:
        return default


def _default_bool(name: str, default: bool) -> bool:
    try:
        return _getenv_bool(name, default)
    except Exception:
        return default


def _parse_comma_list(raw: str) -> set[str]:
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def _parse_csv_ints(raw: str, fallback: tuple[int, ...]) -> tuple[int, ...]:
    out: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(int(item))
        except Exception:
            continue
    if not out:
        return fallback
    return tuple(out)


def _default_xing_urls() -> list[str]:
    # твой текущий набор, как было в core/constants.py
    return [
        "https://www.xing.com/jobs/search?keywords=data&page=2&paging_context=global_search&sort=date&id=c5b2b1e022f743641a624bfdc126dc87&country=de.02516e*ch.e594f5*at.ef7781*lu.5f1463",
        "https://www.xing.com/jobs/search?keywords=Big%20Data%20Engineer&page=2&paging_context=global_search&sort=date&id=b5a1e4a30bcd8a16c88707fdb5e91a25&country=de.02516e*ch.e594f5*at.ef7781*lu.5f1463&sc_o=jobs_search_button",
        "https://www.xing.com/jobs/search?keywords=big%20data&page=2&paging_context=global_search&sort=date&id=36fd461ce3d9d9975167b2541e4f246f&country=de.02516e*ch.e594f5*at.ef7781*lu.5f1463&sc_o=jobs_search_button",
        "https://www.xing.com/jobs/search?keywords=etl&page=2&paging_context=global_search&sort=date&id=6f71c1f3c104c7411f68f32c8d895605&country=de.02516e*ch.e594f5*at.ef7781*lu.5f1463&sc_o=jobs_search_button",
        "https://www.xing.com/jobs/search/ki?keywords=Prompt%20Engineer&tt=fabi.job-search.query-generation.earn-more%3A36dc2bab3e1f4ea4acba40094e0069fd&id=e16f71a0fe75f2e7bee4ab31af7409a3",
    ]


def _parse_urls_env(raw: str) -> list[str]:
    if not raw.strip():
        return []
    # поддержка: переносы строк или ;
    parts = []
    for chunk in raw.replace(";", "\n").splitlines():
        u = chunk.strip()
        if u:
            parts.append(u)
    return parts


@dataclass(frozen=True)
class Settings:
            # project paths
    root: Path
    job_listings_csv: Path
    stats_csv: Path
    xing_cookies_file: Path
    debug_dir: Path
    user_data_dir: Path

    resume_yaml: Path
    styles_css: Path

    # credentials
    xing_email: str
    xing_password: str
    openai_api_key: str

    # models
    gpt_eval_model: str

    # pipeline settings
    initial_xing_urls: list[str]
    relevance_threshold: float

    max_scrolls: int
    max_jobs_collected: int

    # language filter (for XING collect via description lang)
    filter_by_description_lang: bool
    allowed_langs: set[str]
    keep_unknown_lang: bool

    # runtime
    headless: bool
    user_agent: str
    xing_http_timeout_s: float
    xing_retries: int
    xing_backoff_base_s: float
    xing_backoff_max_s: float
    xing_retry_statuses: tuple[int, ...]
    xing_action_interval_s: float
    xing_max_actions_per_run: int
    xing_dry_run_default: bool
    xing_rate_limit_enabled: bool
    xing_confirm_send_default: bool
    xing_proxy: str | None

    @classmethod
    def load(cls) -> "Settings":
        root = Path(__file__).resolve().parents[2]  # .../src/xingbot/settings.py -> repo root
        _parse_env_file(root)

        urls = _parse_urls_env(_getenv("XING_URLS", ""))
        if not urls:
            urls = _default_xing_urls()

        headless = _getenv_bool("HEADLESS", True)
        user_agent = _getenv(
            "XING_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        retry_statuses_raw = _getenv("XING_RETRY_STATUS", "429,500,502,503,504")

        return cls(
            root=root,
            job_listings_csv=root / "job_listings.csv",
            stats_csv=root / "stats.csv",
            xing_cookies_file=root / "xing_cookies.pkl",
            debug_dir=root / "debug_artifacts",
            user_data_dir=root / "user_data",
            resume_yaml=root / "resume.yaml",
            styles_css=root / "styles.css",
            xing_email=_getenv("XING_EMAIL", ""),
            xing_password=_getenv("XING_PASSWORD", ""),
            openai_api_key=_getenv("OPENAI_API_KEY", ""),
            gpt_eval_model=_getenv("GPT_EVAL_MODEL", "gpt-5-mini"),
            initial_xing_urls=urls,
            relevance_threshold=_getenv_float("RELEVANCE_SCORE_THRESHOLD", 8.0),
            max_scrolls=_getenv_int("MAX_SCROLLS", 40),
            max_jobs_collected=_getenv_int("MAX_JOBS_COLLECTED", 500),
            filter_by_description_lang=_getenv_bool("FILTER_BY_DESCRIPTION_LANG", True),
            allowed_langs=_parse_comma_list(_getenv("XING_ALLOWED_LANGS", "en")),
            keep_unknown_lang=_getenv_bool("KEEP_UNKNOWN_LANG", True),
            headless=headless,
            user_agent=user_agent,
            xing_http_timeout_s=_default_float("XING_HTTP_TIMEOUT_S", 8.0),
            xing_retries=_default_int("XING_RETRIES", 3),
            xing_backoff_base_s=_default_float("XING_BACKOFF_BASE_S", 0.7),
            xing_backoff_max_s=_default_float("XING_BACKOFF_MAX_S", 4.5),
            xing_retry_statuses=_parse_csv_ints(retry_statuses_raw, (429, 500, 502, 503, 504)),
            xing_action_interval_s=_default_float("XING_ACTION_INTERVAL_S", 20.0),
            xing_max_actions_per_run=_default_int("XING_MAX_ACTIONS_PER_RUN", 1),
            xing_dry_run_default=_default_bool("XING_DRY_RUN_DEFAULT", False),
            xing_rate_limit_enabled=_default_bool("XING_RATE_LIMIT_ENABLED", True),
            xing_confirm_send_default=_default_bool("XING_CONFIRM_SEND_DEFAULT", False),
            xing_proxy=(lambda v: v if v else None)(_getenv("XING_PROXY", "")),
        )
