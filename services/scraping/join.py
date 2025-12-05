# -*- coding: utf-8 -*-
"""
scraping/join.py

Объединённая и отрефакторенная версия кода для заполнения заявок на join.com:
 - Работа с куками (загрузка/сохранение).
 - Логика авторизации.
 - Поиск «незавершённых» (Incomplete) заявок и их заполнение.
 - Сохранение/загрузка ответов в JSON-файл (QUESTIONS_DB_FILE).
 - Локальный кэш переводов deep-translator (join_translations).
 - Подготовка PDF (cover_letter), если требуется.
 - Поддержка нового Chakra UI wizard flow (Continue / DatePicker / Screening questions).

Версия с использованием асинхронного Playwright.
"""

import asyncio
import datetime
import json
import os
import pickle
import random
import re
from typing import Optional

import yaml
# pip install deep-translator
from deep_translator import GoogleTranslator
# pip install fpdf
from fpdf import FPDF

from core.constants import QUESTIONS_DB_FILE, JOIN_COOKIES_FILE, JOIN_EMAIL, JOIN_PASSWORD
from core.logger import logger
from services.scraping.utils import ahuman_delay, move_cursor_to_element

# Константы
JOIN_CANDIDATE_URL = "https://join.com/candidate"
JOIN_LOGIN_URL = "https://join.com/auth/login/candidate?redirectUrl=%2Fcandidate"
TALENT_HOME_URL = "https://join.com/talent/home"
TALENT_APPLICATIONS_URL = "https://join.com/talent/applications"
MAX_PATH_LENGTH = 200  # лимит для пути к PDF (Windows и пр.)


