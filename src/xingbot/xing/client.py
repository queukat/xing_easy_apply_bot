from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from xingbot.csv_store import (
    ensure_job_listings_csv,
    normalize_schema,
    pad_row,
    read_csv_rows,
    write_csv_rows_atomic,
)
from xingbot.enums import ApplyStatus, JobCsvColumn
from xingbot.xing.config import XINGRuntimeConfig
from xingbot.xing.http import (
    HttpxTransport,
    XingHttpClient,
)
from xingbot.logging import logger
from xingbot.scraping.base import CookieScraper
from xingbot.scraping.xing_cards import (
    SearchCard,
    canonicalize_url,
    is_http_url as _is_http_url,
    parse_details_from_page,
    parse_search_cards,
)
from xingbot.settings import Settings
from xingbot.utils.human import ahuman_delay

NAV_TIMEOUT_MS = 45_000
LOGIN_TIMEOUT_MS = 25_000

_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")

_EN_STOP = {
    "the", "and", "with", "for", "you", "your", "we", "our", "role", "team", "experience",
    "responsibilities", "requirements", "skills", "years", "work", "engineer", "data",
    "software", "develop", "development", "cloud", "platform", "python", "design", "build",
    "implement", "knowledge", "ability", "strong", "good", "excellent", "required",
}
_DE_STOP = {
    "und", "der", "die", "das", "mit", "für", "wir", "du", "dich", "dein", "deine", "aufgaben",
    "profil", "kenntnisse", "bewerbung", "bewerben", "über", "uns", "vollzeit", "teilzeit",
    "erfahrung", "anforderungen", "wünschenswert",
}


class XingSafetyError(RuntimeError):
    """Raised when a human-only checkpoint is detected."""


@dataclass(frozen=True)
class XingApplyPayload:
    url: str
    message: str = ""
    attachments: tuple[str, ...] = ()
    meta: tuple[tuple[str, str], ...] = ()


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _clean_text(s: str, limit: int = 8000) -> str:
    s = " ".join((s or "").split())
    if len(s) > limit:
        return s[:limit] + " ...[truncated]..."
    return s


def _tokenize_words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def detect_lang(text: str, min_chars: int = 300) -> tuple[str, float, str]:
    txt = (text or "").strip()
    if len(txt) < min_chars:
        return "unknown", 0.0, "too_short"

    try:
        from langdetect import detect_langs  # type: ignore

        langs = detect_langs(txt[:5000])
        if langs:
            top = langs[0]
            code = getattr(top, "lang", "unknown")
            prob = float(getattr(top, "prob", 0.0))
            return str(code), prob, "langdetect"
    except Exception:
        pass

    words = _tokenize_words(txt[:8000])
    if not words:
        return "unknown", 0.0, "heuristic_empty"

    n = len(words)
    en_hits = sum(1 for w in words if w in _EN_STOP)
    de_hits = sum(1 for w in words if w in _DE_STOP)

    en_score = en_hits / n
    de_score = de_hits / n

    if de_score >= 0.02 and de_score > en_score * 1.3:
        conf = min(0.99, 0.5 + (de_score - en_score) * 8)
        return "de", conf, "heuristic_stopwords"

    if en_score >= 0.02 and en_score > de_score * 1.3:
        conf = min(0.99, 0.5 + (en_score - de_score) * 8)
        return "en", conf, "heuristic_stopwords"

    return "unknown", 0.2, "heuristic_uncertain"


async def _extract_job_description_fallback(page: Page) -> str:
    candidates = ["[data-testid='expandable-content']", "main", "article", "body"]
    best = ""
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            txt = (await loc.inner_text() or "").strip()
            if len(txt) > len(best):
                best = txt
        except Exception:
            continue
    return _clean_text(best)


