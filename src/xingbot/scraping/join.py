# -*- coding: utf-8 -*-
"""
services/scraping/join.py

Hard-refactored join.com candidate applications completer.

Goals:
  - no blocking input() in default run
  - cleaner architecture: config, storage, auth, parser, filler
  - robust wizard flow (Chakra UI) + legacy fallback
  - atomic JSON DB writes
  - better diagnostics (optional screenshots/html on failures)

Env toggles:
  JOIN_INTERACTIVE=1              allow input() prompts
  JOIN_AUTO_FILL_UNKNOWN=0/1      default 1 (fill unknown with generic/fallback)
  JOIN_DEBUG_ARTIFACTS=0/1        default 1
  JOIN_FLASH_LOG_FILE=...         default "join_flash_failures.log"
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pickle
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from core.constants import (
    QUESTIONS_DB_FILE,
    JOIN_COOKIES_FILE,
    JOIN_EMAIL,
    JOIN_PASSWORD,
    RESUME_YAML_FILE,
    DEBUG_ARTIFACTS_DIR,
)
from core.logger import logger
from services.scraping.utils import ahuman_delay, move_cursor_to_element

# -----------------------------------------------------------------------------
# Constants / URLs
# -----------------------------------------------------------------------------
JOIN_CANDIDATE_URL = "https://join.com/candidate"
JOIN_LOGIN_URL = "https://join.com/auth/login/candidate?redirectUrl=%2Fcandidate"
TALENT_HOME_URL = "https://join.com/talent/home"
TALENT_APPLICATIONS_URL = "https://join.com/talent/applications"

MAX_PATH_LENGTH = 200  # PDF path limit (Windows, etc.)


# -----------------------------------------------------------------------------
# Small env helpers
# -----------------------------------------------------------------------------
def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None else v


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class JoinConfig:
    cookies_file: str = JOIN_COOKIES_FILE
    db_file: str = QUESTIONS_DB_FILE

    login_url: str = JOIN_LOGIN_URL
    home_url: str = TALENT_HOME_URL
    apps_url: str = TALENT_APPLICATIONS_URL

    email: str = JOIN_EMAIL
    password: str = JOIN_PASSWORD

    interactive: bool = _env_bool("JOIN_INTERACTIVE", False)
    auto_fill_unknown: bool = _env_bool("JOIN_AUTO_FILL_UNKNOWN", True)

    debug_artifacts: bool = _env_bool("JOIN_DEBUG_ARTIFACTS", True)
    debug_dir: str = DEBUG_ARTIFACTS_DIR

    flash_log_file: str = _env_str("JOIN_FLASH_LOG_FILE", "join_flash_failures.log")

    # parsing / loops
    apps_scrolls: int = int(_env_str("JOIN_APPS_SCROLLS", "5"))
    wizard_max_steps: int = int(_env_str("JOIN_WIZARD_MAX_STEPS", "20"))

    # availability default fallback
    default_days_to_start: int = int(_env_str("JOIN_DAYS_TO_START", "7"))


# -----------------------------------------------------------------------------
# Atomic JSON store (answers + translations)
# -----------------------------------------------------------------------------
class JoinStore:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Dict[str, str]] = {"join_answers": {}, "join_translations": {}}
        self._loaded = False

    def ensure(self) -> None:
        if not self.path:
            return
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            self.data = {"join_answers": {}, "join_translations": {}}
            self.save()

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path or not os.path.exists(self.path):
            self.data = {"join_answers": {}, "join_translations": {}}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
            if not isinstance(d, dict):
                d = {}
            d.setdefault("join_answers", {})
            d.setdefault("join_translations", {})
            if not isinstance(d["join_answers"], dict):
                d["join_answers"] = {}
            if not isinstance(d["join_translations"], dict):
                d["join_translations"] = {}
            self.data = d
        except Exception as e:
            logger.warning("[JoinStore] Failed to load {}: {}", self.path, e)
            self.data = {"join_answers": {}, "join_translations": {}}

    def save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning("[JoinStore] Failed to save {}: {}", self.path, e)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    @property
    def answers(self) -> Dict[str, str]:
        self.load()
        return self.data["join_answers"]

    @property
    def translations(self) -> Dict[str, str]:
        self.load()
        return self.data["join_translations"]


# -----------------------------------------------------------------------------
# Resume loader + simple mapping
# -----------------------------------------------------------------------------
def _load_resume_data() -> dict:
    # Keep compatibility if RESUME_YAML_FILE is already dict
    if isinstance(RESUME_YAML_FILE, dict):
        return RESUME_YAML_FILE
    if isinstance(RESUME_YAML_FILE, str) and RESUME_YAML_FILE:
        try:
            with open(RESUME_YAML_FILE, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            return d if isinstance(d, dict) else {}
        except Exception as e:
            logger.warning("[Join] Failed to load resume yaml {}: {}", RESUME_YAML_FILE, e)
            return {}
    return {}


def normalize_question_text(question_text: str) -> str:
    text_no_num = re.sub(r"^[0-9]+\.\s*", "", question_text.strip())
    text_no_num = re.sub(r"^[0-9]+\)\s*", "", text_no_num)
    return " ".join(text_no_num.strip().lower().split())


def get_default_answer_from_resume(question: str, cfg: JoinConfig, resume_data: dict) -> Optional[str]:
    """
    Extendable heuristic.
    Returns:
      - string for inputs/textarea
      - ISO date (YYYY-MM-DD) for datepicker questions
    """
    q = normalize_question_text(question)
    pi = resume_data.get("personal_information", {}) or {}
    availability = resume_data.get("availability", {}) or {}
    salary = resume_data.get("salary_expectations", {}) or resume_data.get("expected_salary", {}) or {}

    # City
    if "what city do you currently live in" in q or "in what city" in q:
        return (pi.get("city") or "").strip() or None

    # Country
    if "what country do you currently live in" in q or "which country" in q:
        return (pi.get("country") or "").strip() or None

    # Start date / availability
    if "when are you available to start" in q or "when can you start" in q or "start date" in q:
        days = availability.get("days")
        try:
            days_i = int(str(days).strip())
        except Exception:
            days_i = cfg.default_days_to_start
        target = dt.date.today() + dt.timedelta(days=days_i)
        return target.isoformat()

    # Salary expectations (best effort)
    if "expected yearly compensation" in q or "expected salary" in q or "salary expectation" in q:
        salary_range = None
        if isinstance(salary, str):
            salary_range = salary
        elif isinstance(salary, dict):
            salary_range = salary.get("salary_range") or salary.get("salary_range_usd") or salary.get("range")
        if isinstance(salary_range, str) and "-" in salary_range:
            low, high = salary_range.split("-", 1)
            try:
                low_i = int(re.sub(r"[^\d]", "", low))
                high_i = int(re.sub(r"[^\d]", "", high))
                mid = (low_i + high_i) // 2
            except Exception:
                mid = 45000
        else:
            # last resort: try to find digits anywhere
            digits = re.findall(r"\d{4,}", str(salary_range or ""))
            mid = int(digits[0]) if digits else 45000
        return str(mid)

    return None


# -----------------------------------------------------------------------------
# Translator (optional dependency)
# -----------------------------------------------------------------------------
class Translator:
    def __init__(self, cache: Dict[str, str]):
        self.cache = cache

    def translate(self, text: str, source_lang: str = "auto", target_lang: str = "ru") -> str:
        if not text:
            return ""
        key = f"{source_lang}->{target_lang}:{text}"
        if key in self.cache:
            return self.cache[key]
        try:
            # optional import
            from deep_translator import GoogleTranslator  # type: ignore

            translated = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
            if isinstance(translated, str) and translated.strip():
                self.cache[key] = translated
                return translated
        except Exception as e:
            logger.debug("[Join] Translation failed: {}", e)
        self.cache[key] = text
        return text


# -----------------------------------------------------------------------------
# Browser helpers
# -----------------------------------------------------------------------------
async def safe_wait_networkidle(page: Any, timeout_ms: int = 15000) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # fallback: domcontentloaded + small delay
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        await ahuman_delay(0.4, 0.9)


async def safe_goto(page: Any, url: str, timeout_ms: int = 45000) -> None:
    try:
        await page.goto(url, timeout=timeout_ms)
    except Exception as e:
        logger.warning("[Join] goto failed: {}: {}", url, e)
    await safe_wait_networkidle(page)


async def accept_cookies_join(page: Any) -> None:
    """
    Try to accept join.com cookie banner (CookieScript).
    """
    try:
        banner = await page.query_selector("#cookiescript_injected")
        if not banner:
            return
        accept_btn = await page.query_selector("#cookiescript_accept")
        if accept_btn:
            await accept_btn.click()
            await ahuman_delay(0.6, 1.2)
            return
        saveclose_btn = await page.query_selector("#cookiescript_save")
        if saveclose_btn:
            await saveclose_btn.click()
            await ahuman_delay(0.6, 1.2)
            return
    except Exception:
        return


async def dump_debug_artifacts(cfg: JoinConfig, page: Any, prefix: str) -> None:
    if not cfg.debug_artifacts:
        return
    try:
        Path(cfg.debug_dir).mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", prefix)[:60]
        png = os.path.join(cfg.debug_dir, f"join_{safe}_{ts}.png")
        html = os.path.join(cfg.debug_dir, f"join_{safe}_{ts}.html")
        try:
            await page.screenshot(path=png, full_page=True)
        except Exception:
            pass
        try:
            content = await page.content()
            with open(html, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass
        logger.info("[Join] Debug artifacts saved: {} / {}", png, html)
    except Exception as e:
        logger.debug("[Join] Failed to dump artifacts: {}", e)


async def read_flash_messages(page: Any) -> str:
    """
    Best-effort: collect toast/alert/modal error texts.
    """
    candidates = [
        # Chakra alerts / toasts
        "[role='alert']",
        ".chakra-alert",
        ".chakra-toast",
        "[data-testid*='toast']",
        "[data-testid*='notification']",
        "small[data-testid='FormError']",
    ]
    texts: list[str] = []
    for sel in candidates:
        try:
            els = await page.query_selector_all(sel)
            for el in els[:10]:
                t = (await el.inner_text()).strip()
                if t and t not in texts:
                    texts.append(t)
        except Exception:
            continue
    return " | ".join(texts)


def append_flash_log(cfg: JoinConfig, app_url: str, message: str) -> None:
    if not message:
        return
    try:
        with open(cfg.flash_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now().isoformat()}] {app_url} :: {message}\n")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Cookies + Auth
# -----------------------------------------------------------------------------
class JoinAuth:
    def __init__(self, cfg: JoinConfig):
        self.cfg = cfg

    async def load_cookies(self, context: Any) -> None:
        if self.cfg.cookies_file and os.path.exists(self.cfg.cookies_file):
            try:
                with open(self.cfg.cookies_file, "rb") as f:
                    cookies = pickle.load(f)
                await context.add_cookies(cookies)
                logger.info("[Join] Cookies loaded.")
            except Exception as e:
                logger.warning("[Join] Cookies load failed: {}", e)

    async def save_cookies(self, context: Any) -> None:
        try:
            cookies = await context.cookies()
            with open(self.cfg.cookies_file, "wb") as f:
                pickle.dump(cookies, f)
            logger.info("[Join] Cookies saved.")
        except Exception as e:
            logger.warning("[Join] Cookies save failed: {}", e)

    async def is_logged_in(self, page: Any) -> bool:
        try:
            url = page.url or ""
            if "/auth/login" in url:
                return False
            # stable-ish candidate menu markers
            if await page.query_selector("div[data-testid='UserMenuCandidate']"):
                return True
            if await page.query_selector("div[data-testid='candidateMenu'], div[data-testid='UserMenu']"):
                return True
            # cheap heuristic: presence of applications UI
            if await page.query_selector("a[href*='/talent/applications'], [data-testid*='ApplicationItem']"):
                return True
            return False
        except Exception:
            return False

    async def login(self, page: Any) -> bool:
        if not self.cfg.email or not self.cfg.password:
            logger.error("[Join] JOIN_EMAIL/JOIN_PASSWORD missing.")
            return False

        logger.info("[Join] Attempting login...")
        await safe_goto(page, self.cfg.login_url)
        await accept_cookies_join(page)
        await ahuman_delay(1.2, 2.0)

        # email
        email_selectors = [
            "input#email",
            "input[name='email']",
            "input[type='email'][autocomplete='email']",
            "input[type='email']",
        ]
        email_el = None
        for sel in email_selectors:
            email_el = await page.query_selector(sel)
            if email_el:
                break
        if not email_el:
            logger.error("[Join] Email input not found.")
            await dump_debug_artifacts(self.cfg, page, "login_no_email")
            return False

        await email_el.fill(self.cfg.email)
        await ahuman_delay(0.4, 0.8)

        # password
        password_selectors = [
            "input#password",
            "input[name='password']",
            "input[type='password'][autocomplete='current-password']",
            "input[type='password']",
        ]
        pwd_el = None
        for sel in password_selectors:
            pwd_el = await page.query_selector(sel)
            if pwd_el:
                break
        if not pwd_el:
            logger.error("[Join] Password input not found.")
            await dump_debug_artifacts(self.cfg, page, "login_no_password")
            return False

        await pwd_el.fill(self.cfg.password)
        await ahuman_delay(0.4, 0.9)

        # submit
        btn = await _click_button_by_text(page, ["login", "log in", "sign in"], click=False)
        if not btn:
            # last resort: submit button
            btn = await page.query_selector("button[type='submit']")
        if not btn:
            logger.error("[Join] Login button not found.")
            await dump_debug_artifacts(self.cfg, page, "login_no_button")
            return False

        await move_cursor_to_element(page, btn)
        await btn.click()
        await ahuman_delay(1.8, 3.0)
        await safe_wait_networkidle(page, timeout_ms=20000)

        # recaptcha hint
        try:
            body = (await page.inner_text("body")).lower()
            if "recaptcha" in body and ("invalid" in body or "token" in body):
                logger.warning("[Join] reCAPTCHA likely blocked login. Manual solve required.")
                await dump_debug_artifacts(self.cfg, page, "login_recaptcha")
                return False
        except Exception:
            pass

        ok = await self.is_logged_in(page)
        logger.info("[Join] Login {} (url={})", "OK" if ok else "FAILED", page.url)
        if not ok:
            await dump_debug_artifacts(self.cfg, page, "login_failed")
        return ok

    async def ensure_logged_in(self, page: Any, context: Any) -> bool:
        # cookies first
        await self.load_cookies(context)

        # go home and see where we land
        await safe_goto(page, self.cfg.home_url)
        await accept_cookies_join(page)
        await ahuman_delay(0.8, 1.5)

        if page.url and page.url.startswith(self.cfg.home_url):
            logger.info("[Join] Logged in (home).")
            return True

        if await self.is_logged_in(page):
            logger.info("[Join] Logged in (heuristic).")
            return True

        # need login
        if "/auth/login" in (page.url or ""):
            logger.info("[Join] Not logged in (redirected to login). Attempting login...")

        ok = await self.login(page)
        if not ok:
            return False

        # re-check home and persist cookies
        await safe_goto(page, self.cfg.home_url)
        await accept_cookies_join(page)
        if page.url and page.url.startswith(self.cfg.home_url):
            await self.save_cookies(context)
            logger.info("[Join] Authorization successful, cookies persisted.")
            return True

        logger.warning("[Join] After login, unexpected URL: {}", page.url)
        await dump_debug_artifacts(self.cfg, page, "post_login_unexpected")
        return False


# -----------------------------------------------------------------------------
# Human typing / input helpers
# -----------------------------------------------------------------------------
async def human_type(input_element: Any, text: str, delay_range: Tuple[float, float] = (0.05, 0.15)) -> None:
    if not input_element:
        return
    await input_element.fill("")
    await asyncio.sleep(0.15)
    for ch in text:
        await input_element.type(ch)
        await asyncio.sleep(random.uniform(*delay_range))


async def get_current_value(input_element: Any) -> str:
    if not input_element:
        return ""
    try:
        return (await input_element.input_value()).strip()
    except Exception:
        try:
            return (await input_element.get_attribute("value") or "").strip()
        except Exception:
            return ""


async def fill_if_different(input_element: Any, new_value: str) -> None:
    if not input_element:
        return
    cur = await get_current_value(input_element)
    nv = (new_value or "").strip()
    if cur != nv:
        logger.info("[Join] Field change: '{}' -> '{}'", cur, nv)
        await human_type(input_element, nv)
    else:
        logger.debug("[Join] Field already set, skipping.")


# -----------------------------------------------------------------------------
# Wizard helper: click button by visible text (prefer locator, fallback scan)
# -----------------------------------------------------------------------------
async def _click_button_by_text(page: Any, texts: list[str], click: bool = True) -> Any:
    """
    Returns element handle (best effort). If click=True, performs click.
    """
    texts_l = [t.lower() for t in texts]

    # Fast path: locator with has_text (if available)
    try:
        for t in texts:
            loc = page.locator("button", has_text=re.compile(re.escape(t), re.I))
            if await loc.count():
                el = loc.first
                if click:
                    await el.scroll_into_view_if_needed()
                    await ahuman_delay(0.2, 0.5)
                    await el.click()
                return el
    except Exception:
        pass

    # Fallback: scan all buttons + click first enabled match
    try:
        candidates = await page.query_selector_all("button")
        for c in candidates:
            try:
                txt = (await c.inner_text()).strip().lower()
            except Exception:
                continue
            if not txt:
                continue
            if not any(t in txt for t in texts_l):
                continue
            disabled_attr = await c.get_attribute("disabled")
            if disabled_attr is not None:
                continue
            if click:
                await c.scroll_into_view_if_needed()
                await ahuman_delay(0.2, 0.5)
                await c.click()
            return c
    except Exception:
        pass

    return None


# -----------------------------------------------------------------------------
# DatePicker support (Chakra date-picker)
# -----------------------------------------------------------------------------
async def pick_start_date_in_datepicker(page: Any, target_date: dt.date) -> bool:
    target_iso = target_date.isoformat()

    try:
        await page.wait_for_selector("div[data-testid='DatePickerInput']", timeout=8000)
    except Exception:
        logger.warning("[Join] Datepicker not found")
        return False

    async def click_cell_for_value(value: str) -> bool:
        sel = (
            "[data-scope='date-picker'][data-part='table-cell']"
            f"[data-value='{value}'] "
            "[data-scope='date-picker'][data-part='table-cell-trigger']"
        )
        cell = await page.query_selector(sel)
        if cell:
            await cell.scroll_into_view_if_needed()
            await ahuman_delay(0.2, 0.5)
            await cell.click()
            await ahuman_delay(0.4, 0.8)
            return True
        return False

    # current month
    if await click_cell_for_value(target_iso):
        logger.info("[Join] Picked date {}", target_iso)
        return True

    # try next month a few times
    for _ in range(3):
        next_btn = await page.query_selector("button[data-scope='date-picker'][data-part='next-trigger']")
        if not next_btn:
            break
        await next_btn.click()
        await ahuman_delay(0.2, 0.6)
        if await click_cell_for_value(target_iso):
            logger.info("[Join] Picked date {} after switching month", target_iso)
            return True

    # fallback: first available date
    fallback = await page.query_selector(
        "[data-scope='date-picker'][data-part='table-cell']"
        ":not([data-outside-range]) "
        "[data-scope='date-picker'][data-part='table-cell-trigger']"
    )
    if fallback:
        await fallback.scroll_into_view_if_needed()
        await ahuman_delay(0.2, 0.5)
        await fallback.click()
        await ahuman_delay(0.4, 0.8)
        logger.warning("[Join] Target date not found, clicked first available (wanted={})", target_iso)
        return True

    logger.warning("[Join] Could not select any date (wanted={})", target_iso)
    return False


# -----------------------------------------------------------------------------
# Cover letter PDF attach (optional dependency)
# -----------------------------------------------------------------------------
def _sanitize_for_filename(raw_text: str, max_len: int = 80) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", raw_text or "")
    return safe[:max_len].strip()


def generate_empty_cover_letter_pdf(company: str, job: str) -> str:
    base_folder = "generated_pdfs"
    os.makedirs(base_folder, exist_ok=True)

    comp = _sanitize_for_filename(company, 30)
    role = _sanitize_for_filename(job, 30)
    file_name = f"cover_letter_{comp}_{role}.pdf".strip("_") or "cover_letter.pdf"

    pdf_path = os.path.join(base_folder, file_name)
    if len(os.path.abspath(pdf_path)) > MAX_PATH_LENGTH:
        pdf_path = os.path.join(base_folder, "cover_letter.pdf")

    if os.path.exists(pdf_path):
        return pdf_path

    try:
        from fpdf import FPDF  # type: ignore

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=14)
        pdf.cell(200, 10, txt=f"Cover Letter for {company} - {job}", ln=1, align="L")
        pdf.cell(200, 10, txt="(Empty content, auto-generated)", ln=2, align="L")
        pdf.output(pdf_path)
        logger.info("[Join] Generated cover letter PDF: {}", pdf_path)
    except Exception as e:
        logger.warning("[Join] Failed to generate PDF via fpdf: {}", e)
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4\n% Empty PDF stub\n")
        logger.info("[Join] Created PDF stub: {}", pdf_path)

    return pdf_path


async def attach_cover_letter_pdf_if_required(page: Any) -> bool:
    """
    If join shows: "Following attachments are required: [COVER_LETTER]"
    attach generated pdf.
    """
    try:
        error_el = await page.query_selector("small[data-testid='FormError']")
        if not error_el:
            return False
        msg = (await error_el.inner_text()).strip().lower()
        if "following attachments are required" not in msg or "cover_letter" not in msg:
            return False

        logger.info("[Join] Cover letter required, attaching...")

        company_el = await page.query_selector("div[data-testid='JobApplicationHeader'] div.sc-hLseeU.codrxc")
        job_el = await page.query_selector("div[data-testid='JobApplicationHeader'] div.sc-hLseeU.Lgmbz")
        company = (await company_el.inner_text()).strip() if company_el else "UnknownCompany"
        job_title = (await job_el.inner_text()).strip() if job_el else "UnknownJob"

        pdf_path = generate_empty_cover_letter_pdf(company, job_title)

        loc = page.locator("input[type='file'][data-testid='FileUpload_COVER_LETTER']")
        if not await loc.count():
            loc = page.locator("input[type='file'][accept*='application/pdf']")
        if not await loc.count():
            logger.warning("[Join] File input for attachments not found.")
            return False

        await loc.first.set_input_files(pdf_path)
        await ahuman_delay(0.8, 1.4)
        logger.info("[Join] Cover letter attached.")
        return True
    except Exception as e:
        logger.warning("[Join] Failed to attach cover letter: {}", e)
        return False


# -----------------------------------------------------------------------------
# Contact details fill
# -----------------------------------------------------------------------------
async def fill_contact_details(page: Any, resume_data: dict) -> None:
    pi = resume_data.get("personal_information", {}) or {}
    country_name = (pi.get("country") or "").strip()
    phone_prefix = (pi.get("phone_prefix") or "").strip()
    phone_number = (pi.get("phone") or "").strip()

    # Country
    try:
        country_value_item = await page.query_selector("div.select-container .value-item")
        if country_value_item and country_name:
            current = (await country_value_item.inner_text()).strip()
            if current and current.lower() != country_name.lower():
                logger.info("[Join] Country: '{}' -> '{}'", current, country_name)
                ctrl = await page.query_selector("div[data-testid='SelectControlContainer']")
                if ctrl:
                    await ctrl.click()
                    await ahuman_delay(0.4, 0.8)
                    opt = await page.query_selector(f"div[role='listbox'] div >> text='{country_name}'")
                    if opt:
                        await opt.click()
                        await ahuman_delay(0.4, 0.8)
    except Exception:
        pass

    # Prefix
    try:
        prefix_btn = await page.query_selector("button[id^='listbox-button-']")
        if prefix_btn and phone_prefix:
            await prefix_btn.click()
            await ahuman_delay(0.4, 0.8)
            opt = await page.query_selector(f"div[role='listbox'] div >> text='{phone_prefix}'")
            if opt:
                await opt.click()
                await ahuman_delay(0.4, 0.8)
    except Exception:
        pass

    # Phone number
    try:
        phone_input = await page.query_selector("input[name='candidate.phoneNumber']")
        if phone_input and phone_number:
            await phone_input.scroll_into_view_if_needed()
            await ahuman_delay(0.3, 0.7)
            current = await get_current_value(phone_input)
            if current != phone_number:
                logger.info("[Join] Phone: '{}' -> '{}'", current, phone_number)
                await phone_input.fill("")
                await ahuman_delay(0.2, 0.4)
                await phone_input.type(phone_number)
                await ahuman_delay(0.3, 0.7)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Answer resolver (free text + choices)
# -----------------------------------------------------------------------------
def _generic_fallback_answer() -> str:
    return "All relevant details are in my CV. Happy to clarify in an interview."


def _interactive_choose(prompt: str, options: list[str]) -> str:
    print(prompt)
    for i, opt in enumerate(options, start=1):
        print(f"{i}) {opt}")
    while True:
        s = input("Choose: ").strip()
        if s.isdigit():
            i = int(s)
            if 1 <= i <= len(options):
                return options[i - 1]
        print("Invalid choice.")


def resolve_text_answer(
    cfg: JoinConfig,
    store: JoinStore,
    translator: Translator,
    resume_data: dict,
    raw_question: str,
) -> Optional[str]:
    q_key = normalize_question_text(raw_question)

    if q_key in store.answers:
        return store.answers[q_key]

    default = get_default_answer_from_resume(raw_question, cfg, resume_data)
    if default:
        store.answers[q_key] = str(default)
        store.save()
        return str(default)

    # interactive mode
    if cfg.interactive:
        tr = translator.translate(q_key, target_lang="ru")
        ans = input(f"\n[Join] New question:\n{raw_question}\n[RU]: {tr}\nAnswer: ").strip()
        if ans:
            store.answers[q_key] = ans
            store.save()
            return ans
        return None

    # non-interactive
    if cfg.auto_fill_unknown:
        ans = _generic_fallback_answer()
        store.answers[q_key] = ans
        store.save()
        return ans

    return None


def resolve_choice_answer(
    cfg: JoinConfig,
    store: JoinStore,
    translator: Translator,
    resume_data: dict,
    raw_question: str,
    options: list[str],
) -> Optional[str]:
    q_key = normalize_question_text(raw_question)

    if q_key in store.answers:
        return store.answers[q_key]

    # (optional) tiny heuristics for yes/no
    opts_norm = [o.strip().lower() for o in options]
    if set(opts_norm) >= {"yes", "no"}:
        # If question explicitly asks for work permit/visa sponsorship, default to "No" unless interactive,
        # because auto-yes can be harmful. Otherwise default to "Yes" (keeps flow going).
        if ("sponsorship" in q_key) or ("visa" in q_key) or ("work permit" in q_key):
            guess = "No"
        else:
            guess = "Yes"
        if cfg.auto_fill_unknown and not cfg.interactive:
            store.answers[q_key] = guess
            store.save()
            return guess

    if cfg.interactive:
        tr = translator.translate(q_key, target_lang="ru")
        chosen = _interactive_choose(f"\n[Join] {raw_question}\n[RU]: {tr}", options)
        store.answers[q_key] = chosen
        store.save()
        return chosen

    if cfg.auto_fill_unknown and options:
        store.answers[q_key] = options[0]
        store.save()
        return options[0]

    return None


# -----------------------------------------------------------------------------
# Screening question handler (wizard)
# -----------------------------------------------------------------------------
async def answer_screening_question_page(
    cfg: JoinConfig,
    page: Any,
    store: JoinStore,
    translator: Translator,
    resume_data: dict,
) -> bool:
    """
    Returns:
      True  -> handled (answered or info-only)
      False -> no question detected or could not handle
    """
    question_el = await page.query_selector("div.chakra-ui-1ddb145 h2.chakra-heading")
    if not question_el:
        return False

    raw_q = (await question_el.inner_text()).strip()
    if not raw_q:
        return False

    logger.info("[Join] Screening question: {}", raw_q)

    q_lower = raw_q.lower()
    info_only_phrases = [
        "confirm your cv",
        "confirm your resume",
        "confirm your curriculum vitae",
        "upload your cover letter",
        "upload cover letter",
        "upload your motivation letter",
    ]
    if any(p in q_lower for p in info_only_phrases):
        logger.info("[Join] Info-only page, no input expected.")
        return True

    # datepicker step inside wizard
    if await page.query_selector("div[data-testid='DatePickerInput']"):
        # compute target date from resume mapping (ISO) or fallback days
        default = get_default_answer_from_resume(raw_q, cfg, resume_data)
        target = None
        if default:
            try:
                target = dt.date.fromisoformat(str(default)[:10])
            except Exception:
                target = None
        if not target:
            target = dt.date.today() + dt.timedelta(days=cfg.default_days_to_start)

        ok = await pick_start_date_in_datepicker(page, target)
        return ok

    # textarea
    textarea = await page.query_selector("div[data-scope='field'][data-part='root'] textarea")
    if textarea:
        ans = resolve_text_answer(cfg, store, translator, resume_data, raw_q)
        if not ans:
            logger.warning("[Join] No answer available for textarea question.")
            return False
        await fill_if_different(textarea, ans)
        await ahuman_delay(0.6, 1.2)
        return True

    # inputs
    number_input = await page.query_selector("div[data-scope='field'][data-part='root'] input[type='number']")
    text_input = await page.query_selector("div[data-scope='field'][data-part='root'] input[type='text']")
    input_el = number_input or text_input
    if input_el:
        ans = resolve_text_answer(cfg, store, translator, resume_data, raw_q)
        if not ans:
            logger.warning("[Join] No answer available for input question.")
            return False
        await fill_if_different(input_el, ans)
        await ahuman_delay(0.6, 1.2)
        return True

    # radios / choices
    # (Chakra) try common radio labels
    try:
        radio_labels = await page.query_selector_all("span.chakra-radio__label")
    except Exception:
        radio_labels = []
    if radio_labels:
        opts = []
        for lbl in radio_labels:
            try:
                t = (await lbl.inner_text()).strip()
                if t:
                    opts.append(t)
            except Exception:
                continue
        if opts:
            chosen = resolve_choice_answer(cfg, store, translator, resume_data, raw_q, opts)
            if not chosen:
                logger.warning("[Join] No answer available for radio question.")
                return False
            # click matching label
            for lbl in radio_labels:
                try:
                    t = (await lbl.inner_text()).strip()
                    if t.lower() == chosen.lower():
                        await lbl.click()
                        await ahuman_delay(0.5, 1.0)
                        return True
                except Exception:
                    continue

    logger.info("[Join] Question detected but no known input type matched.")
    return False


# -----------------------------------------------------------------------------
# Legacy blocks handler (older UI QuestionItem)
# -----------------------------------------------------------------------------
async def handle_legacy_questions(
    cfg: JoinConfig,
    page: Any,
    store: JoinStore,
    translator: Translator,
    resume_data: dict,
) -> None:
    blocks = await page.query_selector_all("div[data-testid='QuestionItem']")
    if not blocks:
        return

    logger.info("[Join] Legacy questions detected: {} blocks", len(blocks))
    fallback_date = dt.date.today() + dt.timedelta(days=max(3, cfg.default_days_to_start))
    fallback_date_str = fallback_date.strftime("%d.%m.%Y")

    for qb in blocks:
        try:
            q_el = await qb.query_selector("span.sc-gLDzan, span.sc-blLsxD")
            if not q_el:
                continue
            raw_q = (await q_el.inner_text()).strip()
            if not raw_q:
                continue

            # DateField
            date_field = await qb.query_selector("div[data-testid='DateField']")
            if date_field:
                # prefer datepicker, else fill formatted
                if not await page.query_selector("div[data-testid='DatePickerInput']"):
                    date_input = await date_field.query_selector("input")
                    if date_input:
                        await fill_if_different(date_input, fallback_date_str)
                else:
                    # try resume-derived date
                    default = get_default_answer_from_resume(raw_q, cfg, resume_data)
                    target = None
                    if default:
                        try:
                            target = dt.date.fromisoformat(str(default)[:10])
                        except Exception:
                            target = None
                    if not target:
                        target = fallback_date
                    await pick_start_date_in_datepicker(page, target)
                await ahuman_delay(0.4, 0.9)
                continue

            # TextArea
            text_area = await qb.query_selector("textarea[data-testid='TextAreaField']")
            if text_area:
                ans = resolve_text_answer(cfg, store, translator, resume_data, raw_q)
                if ans:
                    await fill_if_different(text_area, ans)
                await ahuman_delay(0.6, 1.2)
                continue

            # Input
            input_field = await qb.query_selector("div[data-testid='InputField']")
            if input_field:
                t_in = await input_field.query_selector("input[data-testid='TextInput']")
                if t_in:
                    ans = resolve_text_answer(cfg, store, translator, resume_data, raw_q)
                    if ans:
                        await fill_if_different(t_in, ans)
                    await ahuman_delay(0.6, 1.2)
                continue

            # Yes/No
            yes_btn = await qb.query_selector("div[data-testid='YesAnswer']")
            no_btn = await qb.query_selector("div[data-testid='NoAnswer']")
            if yes_btn and no_btn:
                chosen = resolve_choice_answer(cfg, store, translator, resume_data, raw_q, ["Yes", "No"])
                if chosen and chosen.lower() == "yes":
                    await yes_btn.click()
                elif chosen:
                    await no_btn.click()
                await ahuman_delay(0.6, 1.2)
                continue

            # Radio labels
            labels = await qb.query_selector_all("span.chakra-radio__label")
            if labels:
                opts = [(await lbl.inner_text()).strip() for lbl in labels]
                opts = [o for o in opts if o]
                chosen = resolve_choice_answer(cfg, store, translator, resume_data, raw_q, opts)
                if chosen:
                    for lbl in labels:
                        t = (await lbl.inner_text()).strip()
                        if t.lower() == chosen.lower():
                            await lbl.click()
                            await ahuman_delay(0.6, 1.2)
                            break

        except Exception as e:
            logger.debug("[Join] Legacy question handling error: {}", e)


# -----------------------------------------------------------------------------
# Fill one incomplete application
# -----------------------------------------------------------------------------
async def fill_incomplete_application(
    page: Any,
    app_url: str,
    store: JoinStore,
    translator: Translator,
    resume_data: dict,
    cfg: JoinConfig,
) -> bool:
    """
    Completes join.com application and attempts to submit.
    """
    try:
        await safe_goto(page, app_url)
        await accept_cookies_join(page)
        await ahuman_delay(1.2, 2.0)

        # If present: "Complete application" CTA (some pages show a gate)
        try:
            btn = await _click_button_by_text(page, ["complete application"], click=False)
            if btn:
                await move_cursor_to_element(page, btn)
                await btn.scroll_into_view_if_needed()
                await ahuman_delay(0.3, 0.8)
                await btn.click()
                await ahuman_delay(1.0, 2.0)
                await safe_wait_networkidle(page)
                logger.info("[Join] Clicked 'Complete application'")
        except Exception:
            pass

        # Wizard loop: step -> handle -> continue
        for step in range(cfg.wizard_max_steps):
            await ahuman_delay(0.6, 1.2)
            await safe_wait_networkidle(page)

            # cover letter requirement can appear before submit
            await attach_cover_letter_pdf_if_required(page)

            # Success message (in case already submitted)
            try:
                ok = await page.query_selector(
                    "text=/Your application was successful\\.|Deine Bewerbung war erfolgreich/i"
                )
                if ok:
                    logger.info("[Join] Success message already present.")
                    return True
            except Exception:
                pass

            # Review page?
            review = None
            try:
                review = await page.query_selector("h2.chakra-heading:has-text('Review your application')")
            except Exception:
                review = None
            if review:
                logger.info("[Join] Reached review page, attempting final submit.")
                break

            # Detect question/date step and answer
            handled = await answer_screening_question_page(cfg, page, store, translator, resume_data)
            if handled:
                cont = await _click_button_by_text(page, ["continue"], click=False)
                if cont:
                    await move_cursor_to_element(page, cont)
                    await cont.scroll_into_view_if_needed()
                    await ahuman_delay(0.3, 0.8)
                    await cont.click()
                    logger.info("[Join] Continue (after handled step)")
                    continue

            # Neutral step: click Continue if available
            cont = await _click_button_by_text(page, ["continue"], click=False)
            if cont:
                await move_cursor_to_element(page, cont)
                await cont.scroll_into_view_if_needed()
                await ahuman_delay(0.3, 0.8)
                await cont.click()
                logger.info("[Join] Continue (neutral step)")
                continue

            # No continue and not review => exit wizard loop
            logger.info("[Join] Wizard loop: no Continue and no review; stopping step loop.")
            break

        # Legacy questions (older UI), if any
        await handle_legacy_questions(cfg, page, store, translator, resume_data)

        # Professional links (best effort)
        pi = resume_data.get("personal_information", {}) or {}
        links_map = {
            "LINKEDIN": pi.get("linkedin", ""),
            "XING": pi.get("xing", ""),
            "GITHUB": pi.get("github", ""),
            "PORTFOLIO": pi.get("portfolio", ""),
        }
        for link_type, link_val in links_map.items():
            link_val = (link_val or "").strip()
            if not link_val:
                continue
            sel = f"div[data-testid='ProfessionalLink_{link_type}'] input[name='professionalLinks.{link_type}']"
            try:
                inp = await page.query_selector(sel)
                if inp:
                    await fill_if_different(inp, link_val)
                    await ahuman_delay(0.3, 0.7)
            except Exception:
                continue

        # Contact details
        await fill_contact_details(page, resume_data)

        # Attach cover letter if required right before submit
        await attach_cover_letter_pdf_if_required(page)

        # Final submit
        submit_texts = [
            "submit application",
            "submit information",
            "send application",
            "apply now",
            "apply",
            "informationen einreichen",
            "absenden",
        ]

        submit_btn = None
        # try buttons type=submit first
        try:
            submit_btn = await _click_button_by_text(page, submit_texts, click=False)
        except Exception:
            submit_btn = None

        # if not found, fallback scanning submit buttons
        if not submit_btn:
            try:
                candidates = await page.query_selector_all("button[type='submit'], button[type='button']")
                for c in candidates:
                    try:
                        t = (await c.inner_text()).strip().lower()
                    except Exception:
                        continue
                    if any(x in t for x in submit_texts):
                        submit_btn = c
                        break
            except Exception:
                submit_btn = None

        if not submit_btn:
            msg = await read_flash_messages(page)
            append_flash_log(cfg, app_url, f"Submit button not found. Flash={msg}")
            logger.warning("[Join] Final submit button not found.")
            await dump_debug_artifacts(cfg, page, "no_submit_button")
            return False

        await move_cursor_to_element(page, submit_btn)
        await submit_btn.scroll_into_view_if_needed()
        await ahuman_delay(0.8, 1.5)
        await submit_btn.click()
        logger.info("[Join] Clicked final submit.")
        await ahuman_delay(1.5, 2.8)
        await safe_wait_networkidle(page)

        # Sometimes submit fails due to missing attachment -> retry attach + submit once
        if await attach_cover_letter_pdf_if_required(page):
            submit_btn2 = await _click_button_by_text(page, submit_texts, click=False)
            if submit_btn2:
                await move_cursor_to_element(page, submit_btn2)
                await submit_btn2.scroll_into_view_if_needed()
                await ahuman_delay(0.6, 1.2)
                await submit_btn2.click()
                logger.info("[Join] Re-clicked submit after attaching cover letter.")
                await ahuman_delay(1.5, 2.8)
                await safe_wait_networkidle(page)

        # Update profile modal
        try:
            await page.wait_for_selector("div[data-testid='ModalDialog']", timeout=5000)
            update_btn = await page.query_selector("[data-testid='updateProfile']")
            if update_btn:
                await move_cursor_to_element(page, update_btn)
                await update_btn.click()
                await ahuman_delay(0.8, 1.4)
                logger.info("[Join] Clicked 'Yes, update profile'")
        except Exception:
            pass

        # Success detection
        try:
            await page.wait_for_selector(
                "text=/Your application was successful\\.|Deine Bewerbung war erfolgreich/i",
                timeout=10000,
            )
            logger.info("[Join] Application successful.")
            return True
        except Exception:
            msg = await read_flash_messages(page)
            append_flash_log(cfg, app_url, f"No success message. Flash={msg}")
            logger.warning("[Join] No known success message detected.")
            await dump_debug_artifacts(cfg, page, "no_success_message")
            return False

    except Exception as e:
        msg = ""
        try:
            msg = await read_flash_messages(page)
        except Exception:
            pass
        append_flash_log(cfg, app_url, f"Exception: {e}. Flash={msg}")
        logger.error("[Join] Error filling {}: {}", app_url, e)
        await dump_debug_artifacts(cfg, page, "exception_fill")
        return False


# -----------------------------------------------------------------------------
# Parse incomplete applications
# -----------------------------------------------------------------------------
async def parse_incomplete_applications(page: Any, cfg: JoinConfig) -> list[str]:
    await safe_goto(page, cfg.apps_url)
    await accept_cookies_join(page)
    await ahuman_delay(1.0, 2.0)

    last_height = 0
    for i in range(max(1, cfg.apps_scrolls)):
        try:
            h = await page.evaluate("() => document.body.scrollHeight")
        except Exception:
            h = 0
        if i > 1 and h == last_height:
            logger.info("[Join] Applications: no new content on scroll, stopping.")
            break
        last_height = h
        await page.mouse.wheel(0, 2200)
        await ahuman_delay(0.8, 1.6)

    await safe_wait_networkidle(page)

    cards = await page.query_selector_all("div[data-testid='ApplicationItem']")
    logger.info("[Join] Applications cards found: {}", len(cards))

    links: list[str] = []
    for card in cards:
        try:
            badge = await card.query_selector("span.chakra-tag__label")
            if not badge:
                continue
            txt = (await badge.inner_text()).strip().lower()
            if "incomplete" not in txt:
                continue
            href = await card.evaluate(
                """el => {
                    const a = el.closest('a');
                    return a ? a.href : null;
                }"""
            )
            if href:
                links.append(href)
        except Exception:
            continue

    # uniq preserve order
    uniq = list(dict.fromkeys(links))
    logger.info("[Join] Incomplete applications: {}", len(uniq))
    return uniq


# -----------------------------------------------------------------------------
# Public entry point: apply all incomplete applications
# -----------------------------------------------------------------------------
async def apply_incomplete_applications(page: Any, context: Any) -> None:
    cfg = JoinConfig()
    store = JoinStore(cfg.db_file)
    store.ensure()
    store.load()

    translator = Translator(store.translations)
    resume_data = _load_resume_data()

    auth = JoinAuth(cfg)
    ok = await auth.ensure_logged_in(page, context)
    if not ok:
        logger.error("[Join] Cannot proceed: login failed.")
        return

    links = await parse_incomplete_applications(page, cfg)
    logger.info("[Join] Will process {} incomplete apps.", len(links))

    for link in links:
        logger.info("[Join] Processing: {}", link)
        success = await fill_incomplete_application(page, link, store, translator, resume_data, cfg)
        if success:
            logger.info("[Join] Submitted: {}", link)
        else:
            logger.warning("[Join] Not submitted: {}", link)


# -----------------------------------------------------------------------------
# Standalone run (manual)
# -----------------------------------------------------------------------------
async def main():
    from core.config import init_browser

    pw, context, page = await init_browser(headless=False)
    try:
        await apply_incomplete_applications(page, context)
    finally:
        await context.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