def get_resume_data() -> dict:
    """
    Returns resume YAML as dict, regardless of whether RESUME_YAML_FILE is
    a path (str) or already a dict.
    """
    from core.constants import RESUME_YAML_FILE  # чтобы брать актуальное значение

    # Если это уже словарь — просто возвращаем
    if isinstance(RESUME_YAML_FILE, dict):
        return RESUME_YAML_FILE

    # Если это строка — считаем, что это путь к YAML
    if isinstance(RESUME_YAML_FILE, str):
        try:
            with open(RESUME_YAML_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                logger.warning("[Join] Resume YAML is not a dict, got %s", type(data))
                return {}
            return data
        except Exception as e:
            logger.warning(f"[Join] Failed to load resume YAML from {RESUME_YAML_FILE}: {e}")
            return {}

    logger.warning("[Join] RESUME_YAML_FILE has unexpected type: %s", type(RESUME_YAML_FILE))
    return {}

# ---------------------------------------------------------------------------
#  Основные функции для работы с JSON-БД (ответы и переводы)
# ---------------------------------------------------------------------------
def ensure_db_file():
    """
    Создаёт JSON-файл базы (QUESTIONS_DB_FILE), если он не существует.
    По умолчанию структура: {"join_answers": {}, "join_translations": {}}.
    """
    if not QUESTIONS_DB_FILE:
        return
    if not os.path.exists(QUESTIONS_DB_FILE):
        try:
            with open(QUESTIONS_DB_FILE, "w", encoding="utf-8") as f:
                json.dump({"join_answers": {}, "join_translations": {}}, f, ensure_ascii=False, indent=2)
            logger.info(f"[Join] Created empty JSON DB file: {QUESTIONS_DB_FILE}")
        except Exception as e:
            logger.warning(f"[Join] Failed to create QUESTIONS_DB_FILE={QUESTIONS_DB_FILE}: {e}")


def load_join_data() -> dict:
    """
    Загружает JSON-данные (join_answers, join_translations) из QUESTIONS_DB_FILE.
    Возвращает словарь с ключами "join_answers" и "join_translations".
    """
    if not QUESTIONS_DB_FILE or not os.path.exists(QUESTIONS_DB_FILE):
        return {"join_answers": {}, "join_translations": {}}

    try:
        with open(QUESTIONS_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "join_answers" not in data:
            data["join_answers"] = {}
        if "join_translations" not in data:
            data["join_translations"] = {}
        return data
    except Exception as e:
        logger.warning(f"[Join] Error loading {QUESTIONS_DB_FILE}: {e}")
        return {"join_answers": {}, "join_translations": {}}


def save_join_data(join_data: dict):
    """
    Сохраняет структуру { "join_answers": ..., "join_translations": ... }
    обратно в QUESTIONS_DB_FILE.
    """
    if not QUESTIONS_DB_FILE:
        return
    try:
        with open(QUESTIONS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(join_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[Join] Data (answers, translations) saved to {QUESTIONS_DB_FILE}")
    except Exception as e:
        logger.warning(f"[Join] Error saving {QUESTIONS_DB_FILE}: {e}")


def get_join_answers_and_translations() -> tuple[dict, dict]:
    """
    Возвращает кортеж (join_answers, join_translations) – два словаря.
    """
    all_data = load_join_data()
    return all_data["join_answers"], all_data["join_translations"]


def load_questions_db() -> dict:
    """
    Дополнительный маленький wrapper: старый/новый код иногда ожидает
    простой структуры {normalized_question: answer}.
    """
    data = load_join_data()
    return data.get("join_answers", {})


def save_questions_db(data: dict) -> None:
    """
    Сохранить простой questions->answer словарь, сохраняя при этом translations.
    """
    all_data = load_join_data()
    all_data["join_answers"] = data
    save_join_data(all_data)


# ---------------------------------------------------------------------------
#  Работа с cookies и авторизацией
# ---------------------------------------------------------------------------
async def load_join_cookies(context) -> None:
    """
    Загружает cookies из локального файла (JOIN_COOKIES_FILE)
    и добавляет их в playwright-контекст (context).
    """
    if os.path.exists(JOIN_COOKIES_FILE):
        try:
            with open(JOIN_COOKIES_FILE, "rb") as f:
                cookies = pickle.load(f)
            await context.add_cookies(cookies)
            logger.info("[Join] Cookies loaded successfully.")
        except Exception as e:
            logger.warning(f"[Join] Error loading cookies: {e}")


async def save_join_cookies(context) -> None:
    """
    Сохраняет cookies из playwright-контекста в файл JOIN_COOKIES_FILE.
    """
    try:
        cookies = await context.cookies()
        with open(JOIN_COOKIES_FILE, "wb") as f:
            pickle.dump(cookies, f)
        logger.info("[Join] Cookies saved successfully.")
    except Exception as e:
        logger.warning(f"[Join] Error saving cookies: {e}")


async def accept_cookies_join(page):
    """
    Пытается нажать на cookie-баннер (Accept All / Save & Close),
    если он виден на странице.
    """
    try:
        banner = await page.query_selector("#cookiescript_injected")
        if not banner:
            logger.debug("[Join] Cookie banner root not found.")
            return

        accept_btn = await page.query_selector("#cookiescript_accept")
        if accept_btn:
            await accept_btn.click()
            logger.info("[Join] Pressed button 'Accept All'.")
            await ahuman_delay(1, 2)
            return

        saveclose_btn = await page.query_selector("#cookiescript_save")
        if saveclose_btn:
            await saveclose_btn.click()
            logger.info("[Join] Pressed button 'Save & Close'.")
            await ahuman_delay(1, 2)
            return

        logger.info("[Join] Cookie banner not found or already hidden.")
    except Exception as e:
        logger.debug(f"[Join] Cookie banner not found or error while clicking: {e}")


async def is_join_logged_in(page) -> bool:
    """
    Проверяет, залогинен ли пользователь.
    Немного tolerant:
     - если мы на /auth/login, считаем, что нет логина.
     - пытается найти разные варианты меню кандидата.
    """
    try:
        url = page.url or ""
        if "/auth/login" in url:
            return False

        # Основной старый селектор
        user_menu = await page.query_selector("div[data-testid='UserMenuCandidate']")
        if user_menu:
            return True

        # Возможные альтернативы
        alt_menu = await page.query_selector(
            "div[data-testid='candidateMenu'], div[data-testid='UserMenu']"
        )
        if alt_menu:
            return True

        # Очень грубая эвристика: на дашборде часто есть слово "Applications"
        body_text = (await page.inner_text("body")).lower()
        if "your applications" in body_text or "saved jobs" in body_text:
            return True

        return False
    except Exception as e:
        logger.warning(f"[Join] Error checking login status: {e}")
        return False


async def login_join(page):
    """
    Заходит на URL логина JOIN_LOGIN_URL и вводит JOIN_EMAIL/JOIN_PASSWORD.
    Подогнано под HTML, который ты прислал.
    """
    logger.info("[Join] Starting login...")

    try:
        await page.goto(JOIN_LOGIN_URL)
        await page.wait_for_load_state("networkidle")
        await accept_cookies_join(page)
        await ahuman_delay(2, 4)

        # Email
        email_selectors = [
            "input#email",
            "input[name='email']",
            "input[type='email'][autocomplete='email']",
        ]
        email_ok = False
        for sel in email_selectors:
            el = await page.query_selector(sel)
            if el:
                logger.debug(f"[Join] Filling email via selector: {sel}")
                await el.fill(JOIN_EMAIL)
                email_ok = True
                break
        if not email_ok:
            logger.error("[Join] Could not find email input field.")
            return

        await ahuman_delay(1, 2)

        # Password
        password_selectors = [
            "input#password",
            "input[name='password']",
            "input[data-testid='TextInput'][type='password']",
            "input[type='password'][autocomplete='current-password']",
        ]
        pwd_ok = False
        for sel in password_selectors:
            el = await page.query_selector(sel)
            if el:
                logger.debug(f"[Join] Filling password via selector: {sel}")
                await el.fill(JOIN_PASSWORD)
                pwd_ok = True
                break
        if not pwd_ok:
            logger.error("[Join] Could not find password input field.")
            return

        await ahuman_delay(1, 2)

        # Кнопка Login
        login_button = None
        candidates = await page.query_selector_all("button[type='submit'], button")
        for btn in candidates:
            text = (await btn.inner_text()).strip().lower()
            if "login" in text or "log in" in text or "sign in" in text:
                login_button = btn
                break

        if not login_button:
            logger.error("[Join] Login button not found.")
            return

        await move_cursor_to_element(page, login_button)
        await login_button.click()
        await ahuman_delay(3, 5)
        await page.wait_for_load_state("networkidle")

        content_text = (await page.inner_text("body")).lower()
        if "recaptcha token is invalid" in content_text:
            logger.warning("[Join] reCAPTCHA blocked login. Manual solve needed.")
            return

        if await is_join_logged_in(page):
            logger.info("[Join] Successfully logged in.")
        else:
            logger.error("[Join] Failed to log in (check login/password or selectors).")
            logger.debug(f"[Join] Current URL after login attempt: {page.url}")
    except Exception as e:
        logger.error(f"[Join] Error during login: {e}")


async def check_join_login(page, context):
    """
    Проверяет, залогинен ли пользователь. Если нет, пробует:
     1) Загрузить cookies.
     2) Перейти на TALENT_HOME_URL.
     3) Если нас удерживают на TALENT_HOME_URL — считаем, что залогинены.
     4) Если редирект на /auth/login/... — предлагаем авторизоваться (login_join).
     5) После успешного логина снова идём на TALENT_HOME_URL и сохраняем cookies.
    """
    # 1. Подкидываем куки в контекст
    await load_join_cookies(context)

    # 2. Пробуем зайти сразу на /talent/home
    try:
        await page.goto(TALENT_HOME_URL)
        await page.wait_for_load_state("networkidle")
        await accept_cookies_join(page)
        await ahuman_delay(1, 2)
    except Exception as e:
        logger.warning(f"[Join] Error navigating to {TALENT_HOME_URL}: {e}")

    current_url = page.url or ""

    # 3. Если мы действительно на /talent/home — считаем, что уже залогинены
    if current_url.startswith(TALENT_HOME_URL):
        logger.info("[Join] Already logged in (on /talent/home).")
        return

    # 4. Если нас перекинуло на страницу логина — явно не залогинены
    if "/auth/login" in current_url:
        logger.info("[Join] Redirected to login from /talent/home (not logged in).")
    else:
        # Неожиданная страница — попробуем старый fallback
        if await is_join_logged_in(page):
            logger.info("[Join] Already logged in (is_join_logged_in fallback).")
            return

    # 5. Спросить у пользователя, логиниться ли
    answer = input("[Join] Not logged in. Attempt login? (y/n): ").strip().lower()
    if answer not in ("y", "yes"):
        logger.info("[Join] User refused to log in.")
        return

    # 6. Пытаемся залогиниться
    await login_join(page)

    # 7. После login_join ещё раз идём на /talent/home и смотрим, удерживает ли нас там
    try:
        await page.goto(TALENT_HOME_URL)
        await page.wait_for_load_state("networkidle")
        await accept_cookies_join(page)
        await ahuman_delay(1, 2)
    except Exception as e:
        logger.warning(f"[Join] Error navigating to {TALENT_HOME_URL} after login: {e}")

    current_url = page.url or ""
    if current_url.startswith(TALENT_HOME_URL):
        logger.info("[Join] Authorization successful (on /talent/home).")
        await save_join_cookies(context)
    else:
        logger.error(f"[Join] Failed to log in. Current URL: {current_url}")


# ---------------------------------------------------------------------------
# Вспомогательные функции для «человеческого» ввода и заполнения
# ---------------------------------------------------------------------------
async def human_type(input_element, text: str, delay_range=(0.05, 0.15)):
    """
    Эмулирует ввод строки text в элемент input_element,
    с задержками между символами.
    """
    if not input_element:
        return
    await input_element.fill("")
    await asyncio.sleep(0.2)
    for ch in text:
        await input_element.type(ch)
        await asyncio.sleep(random.uniform(*delay_range))


async def get_current_value(input_element) -> str:
    """
    Пытается получить текущее значение input или value.
    """
    if not input_element:
        return ""
    val = ""
    try:
        val = await input_element.input_value()
    except Exception:
        try:
            val = await input_element.get_attribute("value") or ""
        except Exception:
            pass
    return val.strip()


async def fill_if_different(input_element, new_value: str):
    """
    Если текущее значение поля отличается от new_value,
    «человечески» заполняем его.
    """
    if not input_element:
        return
    current_value = await get_current_value(input_element)
    if current_value != new_value.strip():
        logger.info(f"[Join] Changing value '{current_value}' -> '{new_value}'")
        await human_type(input_element, new_value.strip())
    else:
        logger.debug(f"[Join] Field already has '{current_value}', skipping.")


def normalize_question_text(question_text: str) -> str:
    """
    Убирает ведущий номер «2. », «3) » и т.п. из начала вопроса,
    приводит к нормализованной форме (нижний регистр, единая пробельность),
    используемой как ключ в базе.
    """
    text_no_num = re.sub(r'^[0-9]+\.\s*', '', question_text)
    text_no_num = re.sub(r'^[0-9]+\)\s*', '', text_no_num)
    # Снижает регистр и нормализует пробелы
    return " ".join(text_no_num.strip().lower().split())


def translate_question(
        question_text: str,
        translations_cache: dict,
        source_lang='auto',
        target_lang='ru'
) -> str:
    """
    Переводит строку question_text -> target_lang (по умолчанию ru) с помощью
    deep_translator.GoogleTranslator, используя локальный кэш translations_cache.
    """
    if question_text in translations_cache:
        return translations_cache[question_text]

    try:
        translated = GoogleTranslator(source=source_lang, target=target_lang).translate(question_text)
        translations_cache[question_text] = translated
        logger.info(f"[Join] Translated: '{question_text}' => '{translated}'")
    except Exception as e:
        logger.warning(f"[Join] Translation error '{question_text}': {e}")
        translated = question_text
    return translated


# ---------------------------------------------------------------------------
#  Новые вспомогательные функции (предложенные улучшения)
# ---------------------------------------------------------------------------
async def click_button_by_text(
        page,
        texts,
        tag: str = "button",
        only_enabled: bool = True
):
    """
    Find first button whose visible text contains any of given strings.
    Returns element handle or None.
    """
    texts_lower = [t.lower() for t in texts]
    candidates = await page.query_selector_all(tag)
    for c in candidates:
        try:
            btn_text = (await c.inner_text()).strip().lower()
        except Exception:
            continue
        if not btn_text:
            continue

        if not any(t in btn_text for t in texts_lower):
            continue

        if only_enabled:
            disabled_attr = await c.get_attribute("disabled")
            if disabled_attr is not None:
                continue

        return c
    return None


async def pick_start_date_in_datepicker(page, days_from_today: int = 7) -> bool:
    """
    Select a date in join.com Chakra datepicker.

    Target date = today + days_from_today.
    We try to find cell with data-value="YYYY-MM-DD".
    If not found in current month, we click "next month" a few times.
    """
    target_date = datetime.date.today() + datetime.timedelta(days=days_from_today)
    target_iso = target_date.isoformat()

    # Wait until datepicker appears
    try:
        await page.wait_for_selector("div[data-testid='DatePickerInput']", timeout=8000)
    except Exception:
        logger.warning("[Join] Datepicker not found on page")
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
            await ahuman_delay(0.5, 1.0)
            return True
        return False

    # Try current month first
    if await click_cell_for_value(target_iso):
        logger.info(f"[Join] Picked start date {target_iso}")
        return True
    else:
        logger.debug(f"[Join] No exact cell for {target_iso}, trying month navigation / fallback")

    # If not found, try to move forward by months
    for _ in range(3):
        next_btn = await page.query_selector(
            "button[data-scope='date-picker'][data-part='next-trigger']"
        )
        if not next_btn:
            break
        await next_btn.click()
        await ahuman_delay(0.3, 0.7)
        if await click_cell_for_value(target_iso):
            logger.info(f"[Join] Picked start date {target_iso} after switching month")
            return True

    # Fallback: pick first available non outside-range cell
    fallback = await page.query_selector(
        "[data-scope='date-picker'][data-part='table-cell']"
        ":not([data-outside-range]) "
        "[data-scope='date-picker'][data-part='table-cell-trigger']"
    )
    if fallback:
        await fallback.scroll_into_view_if_needed()
        await ahuman_delay(0.2, 0.5)
        await fallback.click()
        await ahuman_delay(0.5, 1.0)
        logger.warning(
            f"[Join] Could not find target date {target_iso}, clicked first available date instead"
        )
        return True

    logger.warning(f"[Join] Could not select any date in datepicker for {target_iso}")
    return False


def get_default_answer_from_resume(question: str) -> Optional[str]:
    """
    Very small heuristic mapping from question to resume fields.
    Extend if needed.
    """
    q_norm = normalize_question_text(question)
    resume_data = get_resume_data()
    pi = resume_data.get("personal_information", {})
    availability = resume_data.get("availability", {})
    salary = resume_data.get("salary_expectations", {}) or resume_data.get("expected_salary", {})

    # City
    if "what city do you currently live in" in q_norm or "in what city" in q_norm:
        return pi.get("city") or ""

    # Country
    if "what country do you currently live in" in q_norm or "which country" in q_norm:
        return pi.get("country") or ""

    # When can you start
    if "when are you available to start" in q_norm or "when can you start" in q_norm:
        days_str = availability.get("days")
        try:
            days_int = int(days_str)
        except Exception:
            days_int = 7
        start_date = datetime.date.today() + datetime.timedelta(days=days_int)
        # Для datepicker возвращаем ISO, для текстовых полей — можно вернуть human-readable
        return start_date.isoformat()

    # Expected salary
    if "expected yearly compensation" in q_norm or "expected salary" in q_norm or "salary expectation" in q_norm:
        # Простейшая эвристика: если в резюме указана цифра/диапазон, пытаемся взять середину
        salary_range = None
        if isinstance(salary, str):
            salary_range = salary
        elif isinstance(salary, dict):
            salary_range = salary.get("salary_range") or salary.get("salary_range_usd")
        if salary_range and "-" in salary_range:
            low, high = salary_range.split("-", 1)
            try:
                low_int = int(re.sub(r"[^\d]", "", low))
                high_int = int(re.sub(r"[^\d]", "", high))
                mid = (low_int + high_int) // 2
            except Exception:
                mid = 45000
        else:
            mid = 45000
        return str(mid)

    return None


# ---------------------------------------------------------------------------
#  Универсальная логика «спросить/сохранить ответ» для Input, TextArea, Radio
#  (используются существующие handle_input_question / handle_textarea_question)
# ---------------------------------------------------------------------------
async def handle_input_question(
        page,
        raw_question_text: str,
        input_el,
        join_answers: dict,
        translations_cache: dict
):
    """
    Обработка вопроса, где требуется ввести в <input>.
    """
    question_clean = normalize_question_text(raw_question_text)

    # Use cached answers from persistent DB if present
    questions_db = load_questions_db()
    if question_clean in questions_db:
        await fill_if_different(input_el, questions_db[question_clean])
        logger.info(f"[Join] Using saved answer for input (db): {question_clean}")
        return

    if question_clean in join_answers:
        await fill_if_different(input_el, join_answers[question_clean])
        logger.info(f"[Join] Using saved answer for input (runtime): {question_clean}")
        return

    question_translated = translate_question(question_clean, translations_cache, target_lang="ru")

    resume_data = get_resume_data()
    pi = resume_data.get("personal_information", {})
    default_city = pi.get("city", "")
    default_salary = pi.get("expected_salary", "")
    standard_stupid_answer = (
        "I created a bot to fill out this form, so I can spend more time with my family "
        "instead of repeating the same pointless answers. All relevant details are in my CV."
    )

    possible_answers = []
    if default_city:
        possible_answers.append(f"(из резюме) City: {default_city}")
    if default_salary:
        possible_answers.append(f"(из резюме) Salary: {default_salary}")
    possible_answers.append(f"(стандартный ответ) {standard_stupid_answer}")
    possible_answers.append("(ввести вручную)")

    print(f"\n[Join] New input question:\n\"{raw_question_text}\"")
    if question_translated != question_clean:
        print(f"[Join] (Translation to RU): \"{question_translated}\"")

    for i, ans in enumerate(possible_answers, start=1):
        print(f"{i}) {ans}")

    while True:
        choice_str = input("Enter answer number: ").strip()
        if not choice_str.isdigit():
            print("Need a digit.")
            continue
        choice_idx = int(choice_str)
        if 1 <= choice_idx <= len(possible_answers):
            chosen = possible_answers[choice_idx - 1]
            if chosen.startswith("(из резюме) City:"):
                answer_text = chosen.split(":", 1)[1].strip()
            elif chosen.startswith("(из резюме) Salary:"):
                answer_text = chosen.split(":", 1)[1].strip()
            elif chosen.startswith("(стандартный ответ)"):
                idx = chosen.find(")")
                answer_text = chosen[idx + 1:].strip()
            elif chosen.startswith("(ввести вручную)"):
                answer_text = input("\nEnter your custom answer: ").strip()
            else:
                answer_text = chosen

            join_answers[question_clean] = answer_text
            # Сохраняем и в персистентную БД
            questions_db[question_clean] = answer_text
            save_questions_db(questions_db)

            await fill_if_different(input_el, answer_text)
            logger.info(f"[Join] Input question filled: {question_clean} => {answer_text}")
            return
        else:
            print(f"Invalid choice. Enter 1..{len(possible_answers)}.")


async def handle_textarea_question(
        page,
        raw_question_text: str,
        text_area,
        join_answers: dict,
        translations_cache: dict
):
    """
    Аналог handle_input_question, но для <textarea>.
    """
    question_clean = normalize_question_text(raw_question_text)

    questions_db = load_questions_db()
    if question_clean in questions_db:
        await fill_if_different(text_area, questions_db[question_clean])
        logger.info(f"[Join] Using saved answer (textarea, db): {question_clean}")
        return

    if question_clean in join_answers:
        await fill_if_different(text_area, join_answers[question_clean])
        logger.info(f"[Join] Using saved answer (textarea, runtime): {question_clean}")
        return

    question_translated = translate_question(question_clean, translations_cache, target_lang="ru")
    resume_data = get_resume_data()
    pi = resume_data.get("personal_information", {})
    default_city = pi.get("city", "")
    default_address = pi.get("address", "")
    standard_stupid_answer = (
        "I created a bot to fill out this form, so I can spend more time with my family "
        "instead of repeating the same pointless answers. All relevant details are in my CV."
    )

    possible_answers = []
    if default_city:
        possible_answers.append(f"(из резюме) City: {default_city}")
    if default_address:
        possible_answers.append(f"(из резюме) Address: {default_address}")
    possible_answers.append(f"(стандартный ответ) {standard_stupid_answer}")
    possible_answers.append("(ввести вручную)")

    print(f"\n[Join] New textarea question:\n\"{raw_question_text}\"")
    if question_translated != question_clean:
        print(f"[Join] (Translation to RU): \"{question_translated}\"")

    for i, ans in enumerate(possible_answers, start=1):
        print(f"{i}) {ans}")

    while True:
        choice_str = input("Enter answer number: ").strip()
        if not choice_str.isdigit():
            print("Need a digit.")
            continue
        choice_idx = int(choice_str)
        if 1 <= choice_idx <= len(possible_answers):
            chosen = possible_answers[choice_idx - 1]
            if chosen.startswith("(из резюме) City:"):
                answer_text = chosen.split(":", 1)[1].strip()
            elif chosen.startswith("(из резюме) Address:"):
                answer_text = chosen.split(":", 1)[1].strip()
            elif chosen.startswith("(стандартный ответ)"):
                idx = chosen.find(")")
                answer_text = chosen[idx + 1:].strip()
            elif chosen.startswith("(ввести вручную)"):
                answer_text = input("\nEnter your custom answer: ").strip()
            else:
                answer_text = chosen

            join_answers[question_clean] = answer_text
            questions_db[question_clean] = answer_text
            save_questions_db(questions_db)

            await fill_if_different(text_area, answer_text)
            logger.info(f"[Join] Textarea question filled: {question_clean} => {answer_text}")
            return
        else:
            print(f"Invalid choice. Enter 1..{len(possible_answers)}.")


def ask_user_for_answer(
        page,
        question_text: str,
        possible_answers: list,
        join_answers: dict,
        translations_cache: dict
) -> str:
    """
    Обработка вопросов типа Yes/No, Radio и т.п.
    Возвращает выбранный пользователем вариант (строку).
    """
    question_clean = normalize_question_text(question_text)

    questions_db = load_questions_db()
    if question_clean in questions_db:
        return questions_db[question_clean]

    if question_clean in join_answers:
        return join_answers[question_clean]

    question_translated = translate_question(question_clean, translations_cache, target_lang="ru")

    print(f"\n[Join] New question:\n\"{question_text}\"")
    if question_translated != question_clean:
        print(f"[Join] (Translation): \"{question_translated}\"")

    print("Answers:")
    for i, ans in enumerate(possible_answers, start=1):
        print(f"{i}) {ans}")

    while True:
        choice_str = input("Enter answer number: ").strip()
        if not choice_str.isdigit():
            print("Need a digit.")
            continue
        choice_idx = int(choice_str)
        if 1 <= choice_idx <= len(possible_answers):
            chosen_answer = possible_answers[choice_idx - 1]
            # Сохраняем в обе БД: runtime и persistent
            join_answers[question_clean] = chosen_answer
            questions_db[question_clean] = chosen_answer
            save_questions_db(questions_db)
            return chosen_answer
        else:
            print(f"Invalid choice. Enter 1..{len(possible_answers)}.")


def save_join_answers(join_answers: dict):
    """
    Сохраняет join_answers в JSON-файл (QUESTIONS_DB_FILE).
    """
    if not QUESTIONS_DB_FILE:
        return

    old_data = {}
    if os.path.exists(QUESTIONS_DB_FILE):
        try:
            with open(QUESTIONS_DB_FILE, "r", encoding='utf-8') as f:
                old_data = json.load(f)
        except Exception as e:
            logger.warning(f"[Join] Error reading {QUESTIONS_DB_FILE} to save answers: {e}")

    old_data["join_answers"] = join_answers
    try:
        with open(QUESTIONS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(old_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[Join] Answers successfully saved in {QUESTIONS_DB_FILE}")
    except Exception as e:
        logger.warning(f"[Join] Error saving answers to {QUESTIONS_DB_FILE}: {e}")


# ---------------------------------------------------------------------------
#  Пример: заполняем контактные детали (страна, телефон)
# ---------------------------------------------------------------------------
async def fill_contact_details(page):
    """
    Заполняет или обновляет блок «Contact details».
    """
    resume_data = get_resume_data()
    pi = resume_data.get("personal_information", {})
    country_name_in_resume = pi.get("country", "")
    phone_prefix = pi.get("phone_prefix", "")
    phone_number = pi.get("phone", "")

    # Страна
    country_value_item = await page.query_selector("div.select-container .value-item")
    if country_value_item:
        current_country = (await country_value_item.inner_text()).strip()
        if country_name_in_resume and current_country.lower() != country_name_in_resume.lower():
            logger.info(f"[Join] Changing country '{current_country}' -> '{country_name_in_resume}'")
            country_select_control = await page.query_selector("div[data-testid='SelectControlContainer']")
            if country_select_control:
                await country_select_control.click()
                await ahuman_delay(0.5, 0.8)
                option_sel = f"div[role='listbox'] div >> text='{country_name_in_resume}'"
                option_el = await page.query_selector(option_sel)
                if option_el:
                    await option_el.click()
                    await ahuman_delay(0.5, 0.8)
                else:
                    logger.warning("[Join] Could not find country in dropdown.")

    # Префикс телефона
    prefix_button = await page.query_selector("button[id^='listbox-button-']")
    if prefix_button:
        try:
            current_prefix_div = await prefix_button.query_selector("div.sc-gLDzan.iYfrPW")
            if current_prefix_div:
                current_prefix_str = (await current_prefix_div.inner_text()).strip()
                if phone_prefix and current_prefix_str != phone_prefix:
                    logger.info(f"[Join] Changing phone prefix: {current_prefix_str} -> {phone_prefix}")
                    await prefix_button.click()
                    await ahuman_delay(0.5, 1)
                    prefix_option = await page.query_selector(
                        f"div[role='listbox'] div >> text='{phone_prefix}'"
                    )
                    if prefix_option:
                        await prefix_option.click()
                        await ahuman_delay(0.5, 1)
                    else:
                        logger.warning(f"[Join] Prefix {phone_prefix} not found in dropdown.")
        except Exception:
            logger.debug("[Join] Phone prefix check failed (structure may differ).")

    # Основной номер (без префикса)
    phone_input = await page.query_selector("input[name='candidate.phoneNumber']")
    if phone_input:
        await phone_input.scroll_into_view_if_needed()
        await ahuman_delay(0.5, 1)
        current_phone = await get_current_value(phone_input)
        if phone_number and current_phone != phone_number:
            logger.info(f"[Join] Changing phone '{current_phone}' -> '{phone_number}'")
            await phone_input.fill("")
            await ahuman_delay(0.3, 0.5)
            await phone_input.type(phone_number)
            await ahuman_delay(0.5, 0.8)


# ---------------------------------------------------------------------------
#  Генерация PDF (cover letter) и прикрепление, если требуется
# ---------------------------------------------------------------------------
def _sanitize_for_filename(raw_text: str, max_len=80) -> str:
    """
    Убирает из строки символы, непригодные для имени файла,
    и обрезает длину до max_len.
    """
    safe = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", raw_text)
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe.strip()


def generate_empty_cover_letter_pdf(company: str, job: str) -> str:
    """
    Создаёт PDF (1 страница) с заголовком "Cover Letter: company / job".
    Имя файла формируется, учитывая лимит пути MAX_PATH_LENGTH.
    Если уже существует, повторно не генерируем.
    """
    base_folder = "generated_pdfs"
    os.makedirs(base_folder, exist_ok=True)

    comp_san = _sanitize_for_filename(company, 30)
    job_san = _sanitize_for_filename(job, 30)
    file_name = f"cover_letter_{comp_san}_{job_san}.pdf"

    pdf_path = os.path.join(base_folder, file_name)
    if len(os.path.abspath(pdf_path)) > MAX_PATH_LENGTH:
        pdf_path = os.path.join(base_folder, "cover_letter.pdf")

    if os.path.exists(pdf_path):
        return pdf_path

    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=14)
        pdf.cell(200, 10, txt=f"Cover Letter for {company} - {job}", ln=1, align="L")
        pdf.cell(200, 10, txt="(Empty content, auto-generated)", ln=2, align="L")
        pdf.output(pdf_path)
        logger.info(f"[Join] Generated PDF cover letter: {pdf_path}")
    except Exception as e:
        logger.warning(f"[Join] Failed to generate PDF: {e}")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4\n%Empty PDF stub")
        logger.info(f"[Join] Created empty PDF stub: {pdf_path}")

    return pdf_path


async def attach_cover_letter_pdf_if_required(page):
    """
    Если на странице присутствует сообщение "Following attachments are required: [COVER_LETTER]",
    пытается найти input[type='file'][data-testid='FileUpload_COVER_LETTER'] и присвоить PDF.
    """
    error_el = await page.query_selector("small[data-testid='FormError']")
    if not error_el:
        return
    text_err = (await error_el.inner_text()).strip().lower()
    if "following attachments are required: [cover_letter]" not in text_err:
        return

    logger.info("[Join] Required to attach cover_letter PDF.")

    company_el = await page.query_selector(
        "div[data-testid='JobApplicationHeader'] div.sc-hLseeU.codrxc"
    )
    job_el = await page.query_selector(
        "div[data-testid='JobApplicationHeader'] div.sc-hLseeU.Lgmbz"
    )
    company = (await company_el.inner_text()).strip() if company_el else "UnknownCompany"
    job_title = (await job_el.inner_text()).strip() if job_el else "UnknownJob"

    pdf_path = generate_empty_cover_letter_pdf(company, job_title)

    file_input = page.locator("input[type='file'][data-testid='FileUpload_COVER_LETTER']")
    if not await file_input.count():
        logger.warning("[Join] No input[type='file'][data-testid='FileUpload_COVER_LETTER']. Trying alternatives...")
        file_input = page.locator("input[type='file'].AttachmentUpload-elements__FileInput-sc-701980d6-1")

    if not await file_input.count():
        logger.warning("[Join] No input[type='file'] with .AttachmentUpload class. Trying accept attribute...")
        file_input = page.locator("input[type='file'][accept*='application/pdf']")

    if not await file_input.count():
        logger.error("[Join] Could not find input[type='file']. Stopping attach.")
        return

    await file_input.set_input_files(pdf_path)
    logger.info("[Join] Attached PDF (cover letter).")
    await ahuman_delay(1, 2)


# ---------------------------------------------------------------------------
#  Основной метод заполнения (fill_incomplete_application) — обновлённая версия
# ---------------------------------------------------------------------------
async def answer_screening_question_page(
        page,
        join_answers: dict,
        translations_cache: dict
) -> bool:
    """
    Handle one page with a single screening question (Chakra UI wizard style).

    Returns True if a question was found and answered, False if no question is present.
    """
    # h2 with question text
    question_el = await page.query_selector(
        "div.chakra-ui-1ddb145 h2.chakra-heading"
    )
    if not question_el:
        # Might be review page or something else
        return False

    raw_question_text = (await question_el.inner_text()).strip()
    if not raw_question_text:
        return False

    logger.info(f"[Join] Screening question: {raw_question_text}")

    # ⚠️ Info-only шаги типа "Confirm your CV" — не требуют ответа, только Continue
    q_lower = raw_question_text.strip().lower()
    info_only_phrases = [
        "confirm your cv",
        "confirm your resume",
        "confirm your curriculum vitae",
        "upload your cover letter",
        "upload cover letter",
        "upload your motivation letter",
    ]

    if any(p in q_lower for p in info_only_phrases):
        logger.info("[Join] Info-only screening page (no input expected), will just click Continue.")
        # Возвращаем True, чтобы внешний цикл в fill_incomplete_application
        # продолжал и нажал Continue.
        return True

    # 🔹 НОВОЕ: шаг с DatePicker внутри вопроса
    datepicker_present = await page.query_selector("div[data-testid='DatePickerInput']")
    if datepicker_present:
        import datetime

        # Пытаемся взять желаемую дату из резюме, если задана
        days_from_today = 7
        default_answer = get_default_answer_from_resume(raw_question_text)
        if default_answer:
            try:
                target_date = datetime.date.fromisoformat(str(default_answer)[:10])
                days_from_today = (target_date - datetime.date.today()).days
                if days_from_today < 0:
                    days_from_today = 7
            except Exception:
                # если не смогли распарсить, оставляем 7 дней
                pass

        ok = await pick_start_date_in_datepicker(page, days_from_today=days_from_today)
        if ok:
            logger.info("[Join] DatePicker question handled (date selected).")
            await ahuman_delay(0.5, 1.0)
            # Возвращаем True: снаружи нажмём Continue
            return True
        else:
            logger.warning("[Join] DatePicker present, but could not select date.")
            # Без даты дальше не пройти, поэтому честно говорим False
            return False

    # Load persistent db once per call
    questions_db = load_questions_db()
    q_key = normalize_question_text(raw_question_text)
    cached_answer = questions_db.get(q_key)

    # Try to detect field type
    textarea = await page.query_selector(
        "div[data-scope='field'][data-part='root'] textarea"
    )
    number_input = await page.query_selector(
        "div[data-scope='field'][data-part='root'] input[type='number']"
    )
    text_input = await page.query_selector(
        "div[data-scope='field'][data-part='root'] input[type='text']"
    )

    if textarea:
        # If we already have an answer saved, fill directly
        if cached_answer:
            await textarea.fill(cached_answer)
            logger.info(f"[Join] Filled textarea from db: {cached_answer}")
        else:
            default_answer = get_default_answer_from_resume(raw_question_text)
            if default_answer:
                await textarea.fill(default_answer)
                logger.info(f"[Join] Filled textarea from resume: {default_answer}")
                questions_db[q_key] = default_answer
                save_questions_db(questions_db)
            else:
                # Use existing interactive handler (translates and asks user)
                await handle_textarea_question(
                    page, raw_question_text, textarea, join_answers, translations_cache
                )
                # If handler wrote answer, try to cache what is inside
                try:
                    value = await textarea.input_value()
                except Exception:
                    value = ""
                if value:
                    questions_db[q_key] = value
                    save_questions_db(questions_db)

        await ahuman_delay(0.8, 1.5)
        return True

    input_el = number_input or text_input
    if input_el:
        if cached_answer:
            await input_el.fill(str(cached_answer))
            logger.info(f"[Join] Filled input from db: {cached_answer}")
        else:
            default_answer = get_default_answer_from_resume(raw_question_text)
            if default_answer:
                await input_el.fill(str(default_answer))
                logger.info(f"[Join] Filled input from resume: {default_answer}")
                questions_db[q_key] = str(default_answer)
                save_questions_db(questions_db)
            else:
                await handle_input_question(
                    page, raw_question_text, input_el, join_answers, translations_cache
                )
                try:
                    value = await input_el.input_value()
                except Exception:
                    value = ""
                if value:
                    questions_db[q_key] = value
                    save_questions_db(questions_db)

        await ahuman_delay(0.8, 1.5)
        return True

    logger.info("[Join] Question found, but no known field type was detected")
    return False


async def fill_incomplete_application(
        page,
        app_url: str,
        join_answers: dict,
        translations_cache: dict
) -> bool:
    """
    Open join.com application by app_url, complete all missing steps and submit.

    Flow supports both older DOM and new Chakra UI wizard:
      - attempts to click "Complete application" if present
      - clicks Continue on neutral steps
      - handles DatePicker using pick_start_date_in_datepicker
      - answers screening questions using answer_screening_question_page
      - final submit (search by several possible button texts)
    """
    try:
        await page.goto(app_url)
        await page.wait_for_load_state("networkidle")
        await accept_cookies_join(page)
        await ahuman_delay(2, 4)

        # Try to click "Complete application" if it's present (talent listing card)
        try:
            complete_btn = await click_button_by_text(page, ["complete application"])
            if complete_btn:
                await move_cursor_to_element(page, complete_btn)
                await complete_btn.scroll_into_view_if_needed()
                await ahuman_delay(0.5, 1.0)
                await complete_btn.click()
                await ahuman_delay(2, 3)
                await page.wait_for_load_state("networkidle")
                logger.info("[Join] Clicked 'Complete application'")
        except Exception as e:
            logger.debug(f"[Join] No 'Complete application' button or click failed: {e}")

        # If page is a wizard, there can be several "Continue" neutral steps
        for _ in range(4):
            await ahuman_delay(1, 2)
            await page.wait_for_load_state("networkidle")

            # Datepicker step
            datepicker_present = await page.query_selector("div[data-testid='DatePickerInput']")
            if datepicker_present:
                break

            # Screening question step
            q_present = await page.query_selector("div.chakra-ui-1ddb145 h2.chakra-heading")
            if q_present:
                break

            # Review step with "Review your application"
            try:
                review_present = await page.query_selector(
                    "h2.chakra-heading:has-text('Review your application')"
                )
            except Exception:
                review_present = None
            if review_present:
                break

            cont_btn = await click_button_by_text(page, ["continue"])
            if cont_btn:
                await move_cursor_to_element(page, cont_btn)
                await cont_btn.scroll_into_view_if_needed()
                await ahuman_delay(0.5, 1.0)
                await cont_btn.click()
                logger.info("[Join] Clicked intermediate 'Continue'")
                continue
            else:
                break

        # Availability / Datepicker step
        datepicker_present = await page.query_selector("div[data-testid='DatePickerInput']")
        if datepicker_present:
            ok = await pick_start_date_in_datepicker(page, days_from_today=7)
            if not ok:
                logger.warning("[Join] Could not select start date, but trying to continue")
            cont_after_date = await click_button_by_text(page, ["continue"])
            if cont_after_date:
                await move_cursor_to_element(page, cont_after_date)
                await cont_after_date.scroll_into_view_if_needed()
                await ahuman_delay(0.5, 1.0)
                await cont_after_date.click()
                await ahuman_delay(2, 3)
                await page.wait_for_load_state("networkidle")
                logger.info("[Join] Date step completed and 'Continue' clicked")

        # Screening questions wizard
        for _ in range(10):
            await ahuman_delay(1, 2)
            await page.wait_for_load_state("networkidle")

            # Check if we are on final review page
            try:
                review_present = await page.query_selector(
                    "h2.chakra-heading:has-text('Review your application')"
                )
            except Exception:
                review_present = None
            if review_present:
                logger.info("[Join] Reached review page")
                break

            answered = await answer_screening_question_page(
                page, join_answers, translations_cache
            )

            if not answered:
                # Не распознали поля (или это инфо-страница нового типа) —
                # пробуем хотя бы нажать Continue.
                cont_btn = await click_button_by_text(page, ["continue"])
                if cont_btn:
                    await move_cursor_to_element(page, cont_btn)
                    await cont_btn.scroll_into_view_if_needed()
                    await ahuman_delay(0.5, 1.0)
                    await cont_btn.click()
                    logger.info("[Join] Clicked 'Continue' on page without known question input")
                    # Переходим к следующей итерации (следующий шаг мастера)
                    continue
                else:
                    logger.info(
                        "[Join] No 'Continue' button on unknown-question page, "
                        "stopping screening loop"
                    )
                    break

            # answered == True → обычная логика: нажимаем Continue после ответа/инфо-шага
            cont_btn = await click_button_by_text(page, ["continue"])
            if not cont_btn:
                logger.info("[Join] No 'Continue' button after answering question")
                break

            await move_cursor_to_element(page, cont_btn)
            await cont_btn.scroll_into_view_if_needed()
            await ahuman_delay(0.5, 1.0)
            await cont_btn.click()
            logger.info("[Join] Clicked 'Continue' after question")

        # Fallback for older UI: scan for QuestionItem blocks and fill them (legacy)
        question_blocks = await page.query_selector_all("div[data-testid='QuestionItem']")
        if question_blocks:
            # If we reached here and question_blocks exist, use legacy logic for compatibility
            days_for_start = 5
            start_date = datetime.date.today() + datetime.timedelta(days=days_for_start)
            formatted_date = start_date.strftime("%d.%m.%Y")

            for qb in question_blocks:
                try:
                    question_el = await qb.query_selector("span.sc-gLDzan, span.sc-blLsxD")
                    if not question_el:
                        continue
                    raw_question_text = (await question_el.inner_text()).strip()

                    # DateField
                    date_field = await qb.query_selector("div[data-testid='DateField']")
                    if date_field:
                        date_input = await date_field.query_selector("input")
                        if date_input:
                            # Попробуем дата-пикер первым, иначе заполним в формате dd.mm.YYYY
                            if not await pick_start_date_in_datepicker(page, days_from_today=5):
                                await date_input.fill(formatted_date)
                            logger.info(f"[Join] Date '{formatted_date}' for: {raw_question_text}")
                            await ahuman_delay(0.5, 1)
                        continue

                    # TextArea
                    text_area = await qb.query_selector("textarea[data-testid='TextAreaField']")
                    if text_area:
                        await handle_textarea_question(
                            page, raw_question_text, text_area, join_answers, translations_cache
                        )
                        await ahuman_delay(1, 2)
                        continue

                    # Input
                    input_field = await qb.query_selector("div[data-testid='InputField']")
                    if input_field:
                        text_input = await input_field.query_selector("input[data-testid='TextInput']")
                        if text_input:
                            await handle_input_question(
                                page, raw_question_text, text_input, join_answers, translations_cache
                            )
                            await ahuman_delay(1, 2)
                        continue

                    # Yes/No
                    yes_btn = await qb.query_selector("div[data-testid='YesAnswer']")
                    no_btn = await qb.query_selector("div[data-testid='NoAnswer']")
                    if yes_btn and no_btn:
                        possible_answers = ["Yes", "No"]
                        user_answer = ask_user_for_answer(
                            page, raw_question_text, possible_answers, join_answers, translations_cache
                        )
                        if user_answer.lower() == "yes":
                            await yes_btn.click()
                        else:
                            await no_btn.click()
                        await ahuman_delay(1, 2)
                        continue

                    # Радио-кнопки
                    radio_labels = await qb.query_selector_all(
                        "span.chakra-radio__label.css-29jn7p"
                    )
                    if radio_labels:
                        possible_answers = [
                            (await lbl.inner_text()).strip() for lbl in radio_labels
                        ]
                        user_answer = ask_user_for_answer(
                            page, raw_question_text, possible_answers, join_answers, translations_cache
                        )
                        for lbl in radio_labels:
                            lbl_text = (await lbl.inner_text()).strip()
                            if lbl_text.lower() == user_answer.lower():
                                await lbl.click()
                                await ahuman_delay(1, 2)
                                break

                except Exception as e:
                    logger.debug(f"[Join] Error processing legacy question: {e}")

        # Optional: fill professional links from resume
        resume_data = get_resume_data()
        pi = resume_data.get("personal_information", {})
        links_map = {
            "LINKEDIN": pi.get("linkedin", ""),
            "XING": pi.get("xing", ""),
            "GITHUB": pi.get("github", ""),
            "PORTFOLIO": pi.get("portfolio", ""),
        }
        for link_type, link_value in links_map.items():
            if not link_value:
                continue
            sel = (
                f"div[data-testid='ProfessionalLink_{link_type}'] "
                f"input[name='professionalLinks.{link_type}']"
            )
            link_input = await page.query_selector(sel)
            if link_input:
                await fill_if_different(link_input, link_value)
                await ahuman_delay(0.5, 0.8)

        # Country and phone if needed
        await fill_contact_details(page)

        # Final submit
        submit_btn = None
        possible_submit_texts = [
            "submit application",
            "submit information",
            "send application",
            "apply now",
            "apply",
            "informationen einreichen",
            "absenden",
        ]

        candidates = await page.query_selector_all("button[type='button']")
        for c in candidates:
            try:
                btn_text = (await c.inner_text()).strip().lower()
            except Exception:
                continue
            if any(keyword in btn_text for keyword in possible_submit_texts):
                submit_btn = c
                break

        if not submit_btn:
            candidates = await page.query_selector_all("button[type='submit']")
            for c in candidates:
                try:
                    btn_text = (await c.inner_text()).strip().lower()
                except Exception:
                    continue
                if any(keyword in btn_text for keyword in possible_submit_texts):
                    submit_btn = c
                    break

        if not submit_btn:
            logger.warning("[Join] No final submit button found")
            return False

        await move_cursor_to_element(page, submit_btn)
        await submit_btn.scroll_into_view_if_needed()
        await ahuman_delay(1, 2)
        await submit_btn.click()
        await ahuman_delay(2, 4)
        logger.info("[Join] Clicked final submit button")

        # Не прикрепляем cover_letter по умолчанию (если всё же потребуется,
        # attach_cover_letter_pdf_if_required)
        await attach_cover_letter_pdf_if_required(page)

        # "Update profile" диалог
        try:
            await page.wait_for_selector("div[data-testid='ModalDialog']", timeout=5000)
            update_btn = await page.query_selector("[data-testid='updateProfile']")
            if update_btn:
                await move_cursor_to_element(page, update_btn)
                await update_btn.click()
                await ahuman_delay(1, 2)
                logger.info("[Join] Clicked 'Yes, update profile'")
        except Exception:
            logger.info("[Join] No 'update profile' dialog appeared, continuing")

        # Success message
        try:
            await page.wait_for_selector(
                "text=/Your application was successful\\. Awesome!|Deine Bewerbung "
                "war erfolgreich - Super!/i",
                timeout=10000,
            )
            logger.info("[Join] Application successful (found success message)")
            return True
        except Exception:
            logger.warning("[Join] Did not see a known success message. Something might be wrong")
            return False

    except Exception as e:
        logger.error(f"[Join] Error filling application {app_url}: {e}")
        return False


# ---------------------------------------------------------------------------
#  Парсинг «незавершённых» заявок и обход страниц
# ---------------------------------------------------------------------------
async def parse_incomplete_applications_on_current_page(page) -> list[str]:
    """
    Парсим заявки на текущей странице /talent/applications и возвращаем
    список ссылок (href) только для статуса "Incomplete application".
    """
    await page.wait_for_load_state("networkidle")
    await accept_cookies_join(page)
    await ahuman_delay(2, 4)

    app_cards = await page.query_selector_all("div[data-testid='ApplicationItem']")
    logger.info(f"[Join] Found {len(app_cards)} applications on the current page.")

    incomplete_links: list[str] = []

    for card in app_cards:
        try:
            # 1) статус — в span.chakra-tag__label
            status_badge = await card.query_selector("span.chakra-tag__label")
            if not status_badge:
                continue

            badge_text = (await status_badge.inner_text()).strip().lower()

            # Нам нужны только "Incomplete application"
            # (на всякий случай через contains по 'incomplete')
            if "incomplete" not in badge_text:
                continue

            # 2) href сидит у ближайшего родительского <a>
            href = await card.evaluate(
                """el => {
                    const a = el.closest('a');
                    return a ? a.href : null;
                }"""
            )

            if href:
                incomplete_links.append(href)
        except Exception as e:
            logger.debug(f"[Join] Error processing application card: {e}")
            continue

    logger.info(f"[Join] Found {len(incomplete_links)} 'Incomplete application' apps on this page.")
    return incomplete_links


async def parse_incomplete_applications(page, max_scrolls: int = 5) -> list[str]:
    """
    Переходит на /talent/applications и собирает все "Incomplete application".
    Сейчас там одна страница с подгрузкой, поэтому:
      - заходим на TALENT_APPLICATIONS_URL,
      - несколько раз скроллим вниз (max_scrolls),
      - парсим все видимые карточки.
    Возвращает список уникальных ссылок.
    """
    await page.goto(TALENT_APPLICATIONS_URL)
    await page.wait_for_load_state("networkidle")
    await accept_cookies_join(page)
    await ahuman_delay(2, 4)

    # Простой infinite-scroll: несколько раз скроллим к низу страницы,
    # чтобы подтянуть дополнительные заявки (если есть).
    last_height = await page.evaluate("() => document.body.scrollHeight")

    for i in range(max_scrolls):
        logger.info(f"[Join] Scrolling applications page (step {i + 1}/{max_scrolls}).")
        # Крутим колесо мыши вниз
        await page.mouse.wheel(0, 2000)
        await ahuman_delay(1, 2)

        new_height = await page.evaluate("() => document.body.scrollHeight")
        if new_height == last_height:
            logger.info("[Join] No more content loaded on scroll, stopping.")
            break
        last_height = new_height

    all_incomplete_links = await parse_incomplete_applications_on_current_page(page)

    # На всякий случай убираем дубли
    unique_links = list(dict.fromkeys(all_incomplete_links))
    logger.info(f"[Join] Total unique 'Incomplete application' links: {len(unique_links)}")

    return unique_links


# ---------------------------------------------------------------------------
#  Основная функция: apply_incomplete_applications
# ---------------------------------------------------------------------------
async def apply_incomplete_applications(page, context):
    """
    - Убеждается, что мы залогинены (check_join_login).
    - Парсит ссылки незавершённых заявок (до 5 страниц).
    - Для каждой заявки вызывает fill_incomplete_application.
    """
    ensure_db_file()
    all_data = load_join_data()
    join_answers = all_data["join_answers"]
    translations_cache = all_data["join_translations"]


    incomplete_links = await parse_incomplete_applications(page)
    logger.info(f"[Join] Found {len(incomplete_links)} incomplete apps (on up to {len(incomplete_links)} pages).")

    for link in incomplete_links:
        logger.info(f"[Join] Filling form: {link}")
        ok = await fill_incomplete_application(page, link, join_answers, translations_cache)
        if ok:
            logger.info(f"[Join] Successfully submitted application: {link}")
        else:
            logger.warning(f"[Join] Could not submit application: {link}")


# ---------------------------------------------------------------------------
#  Точка входа (пример)
# ---------------------------------------------------------------------------
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