async def _extract_external_apply_url(page: Page) -> str:
    selectors = [
        "a[href^='http']:has-text('Apply')",
        "a[href^='http']:has-text('Bewerben')",
        "a[href^='http'][target='_blank']",
        "a[href^='http'][rel*='noopener']",
        "a[href^='http'][rel*='noreferrer']",
    ]
    for sel in selectors:
        try:
            a = await page.query_selector(sel)
            if not a:
                continue
            href = (await a.get_attribute("href") or "").strip()
            if _is_http_url(href):
                return href
        except Exception:
            continue
    return ""


async def _check_for_manual_gate(page: Page) -> None:
    text = ""
    try:
        body = page.locator("body").first
        if await body.count() > 0:
            text = ((await body.inner_text()) or "").lower()
    except Exception:
        text = ""

    flags = ("captcha", "recaptcha", "two-factor", "2fa", "verify", "security check")
    if any(flag in text for flag in flags):
        raise XingSafetyError("Manual verification (captcha/2FA) is required.")


async def _load_search_results(page: Page, target_cards: int, max_rounds: int) -> int:
    cards = page.locator("article[data-testid='job-search-result']")
    show_more = page.locator('button:has-text("Show more"), button:has-text("Mehr anzeigen")').first

    prev = await cards.count()
    stable = 0

    for _ in range(max_rounds):
        if prev >= target_cards:
            break

        clicked = False
        try:
            if await show_more.count() > 0 and await show_more.is_visible():
                await show_more.scroll_into_view_if_needed()
                await ahuman_delay(0.3, 0.7)
                await show_more.click(timeout=5000)
                clicked = True
        except Exception:
            clicked = False

        if not clicked:
            try:
                if prev > 0:
                    await cards.nth(prev - 1).scroll_into_view_if_needed()
                    await ahuman_delay(0.2, 0.4)
                await page.mouse.wheel(0, 2200)
            except Exception:
                pass

        await ahuman_delay(0.9, 1.6)

        cur = await cards.count()
        if cur <= prev:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        prev = cur

    return prev


class XingAuth(CookieScraper):
    def __init__(self, settings: Settings):
        super().__init__(cookies_file=settings.xing_cookies_file)
        self.settings = settings
        self._logger = logger.bind(component="xing.auth")

    async def _dump_debug(self, page: Page, reason: str) -> None:
        self.settings.debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            png = self.settings.debug_dir / f"xing_{ts}_{reason}.png"
            await page.screenshot(path=str(png), full_page=True)
            self._logger.warning("[Xing] Debug screenshot: {}", png)
        except Exception:
            pass
        try:
            html = self.settings.debug_dir / f"xing_{ts}_{reason}.html"
            content = await page.content()
            html.write_text(content, encoding="utf-8")
            self._logger.warning("[Xing] Debug html: {}", html)
        except Exception:
            pass

    async def _goto(self, page: Page, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    async def _perform_login(self, page: Page, email: str, password: str) -> None:
        try:
            await page.context.clear_cookies()
        except Exception:
            pass

        await self._goto(page, "https://login.xing.com/")
        await ahuman_delay(0.8, 1.4)

        try:
            await page.wait_for_selector("form[data-qa='login-form']", timeout=20_000)
        except Exception:
            await self._dump_debug(page, "no_login_form")
            raise RuntimeError("XING login form not found")

        username = page.locator("input[data-qa='username'], #username")
        pwd = page.locator("input[data-qa='password'], #password")
        if await username.count() == 0 or await pwd.count() == 0:
            await self._dump_debug(page, "no_login_inputs")
            raise RuntimeError("XING login inputs not found")

        await username.first.fill(email)
        await ahuman_delay(0.2, 0.4)
        await pwd.first.fill(password)
        await ahuman_delay(0.2, 0.4)

        submit = page.locator("form[data-qa='login-form'] button[type='submit']")
        if await submit.count() == 0:
            await self._dump_debug(page, "no_submit")
            raise RuntimeError("XING submit button not found")

        await submit.first.click()
        try:
            await page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
        except Exception:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=LOGIN_TIMEOUT_MS)
            except Exception:
                pass

        await ahuman_delay(1.2, 2.0)
        try:
            await self._goto(page, "https://www.xing.com")
        except Exception:
            pass
        await ahuman_delay(0.8, 1.4)

    async def is_logged_in(self, page: Page) -> bool:
        url = (page.url or "").lower()
        if "login.xing.com" in url or "/login" in url or "anmelden" in url:
            return False

        selectors = [
            "img[data-testid='header-profile-logo']",
            "[data-testid='top-bar-profile-progress-badge']",
            "[class*='me-menu-dropdown__ProfileImageMeMenuContainer']",
        ]
        for sel in selectors:
            try:
                if await page.query_selector(sel):
                    return True
            except Exception:
                pass
        return False

    async def ensure_logged_in(self, page: Page) -> bool:
        await self.load_cookies(page)

        try:
            await self._goto(page, "https://www.xing.com")
        except Exception:
            pass

        await ahuman_delay(0.8, 1.4)
        if await self.is_logged_in(page):
            await self.save_cookies(page)
            return True

        if not self.settings.xing_email or not self.settings.xing_password:
            await self._dump_debug(page, "no_creds")
            self._logger.error("[Xing] Missing XING_EMAIL/XING_PASSWORD")
            return False

        try:
            await self._perform_login(page, self.settings.xing_email, self.settings.xing_password)
        except Exception as e:
            self._logger.error("[Xing] login crashed: {}", e)
            await self._dump_debug(page, "login_exception")
            return False

        if await self.is_logged_in(page):
            await self.save_cookies(page)
            return True

        await self._dump_debug(page, "login_failed")
        return False


class XingClient:
    def __init__(
        self,
        settings: Settings,
        *,
        config: Optional[XINGRuntimeConfig] = None,
        http_client: Optional[XingHttpClient] = None,
        max_actions_per_run: int | None = None,
        action_interval_s: float | None = None,
        dry_run: bool | None = None,
        confirm_send: bool = False,
    ) -> None:
        self.settings = settings
        self.auth = XingAuth(settings)
        self.config = config or XINGRuntimeConfig.from_settings(settings)
        self.confirm_send = bool(confirm_send) if confirm_send else self.config.safety.confirm_send_default
        self.dry_run = bool(dry_run) if dry_run is not None else self.config.safety.dry_run_default
        self.max_actions = (
            int(max_actions_per_run)
            if max_actions_per_run is not None
            else self.config.safety.max_actions_per_run
        )
        self.action_interval_s = (
            float(action_interval_s)
            if action_interval_s is not None
            else self.config.safety.action_interval_s
        )

        if http_client is None:
            http_client = XingHttpClient(
                transport=HttpxTransport(
                    timeout_s=self.config.http.timeout_s,
                    user_agent=self.config.http.user_agent,
                    proxy=self.config.http.proxy,
                ),
                retry=self.config.retry,
                rate_limit=self.config.rate_limit,
            )
        self.http = http_client

        self._touched = 0
        self._actions_taken = 0
        self._run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
        self._logger = logger.bind(component="xing", action="client", run_id=self._run_id)

    async def ensure_logged_in(self, page: Page) -> bool:
        return await self.auth.ensure_logged_in(page)

    async def close(self) -> None:
        await self.http.close()

    async def list_jobs(self, page: Page) -> list[SearchCard]:
        return await self._list_jobs_logged(page)

    async def _list_jobs_logged(self, page: Page) -> list[SearchCard]:
        log = self._logger.bind(action="collect_jobs", source="listing")
        cards: list[SearchCard] = []
        for src in self.settings.initial_xing_urls:
            src = (src or "").strip()
            if not src:
                continue
            try:
                await page.goto(src, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                log.warning("[Xing] Timeout opening search URL: {}", src)
                continue

            await ahuman_delay(1.2, 2.0)
            if not await self.auth.is_logged_in(page):
                raise XingSafetyError("Not logged in while listing jobs.")

            await _check_for_manual_gate(page)
            await _load_search_results(page, target_cards=120, max_rounds=self.settings.max_scrolls)
            parsed = await parse_search_cards(page)
            cards.extend(parsed)
            await ahuman_delay(0.2, 0.4)
        return cards

    def _build_payload(
        self,
        *,
        job_url: str,
        message: str = "",
        attachments: Iterable[Path] = (),
        metadata: dict[str, str] | None = None,
    ) -> XingApplyPayload:
        ordered_attachments = tuple(str(a) for a in attachments if str(a))
        ordered_meta = tuple((k, v) for k, v in (metadata or {}).items())
        return XingApplyPayload(
            url=job_url,
            message=message or "",
            attachments=ordered_attachments,
            meta=(
                ("job_url", job_url),
                ("source", "xing_client"),
                ("dry_run", str(bool(self.dry_run))),
            ) + ordered_meta,
        )

    async def _wait_between_actions(self) -> None:
        if not self.config.safety.rate_limit_enabled or self.action_interval_s <= 0:
            return
        await ahuman_delay(self.action_interval_s, self.action_interval_s * 1.2)

    async def _probe(self, url: str) -> bool:
        try:
            response = await self.http.request("GET", url)
            return response.status_code < 500
        except Exception:
            return False

    def _validate_contract(self, row: list[str], idx_url: int) -> bool:
        url = (row[idx_url] or "").strip()
        return bool(url)

    async def _extract_external_apply_url(self, page: Page) -> str:
        return await _extract_external_apply_url(page)

    async def _append_stats(self, stats_csv: Path, source_url: str, collected_count: int) -> None:
        exists = stats_csv.exists()
        stats_csv.parent.mkdir(parents=True, exist_ok=True)
        with stats_csv.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["URL", "Count", "Date"])
            w.writerow([source_url, str(int(collected_count)), _now_iso()])

    @staticmethod
    def _safe_float(val: str, default: float = 0.0) -> float:
        try:
            return float(str(val).replace(",", "."))
        except Exception:
            return default

    async def collect_jobs(self, page: Page) -> int:
        started_at = datetime.now()
        ensure_job_listings_csv(self.settings.job_listings_csv)

        if not await self.auth.ensure_logged_in(page):
            self._logger.error("[Xing] collect aborted: not logged in.")
            return 0

        headers, data = read_csv_rows(self.settings.job_listings_csv)
        headers, data = normalize_schema(headers, data)
        write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)

        idx_url = headers.index(JobCsvColumn.URL.value)
        idx_status = headers.index(JobCsvColumn.APPLY_STATUS.value)
        idx_exturl = headers.index(JobCsvColumn.EXTERNAL_URL.value)
        idx_desc = headers.index(JobCsvColumn.DESCRIPTION.value)
        idx_score = headers.index(JobCsvColumn.GPT_SCORE.value)
        idx_reason = headers.index(JobCsvColumn.GPT_REASON.value)
        idx_date = headers.index(JobCsvColumn.INSERTION_DATE.value)

        existing_urls: set[str] = set()
        for row in data:
            row = pad_row(row, headers)
            u = (row[idx_url] or "").strip()
            if u:
                existing_urls.add(canonicalize_url(u))

        total_saved = 0
        details_page: Page | None = None
        try:
            details_page = await page.context.new_page()
        except Exception:
            details_page = None

        for src in self.settings.initial_xing_urls:
            src = (src or "").strip()
            if not src:
                continue
            src_log = self._logger.bind(action="collect_jobs", source_url=src)

            src_log.info("[Xing] Collect from: {}", src)
            try:
                await page.goto(src, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                src_log.warning("[Xing] Timeout opening search URL: {}", src)
                await self._append_stats(self.settings.stats_csv, src, 0)
                continue

            await ahuman_delay(1.2, 2.0)

            if not await self.auth.is_logged_in(page):
                src_log.error("[Xing] Lost login on search page.")
                return total_saved

            try:
                await _check_for_manual_gate(page)
            except XingSafetyError as exc:
                src_log.warning("[Xing] Safety gate hit on search page: {}", exc)
                return total_saved

            try:
                await _load_search_results(page, target_cards=120, max_rounds=self.settings.max_scrolls)
            except Exception:
                # graceful stop if page became unstable
                src_log.warning("[Xing] Failed to expand search results for {}", src)

            cards: list[SearchCard] = await parse_search_cards(page)
            src_log.info("[Xing] Parsed cards: {}", len(cards))

            for card in cards:
                if total_saved >= self.settings.max_jobs_collected:
                    src_log.info("[Xing] Reached MAX_JOBS_COLLECTED, stopping.")
                    break

                if card.canonical_url in existing_urls:
                    continue
                existing_urls.add(card.canonical_url)

                if card.is_external:
                    row = [""] * len(headers)
                    row[idx_url] = card.href
                    row[idx_status] = ApplyStatus.EXTERNAL.value
                    row[idx_exturl] = card.href
                    row[idx_desc] = f"[EXTERNAL] {card.title}"
                    row[idx_score] = ""
                    row[idx_reason] = ""
                    row[idx_date] = _now_iso()
                    data.append(row)
                    total_saved += 1
                    if total_saved % 10 == 0:
                        write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
                    continue

                use_page = details_page or page
                try:
                    await use_page.goto(card.href, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    continue
                await ahuman_delay(1.0, 2.0)
                try:
                    await _check_for_manual_gate(use_page)
                except XingSafetyError as exc:
                    src_log.warning("[Xing] Safety gate hit on job page {}: {}", card.href, exc)
                    continue

                if not await self.auth.is_logged_in(use_page):
                    src_log.error("[Xing] Lost login on job page.")
                    return total_saved

                try:
                    details = await parse_details_from_page(use_page, card.href)
                    desc = details.description_text or ""
                except Exception:
                    desc = ""

                if not desc:
                    desc = await _extract_job_description_fallback(use_page)

                desc = _clean_text(desc)
                row = [""] * len(headers)
                row[idx_url] = card.href
                row[idx_status] = ApplyStatus.PENDING.value
                row[idx_desc] = desc
                row[idx_score] = ""
                row[idx_reason] = ""
                row[idx_date] = _now_iso()
                row[idx_exturl] = ""

                if self.settings.filter_by_description_lang:
                    lang, _conf, _method = detect_lang(desc, min_chars=300)
                    if lang == "unknown" and self.settings.keep_unknown_lang:
                        pass
                    elif lang not in self.settings.allowed_langs:
                        row[idx_status] = ApplyStatus.NOT_ALLOWED_LANG.value
                        data.append(row)
                        total_saved += 1
                    continue

                ext = await _extract_external_apply_url(use_page)
                row[idx_exturl] = ext
                data.append(row)
                total_saved += 1

                if total_saved % 10 == 0:
                    write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)

        write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
        self._logger.info(
            "[Xing] Collection finished. sources={} total_appended={}",
            len(self.settings.initial_xing_urls),
            total_saved,
        )
        self._logger.info(
            "[Xing] Collection duration: {:.2f}s",
            (datetime.now() - started_at).total_seconds(),
        )
        return total_saved

    async def apply_to_relevant_jobs(
        self,
        page: Page,
        min_score: float | None = None,
        *,
        message: str = "",
        attachments: tuple[Path, ...] = (),
    ) -> int:
        started_at = datetime.now()
        log = self._logger.bind(action="apply_jobs")
        ensure_job_listings_csv(self.settings.job_listings_csv)

        if not await self.auth.ensure_logged_in(page):
            log.error("[Xing] apply aborted: not logged in.")
            return 0

        headers, data = read_csv_rows(self.settings.job_listings_csv)
        if not headers:
            return 0
        headers, data = normalize_schema(headers, data)
        write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)

        idx_url = headers.index(JobCsvColumn.URL.value)
        idx_status = headers.index(JobCsvColumn.APPLY_STATUS.value)
        idx_score = headers.index(JobCsvColumn.GPT_SCORE.value)
        idx_ext = headers.index(JobCsvColumn.EXTERNAL_URL.value)

        threshold = float(min_score) if min_score is not None else float(self.settings.relevance_threshold)
        touched = 0
        actions_taken = 0

        def can_take(status_norm: str) -> bool:
            return status_norm in {"", ApplyStatus.PENDING.value, ApplyStatus.UNCERTAIN.value}

        for i, row in enumerate(data):
            row = pad_row(row, headers)
            if actions_taken >= self.max_actions:
                log.info("[Xing] Safety limit reached ({} actions).", self.max_actions)
                break

            url = (row[idx_url] or "").strip()
            if not self._validate_contract(row, idx_url):
                continue

            status_norm = ApplyStatus.normalize(row[idx_status])
            if not can_take(status_norm):
                continue

            score_val = self._safe_float(row[idx_score], 0.0)
            if score_val < threshold:
                continue

            if self.dry_run:
                payload = self._build_payload(
                    job_url=url,
                    message=message,
                    attachments=attachments,
                    metadata={"action": "apply_dry_run"},
                )
                log.info("[Xing][dry-run] {}", payload)
                row[idx_status] = (
                    ApplyStatus.DONE.value if row[idx_status].strip() else ApplyStatus.PENDING.value
                )
                data[i] = row
                touched += 1
                if touched % 10 == 0:
                    write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
                continue

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await _check_for_manual_gate(page)
            except PlaywrightTimeoutError:
                row[idx_status] = ApplyStatus.TIMEOUT.value
                data[i] = row
                touched += 1
                continue
            except XingSafetyError as exc:
                log.warning("[Xing] Safety gate hit on apply route for {}: {}", url, exc)
                break

            await ahuman_delay(1.0, 2.0)

            if not await self.auth.is_logged_in(page):
                log.error("[Xing] Lost login during apply.")
                return touched

            ext = (row[idx_ext] or "").strip()
            if not ext:
                extracted = self._extract_external_apply_url(page)
                if hasattr(extracted, "__await__"):
                    ext = await extracted
                else:
                    ext = str(extracted)
                row[idx_ext] = ext

            if ext and _is_http_url(ext):
                row[idx_status] = ApplyStatus.EXTERNAL.value
                data[i] = row
                touched += 1
                if touched % 10 == 0:
                    write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
                continue

            apply_btn = None
            for sel in [
                "button:has-text('Apply')",
                "button:has-text('Bewerben')",
                "a:has-text('Apply')",
                "a:has-text('Bewerben')",
                "button[data-testid*='apply']",
                "a[data-testid*='apply']",
            ]:
                try:
                    apply_btn = await page.query_selector(sel)
                    if apply_btn:
                        break
                except Exception:
                    continue

            if not apply_btn:
                row[idx_status] = ApplyStatus.UNCERTAIN.value
                data[i] = row
                touched += 1
                if touched % 10 == 0:
                    write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
                continue

            if self.confirm_send:
                answer = input(f"[Xing] Send application for {url}? [y/N]: ").strip().lower()
                if answer not in {"y", "yes"}:
                    row[idx_status] = ApplyStatus.PENDING.value
                    data[i] = row
                    touched += 1
                    log.info("[Xing] Skipped by user confirmation: {}", url)
                    if touched % 10 == 0:
                        write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
                    continue

            try:
                await self._wait_between_actions()
                await apply_btn.click()
                await ahuman_delay(1.0, 2.0)
                row[idx_status] = ApplyStatus.DONE.value
                actions_taken += 1
            except Exception as e:
                row[idx_status] = ApplyStatus.ERROR_EASY.value
                log.warning("[Xing] failed to click apply for {}: {}", url, e)

            data[i] = row
            touched += 1
            if touched % 10 == 0:
                write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)

        self._touched = touched
        self._actions_taken = actions_taken
        write_csv_rows_atomic(self.settings.job_listings_csv, headers, data)
        log.info("[Xing] Apply stage finished. touched={} actions_taken={}", touched, actions_taken)
        log.info(
            "[Xing] Apply duration: {:.2f}s",
            (datetime.now() - started_at).total_seconds(),
        )
        return touched
