# --- services/scraping/xing_scraper.py ---

"""
Скрапер XING Jobs (async, Playwright).

*Новое в v2.1*
1. Все блокирующие `human_delay()` заменены на `await ahuman_delay()`.
2. Импортирована новая асинхронная пауза из utils.
"""

import csv
import os
import time
from collections import defaultdict

from langdetect import detect, LangDetectException

from playwright.async_api import Page, TimeoutError

from core.constants import (
    XING_COOKIES_FILE,
    JOB_LISTINGS_HEADERS,
    MAX_SCROLLS,
    MAX_JOBS_COLLECTED,
    FILTER_CONFIG,
    OPENAI_API_KEY,
    STYLES_CSS_FILE,
    RESUME_YAML_FILE,
    JOB_KEYWORDS,
    XING_ALLOWED_LANGS, XING_PHONE_COUNTRY_CODE, XING_PHONE_NUMBER,
)
from core.logger import logger
from services.gpt.gpt_resume_builder import generate_entire_resume_pdf
from services.scraping.base_scraper import BaseScraper
from services.scraping.utils import (
    ahuman_delay,  # неблокирующая пауза
    move_cursor_to_element,
    update_csv_file,
    load_existing_urls,
)


async def accept_cookies_if_present(page: Page) -> None:
    """
    Пытаемся нажать 'Accept all' на cookie баннере, если он показан.
    Не падаем, если баннера нет.
    """
    try:
        footer = await page.query_selector("div[data-testid='uc-footer']")
        if not footer:
            return

        btn = await footer.query_selector("button[data-testid='uc-accept-all-button']")
        if not btn:
            # запасной вариант по тексту
            btn = await footer.query_selector("button:has-text('Accept all')")

        if btn:
            logger.debug("[accept_cookies_if_present] Найдена панель cookies, жмём 'Accept all'.")
            await move_cursor_to_element(page, btn)
            await btn.click()
            await ahuman_delay(1, 2)
    except Exception as e:
        logger.debug(f"[accept_cookies_if_present] Ошибка при закрытии cookie баннера: {e}")


class XingScraper(BaseScraper):
    """
    Класс для работы с вакансиями на XING (авторизация, сбор).
    Наследуется от BaseScraper, умеющего работать с куками.
    """
    def __init__(self, cookies_file: str = XING_COOKIES_FILE):
        logger.debug("[XingScraper] Инициализация экземпляра XingScraper")
        super().__init__(cookies_file_path=cookies_file)

    async def login(self, page: Page, email: str, password: str) -> bool:
        """
        Проверяем, есть ли валидные cookies, если нет — логинимся заново.
        Возвращает True при успешной авторизации.
        """
        logger.debug("[XingScraper] Начало процедуры логина.")
        logger.info("[XingScraper] Проверяем авторизацию (cookies)...")

        # 1) Пробуем подлить cookies (если файл есть)
        await self.load_cookies(page)
        logger.debug("[XingScraper] Обработали cookies (если были). Переходим на главную страницу.")

        # 2) Открываем главную, но НЕ умираем, если что-то долго грузится
        try:
            await page.goto("https://www.xing.com/", wait_until="domcontentloaded", timeout=45000)
        except TimeoutError:
            logger.warning("[XingScraper] Timeout при загрузке https://www.xing.com/, продолжаем дальше.")

        # Дадим странице чуть отдышаться
        await ahuman_delay(1, 2)

        # возможно, сразу показывается cookie баннер
        await accept_cookies_if_present(page)

        logger.debug("[XingScraper] Главная страница (скорее всего) загружена, выполняем проверку авторизации.")

        # 3) Проверяем, авторизованы ли мы уже
        if await self.is_logged_in(page):
            logger.info("[XingScraper] Уже авторизованы (cookies сработали).")
            logger.debug("[XingScraper] Завершаем процедуру логина с положительным результатом.")
            return True

        # 4) Если нет — идём на страницу логина
        logger.info("[XingScraper] Пытаемся авторизоваться заново...")
        try:
            await page.goto("https://login.xing.com/", wait_until="domcontentloaded", timeout=45000)
        except TimeoutError:
            logger.error("[XingScraper] Timeout при загрузке страницы логина https://login.xing.com/")
            return False

        # Ждём появления поля логина, а не абстрактного 'networkidle'
        try:
            await page.wait_for_selector("#username", timeout=15000)
        except TimeoutError:
            logger.error("[XingScraper] Не дождались поля #username на странице логина.")
            return False

        logger.debug("[XingScraper] Страница логина загружена, заполняем форму.")

        await page.fill("#username", email)
        logger.debug(f"[XingScraper] Заполнено поле username: {email}")
        await ahuman_delay(1, 2)

        await page.fill("#password", password)
        logger.debug("[XingScraper] Заполнено поле password.")
        await ahuman_delay(1, 2)

        login_btn = await page.query_selector("button:has-text('Log in')")
        if login_btn:
            logger.debug("[XingScraper] Найдена кнопка Log in, перемещаем курсор и кликаем.")
            await move_cursor_to_element(page, login_btn)
            await login_btn.click()
            await ahuman_delay(3, 5)
        else:
            logger.debug("[XingScraper] Кнопка Log in не найдена на странице.")
            return False

        # Здесь тоже не ждём networkidle, а просто чуть подождём и проверим статус
        await ahuman_delay(2, 3)

        if await self.is_logged_in(page):
            # Сохранить cookies
            await self.save_cookies(page)
            logger.info("[XingScraper] Авторизация прошла успешно.")
            logger.debug("[XingScraper] Cookies сохранены после успешного логина.")
            return True
        else:
            logger.error("[XingScraper] Ошибка логина на XING (после отправки формы не увидели признак авторизации).")
            return False

    async def is_logged_in(self, page: Page) -> bool:
        """
        Признак авторизации на XING — наличие аватарки/профильных элементов.
        """
        logger.debug("[XingScraper] Проверяем наличие элементов, указывающих на авторизацию.")
        avatar = await page.query_selector("img[data-testid='header-profile-logo']")
        me_tab = await page.query_selector("a[data-testid='layout-me']")
        is_logged = bool(avatar or me_tab)
        logger.debug(f"[XingScraper] Результат проверки авторизации: {is_logged}")
        return is_logged


async def scrape_xing_jobs(
    page: Page,
    urls: list[str],
    job_listings_csv: str,
    stats_csv: str,
    email: str,
    password: str
):
    """
    Главная функция сбора вакансий:
     1) Создаём экземпляр XingScraper и логинимся
     2) Идём по списку initial_urls
     3) На каждой странице прокручиваем и собираем
    """
    logger.debug("[scrape_xing_jobs] Инициализация процесса сбора вакансий.")
    # Инициализируем файл, если нет
    if not os.path.exists(job_listings_csv):
        logger.debug(f"[scrape_xing_jobs] Файл {job_listings_csv} не существует, создаём новый.")
        with open(job_listings_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(JOB_LISTINGS_HEADERS)

    scraper = XingScraper()
    # Логинимся
    if not await scraper.login(page, email, password):
        logger.error("[scrape_xing_jobs] Логин не удался, прекращаем.")
        return

    for url in urls:
        logger.info(f"[scrape_xing_jobs] Открываем URL: {url}")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            logger.debug(f"[scrape_xing_jobs] {url} загружен (domcontentloaded).")

            await accept_cookies_if_present(page)

            # Для SPA, как XING, networkidle может не наступать вообще, поэтому делаем мягко:
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
                logger.debug("[scrape_xing_jobs] Состояние networkidle достигнуто.")
            except Exception as e:
                logger.warning(f"[scrape_xing_jobs] Не дождались networkidle: {e!r}")

            await ahuman_delay(2, 3)
            logger.debug(f"[scrape_xing_jobs] Страница {url} загружена, применяем фильтры.")

            # Здесь явно вызываем сбор вакансий
            added = await scroll_and_collect(page, job_listings_csv)
            logger.info(f"[scrape_xing_jobs] Для {url} добавлено {added} новых вакансий.")

        except Exception as e:
            logger.exception(f"[scrape_xing_jobs] Ошибка при обработке {url}: {e!r}")
            # продолжаем с другими URL, а не завершаем весь скрипт
            continue

        # Применяем фильтры (если нужно)
        await apply_filters(page, FILTER_CONFIG)

        # Прокрутка + сбор
        new_count = await scroll_and_collect(page, job_listings_csv)
        logger.info(f"[scrape_xing_jobs] Добавлено новых вакансий: {new_count}")

        # Дописать в stats.csv (при желании)
        if stats_csv:
            append_stats(stats_csv, url, new_count)
            logger.debug(f"[scrape_xing_jobs] Статистика обновлена для URL: {url}")


async def scroll_and_collect(page: Page, job_listings_csv: str) -> int:
    """
    Прокручивает страницу, ищет карточки вакансий, открывает каждую в новой вкладке,
    парсит описание, добавляет в CSV. Возвращает количество новых добавленных записей.
    Новизна карточки определяется по уникальному URL вакансии.
    Если за 3 итерации подряд не появляется ни одной новой карточки (DOM-новинки),
    функция прерывает сбор, считая, что страница не обновляется.
    Обрабатываются только те вакансии, у которых в ссылке присутствует хотя бы одно из ключевых слов.
    """
    logger.debug("[scroll_and_collect] Начало процедуры скроллинга и сбора вакансий.")

    existing_urls = load_existing_urls(job_listings_csv)
    total_new = 0
    scroll_count = 0
    consecutive_empty = 0
    job_cards_seen: set[str] = set()

    # буфер для пачечной записи
    buffer: list[list[str]] = []
    FLUSH_EVERY = 10

    def flush_buffer():
        nonlocal buffer
        if not buffer:
            return
        with open(job_listings_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(buffer)
        logger.debug(f"[scroll_and_collect] Flushed {len(buffer)} rows to CSV.")
        buffer.clear()

    show_more_selectors = [
        "button:has-text('Show more')",   # старый селектор
        "button:has-text('Load more')",   # запасной
        "button:has-text('Mehr anzeigen')"  # на случай немецкого интерфейса
    ]

    # Набор селекторов для ссылок вакансий (новые + старые)
    job_link_selectors = [
        # новый/основной: сразу ссылка-карточка
        "a[data-testid='job-search-result']",
        # старый вариант: контейнер <article data-testid='job-search-result'>, берём ссылки внутри
        "article[data-testid='job-search-result'] a[href]",
    ]

    while scroll_count < MAX_SCROLLS:
        scroll_count += 1
        logger.debug(f"[scroll_and_collect] Скролл #{scroll_count} начинается.")

        # Скроллим вниз (примитивно)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await ahuman_delay(2, 3)
        logger.debug("[scroll_and_collect] Прокрутка страницы выполнена.")

        # Нажимаем кнопку "Show more" / "Load more" / "Mehr anzeigen", если найдена
        show_more_btn = None
        for sel in show_more_selectors:
            show_more_btn = await page.query_selector(sel)
            if not show_more_btn:
                continue

            # проверяем, активна ли кнопка
            if not await show_more_btn.is_enabled():
                logger.debug(
                    f"[scroll_and_collect] Кнопка по селектору {sel} найдена, но не активна. "
                    f"Считаем, что больше подгружать нечего."
                )
                show_more_btn = None
                continue

            logger.debug(f"[scroll_and_collect] Найдена активная кнопка подгрузки по селектору: {sel}, кликаем по ней.")
            await move_cursor_to_element(page, show_more_btn)
            await show_more_btn.click()
            await ahuman_delay(1, 2)
            break

        # Собираем ссылки вакансий по нескольким селекторам (новый + старые, на всякий случай)
        cards = []
        for sel in job_link_selectors:
            found = await page.query_selector_all(sel)
            if found:
                logger.debug(
                    f"[scroll_and_collect] Итерация {scroll_count}: по селектору '{sel}' найдено {len(found)} элементов."
                )
                cards.extend(found)

        logger.debug(
            f"[scroll_and_collect] Итерация {scroll_count}: всего найдено {len(cards)} кандидатов на вакансии."
        )

        new_cards_dom = 0  # сколько новых карточек (по DOM) нашли в этой итерации
        new_in_iter = 0    # сколько новых URL добавили в CSV

        for card in cards:
            # Ссылка вакансии
            href = await card.get_attribute("href")
            if not href:
                continue

            # Делает полный URL (если он относительный, типа "/jobs/...")
            if href.startswith("/jobs/"):
                full_url = "https://www.xing.com" + href
            else:
                full_url = href

            # Если уже видели этот URL в DOM, пропускаем (на уровне текущей сессии)
            if full_url in job_cards_seen:
                continue

            job_cards_seen.add(full_url)
            new_cards_dom += 1  # новая карточка в текущей итерации

            # Фильтруем по ключевым словам (только если в URL есть одно из JOB_KEYWORDS)
            if not any(keyword.lower() in full_url.lower() for keyword in JOB_KEYWORDS):
                logger.debug(f"[scroll_and_collect] Пропуск вакансии {full_url} - без ключевых слов.")
                continue

            # Если вакансия уже в CSV — пропускаем
            if full_url in existing_urls:
                continue

            logger.debug(f"[scroll_and_collect] Обнаружена новая вакансия: {full_url}")

            # Парсим вакансию (открываем во вкладке, извлекаем данные)
            apply_status, external_url, description = await inspect_job(page, full_url)
            logger.debug(
                f"[scroll_and_collect] Результат парсинга вакансии: "
                f"status={apply_status}, external_url={external_url}"
            )

            if apply_status == "not_allowed_lang":
                logger.debug(f"[scroll_and_collect] Пропускаем {full_url}: язык описания не подходит.")
                # Можно записать строку с пустым описанием и статусом
                row = [
                    full_url,
                    apply_status,
                    "",  # external_url
                    "",  # description
                    "",
                    "",
                    time.strftime("%Y-%m-%d"),
                ]
            else:
                row = [
                    full_url,
                    apply_status,
                    external_url,
                    description,
                    "",
                    "",
                    time.strftime("%Y-%m-%d"),
                ]

            buffer.append(row)
            existing_urls.add(full_url)
            new_in_iter += 1
            total_new += 1

            # каждые 10 строк — запись на диск
            if len(buffer) >= FLUSH_EVERY:
                flush_buffer()

            if total_new >= MAX_JOBS_COLLECTED:
                logger.debug("[scroll_and_collect] Достигнуто MAX_JOBS_COLLECTED, останавливаемся.")
                break

        # Если не нашли новых карточек в DOM, увеличиваем счётчик consecutive_empty
        if new_cards_dom == 0:
            consecutive_empty += 1
            logger.debug(
                f"[scroll_and_collect] Итерация #{scroll_count}: нет новых DOM-карточек "
                f"(подряд {consecutive_empty})."
            )
        else:
            consecutive_empty = 0

        # Проверяем условия выхода
        if total_new >= MAX_JOBS_COLLECTED:
            break
        if consecutive_empty >= 3:
            logger.info("[scroll_and_collect] Три итерации подряд без новых карточек — завершаем.")
            break

    # финальный флеш, чтобы не потерять «хвост»
    flush_buffer()

    logger.debug(f"[scroll_and_collect] Сбор завершён: всего новых {total_new}")
    return total_new


def is_description_language_allowed(text: str, allowed_langs: list[str]) -> bool:
    """
    Проверяет, что язык текста входит в список допустимых.
    Пустой или очень короткий текст считаем "не прошедшим" (можно поменять логику при желании).
    """
    if not text:
        return False

    sample = text.strip()
    # Можно обрезать до N символов, чтобы langdetect не страдал от очень длинных текстов
    if len(sample) > 5000:
        sample = sample[:5000]

    try:
        lang = detect(sample)
    except LangDetectException:
        return False

    return lang in allowed_langs


async def is_job_not_available(page: Page) -> bool:
    """
    Проверка empty-state "This job ad isn't available." и аналогичных.
    """
    try:
        h2 = await page.query_selector("h2[data-xds='Headline']")
        if not h2:
            return False
        text = (await h2.inner_text() or "").strip().lower()
        if "this job ad isn't available" in text or "this job ad isnt available" in text:
            logger.info("[is_job_not_available] Вакансия в состоянии 'This job ad isn't available'.")
            return True
        return False
    except Exception as e:
        logger.debug(f"[is_job_not_available] Ошибка при проверке empty-state: {e}")
        return False


async def inspect_job(page: Page, job_url: str) -> tuple[str, str, str]:
    """
    Открываем вакансию в новой вкладке, пытаемся вытащить описание,
    определить external_url и apply_status.
    """
    logger.debug(f"[inspect_job] Начало парсинга вакансии: {job_url}")
    apply_status = ""
    external_url = ""
    description = ""

    new_tab: Page | None = None

    try:
        # Ожидаем новую вкладку
        async with page.context.expect_page() as new_page_info:
            await page.evaluate("url => window.open(url, '_blank')", job_url)
        new_tab = await new_page_info.value
        logger.debug(f"[inspect_job] Открыта новая вкладка для вакансии: {job_url}")

        try:
            await new_tab.wait_for_load_state("networkidle", timeout=30000)
        except TimeoutError:
            logger.warning(f"[inspect_job] Таймаут ожидания networkidle для {job_url}")

        # cookies на странице вакансии
        await accept_cookies_if_present(new_tab)

        # === Проверяем empty-state: "This job ad isn't available." ===
        if await is_job_not_available(new_tab):
            apply_status = "not_available"
            external_url = ""
            # берём текст заголовка как описание (если нужно)
            h2 = await new_tab.query_selector("h2[data-xds='Headline']")
            if h2:
                description = (await h2.inner_text() or "").strip()
            await new_tab.close()
            logger.debug(f"[inspect_job] Вакансия {job_url} недоступна (not_available).")
            return apply_status, external_url, description

        # Попробуем извлечь описание
        description = await extract_job_description(new_tab)
        logger.debug(f"[inspect_job] Извлечено описание вакансии длиной {len(description)} символов.")

        # 2. Проверяем язык описания
        if not is_description_language_allowed(description, XING_ALLOWED_LANGS):
            logger.info(
                f"[inspect_job] Описание вакансии {job_url} не соответствует допустимым языкам: {XING_ALLOWED_LANGS}"
            )
            await new_tab.close()
            # Можно вернуть специальный статус или просто пустое описание + 'not_allowed_lang'
            return "not_allowed_lang", "", ""

        # Проверим, не external ли баннер
        if await check_external_banner(new_tab):
            logger.debug("[inspect_job] Обнаружен внешний баннер вакансии.")
            apply_status = "external"
            ext_btn = await new_tab.query_selector("a.button-styles__RouterButton-sc-")
            if ext_btn:
                external_url = (await ext_btn.get_attribute("href")) or ""
            await new_tab.close()
            return apply_status, external_url, ""

        # Ищем Easy Apply
        if await has_easy_apply_button(new_tab):
            logger.debug("[inspect_job] Найдена кнопка Easy apply.")
            apply_status = ""
        else:
            # Ищем external link
            ext_link = await find_employer_website(new_tab)
            if ext_link:
                external_url = ext_link
                apply_status = "external"
                description = ""
                logger.debug("[inspect_job] Обнаружена внешняя ссылка на сайт работодателя.")
            else:
                # Возможно, чат?
                chat_btn = await new_tab.query_selector("button[data-testid='applyAction']")
                if chat_btn:
                    apply_status = "chat"
                    logger.debug("[inspect_job] Обнаружена кнопка чата для отклика.")
                else:
                    apply_status = "error_easy"
                    logger.debug(
                        "[inspect_job] Не удалось определить способ отклика "
                        "(нет Easy apply, внешней ссылки или чата)."
                    )

        await new_tab.close()

    except TimeoutError:
        logger.warning(f"[inspect_job] Таймаут при открытии {job_url}")
        apply_status = "timeout"
        if new_tab:
            try:
                await new_tab.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[inspect_job] Ошибка при открытии {job_url}: {e}")
        apply_status = "error_load"
        if new_tab:
            try:
                await new_tab.close()
            except Exception:
                pass

    logger.debug(f"[inspect_job] Завершаем парсинг вакансии: {job_url} с результатом: {apply_status}")
    return apply_status, external_url, description


async def extract_job_description(tab: Page) -> str:
    """
    Ищем div с описанием, при наличии кнопки "Show more" — можно расширить при желании.
    """
    logger.debug("[extract_job_description] Поиск описания вакансии.")

    desc_el = await tab.query_selector("div[class^='description-module__DescriptionWrapper']")
    if desc_el:
        description = (await desc_el.inner_text()).strip()
        logger.debug(f"[extract_job_description] Описание найдено, длина: {len(description)} символов.")
        return description
    logger.debug("[extract_job_description] Описание не найдено.")
    return ""


async def check_external_banner(tab: Page) -> bool:
    logger.debug("[check_external_banner] Проверка на наличие внешнего баннера.")
    banner = await tab.query_selector("div[class^='external-job-banner__Container']")
    found = bool(banner)
    logger.debug(f"[check_external_banner] Внешний баннер {'найден' if found else 'не найден'}.")
    return found


async def has_easy_apply_button(tab: Page) -> bool:
    """
    Checks for a <button data-testid="apply-button"> whose text contains "Easy apply".
    Returns True if found, else False.
    """
    # Grab the button by data-testid
    apply_btn = await tab.query_selector("button[data-testid='apply-button']")

    if not apply_btn:
        return False  # no such button at all

    # Check text content to verify it really says "Easy apply"
    btn_text = (await apply_btn.inner_text() or "").strip().lower()
    return "easy apply" in btn_text


async def find_employer_website(tab: Page) -> str:
    """
    Иногда есть кнопка/ссылка "Visit employer website" или "Apply on employer website".
    """
    logger.debug("[find_employer_website] Поиск ссылки на сайт работодателя.")
    visit_btn = await tab.query_selector("button[data-testid='apply-button']")
    if visit_btn:
        text_btn = (await visit_btn.inner_text() or "").strip().lower()
        # учитываем оба варианта текста
        if (
            "visit employer website" in text_btn
            or "apply on employer website" in text_btn
        ):
            logger.debug(
                f"[find_employer_website] Найдена кнопка перехода на сайт "
                f"работодателя ('{text_btn}'), кликаем."
            )
            async with tab.context.expect_page() as popup_info:
                await visit_btn.click()
            popup = await popup_info.value
            await popup.wait_for_load_state()
            url = popup.url
            await popup.close()
            logger.debug(f"[find_employer_website] Получен внешний URL: {url}")
            return url

    # Или a[data-testid='applyAction']
    links = await tab.query_selector_all("a[data-testid='applyAction']")
    for link in links:
        href = await link.get_attribute("href") or ""
        if href:
            logger.debug(f"[find_employer_website] Найдена ссылка: {href}")
            return href
    logger.debug("[find_employer_website] Ссылка на сайт работодателя не найдена.")
    return ""


# A helper that toggles "tag-based" filters
async def apply_tag_filter(page: Page, filter_items: list[str]) -> None:
    """
    For each text in filter_items, finds a <button data-xds='InteractiveTag'>
    whose inner text matches, and clicks if aria-pressed='false'.
    """
    # Grab all 'InteractiveTag' buttons once and reuse if desired
    # Alternatively re-query after each click if the DOM changes drastically
    all_buttons = await page.query_selector_all("button[data-xds='InteractiveTag']")

    for item_text in filter_items:
        found_match = False
        item_lower = item_text.lower()
        for btn in all_buttons:
            text_content = (await btn.inner_text() or "").strip().lower()
            # e.g. "germany (3,139)" => if "germany" in "germany (3,139)"
            if item_lower in text_content:
                # Check if pressed
                aria_pressed = await btn.get_attribute("aria-pressed")
                if aria_pressed == "false":
                    logger.debug(f"[apply_tag_filter] Activating filter: '{item_text}'")
                    await move_cursor_to_element(page, btn)
                    await btn.click()
                    await ahuman_delay(1, 2)  # short pause
                found_match = True
                break
        if not found_match:
            logger.debug(f"[apply_tag_filter] No matching button found for '{item_text}'")


# A helper that toggles "checkbox-based" filters
async def apply_checkbox_filter(page: Page, filter_items: list[str]) -> None:
    """
    For each text in filter_items, finds a <label data-xds='Label'> that has an
    <input type='checkbox'> inside, whose label text includes that filter name,
    and checks it if not checked already.
    """
    # All <label data-xds='Label'> elements
    label_elements = await page.query_selector_all("label[data-xds='Label']")

    for item_text in filter_items:
        found_match = False
        item_lower = item_text.lower()
        for label_el in label_elements:
            label_text = (await label_el.inner_text() or "").strip().lower()
            # e.g. "analysis and statistics (125)" => if "analysis and statistics" in ...
            if item_lower in label_text:
                # The <input type="checkbox">
                input_el = await label_el.query_selector("input[data-xds='Checkbox']")
                if input_el is None:
                    continue
                checked = await input_el.is_checked()
                if not checked:
                    logger.debug(f"[apply_checkbox_filter] Checking: '{item_text}'")
                    await move_cursor_to_element(page, label_el)
                    await label_el.click()
                    await ahuman_delay(1, 2)
                found_match = True
                break
        if not found_match:
            logger.debug(f"[apply_checkbox_filter] No matching checkbox found for '{item_text}'")


async def apply_salary_filter(page: Page, min_salary: int, max_salary: int) -> None:
    """
    A rough approach to set salary slider inputs. We locate them by:
       span.MuiSlider-thumb[data-index='0'] (MIN)
       span.MuiSlider-thumb[data-index='1'] (MAX)
    Then set the <input type="range"> values via JavaScript.
    Some websites require dispatching events after changing the input's value.
    """
    logger.debug(f"[apply_salary_filter] Setting salary range to {min_salary} - {max_salary}")

    try:
        # Evaluate a small script to set the values of the 2 range inputs
        # Then dispatch "input" or "change" events so the page picks it up
        await page.evaluate(
            """([min, max]) => {
                 const inputs = document.querySelectorAll('input[type="range"]');
                 if (inputs.length >= 2) {
                     inputs[0].value = min;
                     inputs[1].value = max;
                     // Fire input events for each
                     const evt = new Event('input', { bubbles: true });
                     inputs[0].dispatchEvent(evt);
                     inputs[1].dispatchEvent(evt);
                 }
               }""",
            [min_salary, max_salary]
        )
        await ahuman_delay(1, 2)
    except Exception as e:
        logger.warning(f"[apply_salary_filter] Failed to set salary range: {e}")


async def apply_filters(page: Page, filters: dict):
    """
    Применяет все фильтры на странице XING Jobs, исходя из структуры `filters`.

    Expected keys:
      - "country": ["Germany", "Switzerland", ...]        # Tag-based
      - "city": ["Berlin", "Hamburg", ...]               # Tag-based
      - "sort": ["Newest first", "Most relevant first"]   # Tag-based
      - "remoteOption": ["Full Remote", "Hybrid"]         # Tag-based
      - "employmentType": ["Full-time", "Part-time"]      # Tag-based
      - "careerLevel": ["Student/Intern", "Entry Level"]  # Tag-based
      - "benefitWorkingCulture": ["Flexitime", ...]       # Tag-based
      - "benefitEmployeePerk": ["Company car", ...]       # Tag-based
      - "discipline": ["Analysis and statistics", ...]    # Checkbox-based
      - "industry": ["Aerospace", "Academia", ...]        # Checkbox-based
      - "salary": [min_salary, max_salary]                # Range slider

    Example:
      filters = {
        "country": ["Germany", "Switzerland", "Austria", "Luxembourg"],
        "sort": ["Newest first"],
        "salary": [0, 200000],
        "discipline": ["Consulting", "Analysis and statistics"],
        "remoteOption": ["Full Remote"]
      }
    """
    logger.debug(f"[apply_filters] Применяем фильтры: {filters}")

    # 1) Tag-based categories
    tag_filter_keys = {
        "country", "city", "sort", "remoteOption",
        "employmentType", "careerLevel",
        "benefitWorkingCulture", "benefitEmployeePerk"
    }
    # 2) Checkbox-based categories
    checkbox_filter_keys = {"discipline", "industry"}

    # 3) Salary range
    salary_key = "salary"

    # For each key in the user’s config, delegate to the correct function
    for key, value in filters.items():
        if key in tag_filter_keys and isinstance(value, list):
            await apply_tag_filter(page, value)
        elif key in checkbox_filter_keys and isinstance(value, list):
            await apply_checkbox_filter(page, value)
        elif key == salary_key and isinstance(value, list) and len(value) == 2:
            min_val, max_val = value
            await apply_salary_filter(page, min_val, max_val)
        else:
            logger.debug(f"[apply_filters] Unsupported or invalid filter: '{key}' -> {value}")

    # Often, after applying filters, XING reloads or fetches new results
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except:
        logger.debug("[apply_filters] Timeout waiting for networkidle after filters.")

    logger.debug("[apply_filters] Все указанные фильтры применены.")


def append_stats(stats_csv: str, url: str, collected_count: int):
    """
    Для простого учёта сбора сохраняем в stats.csv (URL, кол-во собранных, дата).
    """
    logger.debug(f"[append_stats] Обновление статистики для URL: {url} с количеством: {collected_count}")
    if not os.path.exists(stats_csv):
        with open(stats_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["URL", "CollectedCount", "Date"])

    with open(stats_csv, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([url, collected_count, time.strftime("%Y-%m-%d")])
    logger.debug("[append_stats] Статистика записана.")


# --------------------------
# Функции для отклика (apply_to_relevant_jobs)
# --------------------------

async def apply_to_relevant_jobs(page: Page, job_listings_csv: str, email: str, password: str, min_score: float):
    """
    Открывает CSV, ищет вакансии (GPT_Score >= min_score),
    где ApplyStatus = ["","uncertain","error_easy","pending"], и пытается "Easy apply".
    В конце логирует сводку по финальным статусам и числам.
    """
    logger.debug("[apply_to_relevant_jobs] Начало процедуры отклика на вакансии.")
    scraper = XingScraper()
    if not await scraper.login(page, email, password):
        logger.error("[apply_to_relevant_jobs] Авторизация не удалась, пропускаем.")
        return

    if not os.path.exists(job_listings_csv):
        logger.warning("[apply_to_relevant_jobs] Файл вакансий не найден.")
        return

    with open(job_listings_csv, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.info("[apply_to_relevant_jobs] CSV пуст, делать нечего.")
        return

    headers = rows[0]
    data = rows[1:]

    try:
        idx_url    = headers.index("URL")
        idx_status = headers.index("ApplyStatus")
        idx_score  = headers.index("GPT_Score")
        idx_desc   = headers.index("Description")
        idx_ext    = headers.index("ExternalURL")
    except ValueError:
        logger.error("[apply_to_relevant_jobs] Не хватает нужных колонок.")
        return

    changed = False

    total_rows = len(data)
    skipped_by_status = 0
    eligible_rows = 0

    # Сбор статистики по финальным статусам
    status_counts = defaultdict(int)

    for i, row in enumerate(data):
        # Дополним пустыми, если длины не совпадают
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        url     = row[idx_url].strip()
        status  = row[idx_status].strip().lower()
        score_s = row[idx_score].strip()
        ext_url = row[idx_ext].strip()
        desc    = row[idx_desc].strip()

        # Если статус не тот — пропускаем
        if status not in ["", "uncertain", "error_easy", "pending", "error_form", "error_load"]:
            # logger.debug(f"[apply_to_relevant_jobs] Пропуск вакансии {url} с статусом: {status}")
            skipped_by_status += 1
            continue

        eligible_rows += 1
        try:
            score_val = float(score_s)
        except:
            score_val = 0.0

        if score_val < min_score:
            # Считаем нерелевантной
            row[idx_status] = "not relevant"
            data[i] = row
            changed = True
            status_counts["not relevant"] += 1
            logger.debug(f"[apply_to_relevant_jobs] Вакансия {url} признана нерелевантной (score={score_val}).")
            continue

        # Если уже ext_url есть — значит external
        if ext_url:
            row[idx_status] = "external"
            data[i] = row
            changed = True
            status_counts["external"] += 1
            logger.debug(f"[apply_to_relevant_jobs] Вакансия {url} имеет внешний URL, помечаем как external.")
            continue

        # Пытаемся открыть вакансию
        logger.info(f"[apply_to_relevant_jobs] Пробуем податься на {url}, score={score_val}")
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state("networkidle")
            await accept_cookies_if_present(page)
            await ahuman_delay(1, 2)
            logger.debug(f"[apply_to_relevant_jobs] Страница вакансии {url} успешно загружена.")
        except Exception as e:
            row[idx_status] = "error_load"
            data[i] = row
            changed = True
            status_counts["error_load"] += 1
            logger.debug(f"[apply_to_relevant_jobs] Ошибка загрузки страницы вакансии {url}: {e}")
            continue

        # Если уже "job ad isn't available" — пометим и не пытаемся кликать
        if await is_job_not_available(page):
            row[idx_status] = "not_available"
            data[i] = row
            changed = True
            status_counts["not_available"] += 1
            logger.debug(f"[apply_to_relevant_jobs] Вакансия {url} недоступна (not_available).")
            continue

        # Проверка "already applied"?
        if await is_already_applied(page):
            row[idx_status] = "done"
            data[i] = row
            changed = True
            status_counts["done"] += 1
            logger.debug(f"[apply_to_relevant_jobs] Вакансия {url} уже откликнута (done).")
            continue

        if not await click_easy_apply(page):
            logger.info("[XingScraper] No Easy Apply => 'error_easy'.")
            row[idx_status] = "error_easy"
            data[i] = row
            changed = True
            status_counts["error_easy"] += 1
            logger.debug(f"[apply_to_relevant_jobs] Кнопка Easy Apply не найдена для вакансии {url}.")
            continue

        # Если кнопка "Easy apply" нашлась, заполним форму
        final_status = await fill_easy_apply_form(page, desc, email)
        final_status = str(final_status) if final_status is not None else "unknown"
        row[idx_status] = final_status
        data[i] = row
        changed = True
        status_counts[final_status] += 1
        logger.debug(f"[apply_to_relevant_jobs] Окончательный статус вакансии {url}: {final_status}")

    # Если не было обработанных строк - логим и выходим
    if eligible_rows == 0:
        logger.info(
            "[apply_to_relevant_jobs] Не найдено ни одной вакансии со статусом "
            "'' / 'uncertain' / 'error_easy' / 'pending' для отклика. "
            f"Всего строк: {total_rows}, пропущено по статусу: {skipped_by_status}."
        )

    # Если были изменения — сохраняем CSV
    if changed:
        update_csv_file(data, job_listings_csv, headers)
        logger.info("[apply_to_relevant_jobs] CSV обновлён после откликов.")

    # --- Итоговая сводка по статусам ---
    if status_counts:
        # Сортируем по убыванию числа
        sorted_stats = sorted(status_counts.items(), key=lambda kv: kv[1], reverse=True)
        logger.info("[apply_to_relevant_jobs] Итоговая сводка по финальным статусам:")
        for st, cnt in sorted_stats:
            logger.info(f"[apply_to_relevant_jobs]   {st}: {cnt}")
    else:
        logger.info("[apply_to_relevant_jobs] Не было финальных статусов для подсчёта.")

    # Дополнительная сводка
    logger.info(f"[apply_to_relevant_jobs] Всего строк: {total_rows}; "
                f"подлежало проверке (eligible): {eligible_rows}; "
                f"пропущено по статусу (skipped_by_status): {skipped_by_status}.")

async def is_already_applied(page: Page) -> bool:
    """
    Проверяем, нет ли баннера "You applied for this job" и т.п.
    """
    logger.debug("[is_already_applied] Проверка на наличие признака ранее сделанного отклика.")
    banner = await page.query_selector("div[data-xds='ContentBanner']")
    if banner:
        text_banner = (await banner.inner_text()).lower()
        if "you applied for this job" in text_banner or "already applied" in text_banner:
            logger.debug("[is_already_applied] Обнаружен баннер, подтверждающий, что вакансия уже откликнута.")
            return True
    logger.debug("[is_already_applied] Признак отклика не обнаружен.")
    return False


async def click_easy_apply(tab: Page) -> bool:
    """
    Tries to find and click the "Easy apply" button on the new markup.
    Returns True if clicked, else False.
    """
    apply_btn = await tab.query_selector("button[data-testid='apply-button']")
    if not apply_btn:
        return False  # no such button

    # Double-check it truly says "Easy apply"
    btn_text = (await apply_btn.inner_text() or "").lower()
    if "easy apply" in btn_text:
        await move_cursor_to_element(tab, apply_btn)
        await apply_btn.click()
        await ahuman_delay(1, 2)
        return True

    return False


async def fill_easy_apply_form(page: Page, job_desc: str, email: str) -> str:
    """
    Заполнение формы отклика на /jobs/apply/...:
      1) Принимаем cookies, если есть
      2) Проверяем/заполняем email
      3) Генерируем и загружаем резюме
      4) Жмём кнопку отправки
    """
    logger.debug("[fill_easy_apply_form] Начало заполнения формы отклика.")

    # ждём появления секции "Your contact details" или поля email
    try:
        await page.wait_for_selector("input[name='email'], h2:has-text('Your contact details')", timeout=15000)
    except TimeoutError:
        logger.debug("[fill_easy_apply_form] Не дождались формы контактных данных.")
        return "error_form"

    await accept_cookies_if_present(page)

    # email
    try:
        email_input = await page.query_selector("input[name='email']")
        if email_input:
            current = (await email_input.input_value()) or ""
            if not current.strip():
                await email_input.fill(email)
                logger.debug("[fill_easy_apply_form] Поле email заполнено.")
    except Exception as e:
        logger.debug(f"[fill_easy_apply_form] Ошибка при работе с полем email: {e}")

    # phone (countryCode + phoneNumber)
    try:
        # выбираем код страны, если есть select и константа
        if XING_PHONE_COUNTRY_CODE:
            country_select = await page.query_selector("select[name='countryCode']")
            if country_select:
                await country_select.select_option(XING_PHONE_COUNTRY_CODE)
                logger.debug(
                    f"[fill_easy_apply_form] Поле countryCode установлено: {XING_PHONE_COUNTRY_CODE}"
                )

        # заполняем номер телефона, если поле есть и константа задана
        if XING_PHONE_NUMBER:
            phone_input = await page.query_selector("input[name='phoneNumber']")
            if phone_input:
                current_phone = (await phone_input.input_value()) or ""
                if not current_phone.strip():
                    await phone_input.fill(XING_PHONE_NUMBER)
                    logger.debug("[fill_easy_apply_form] Поле phoneNumber заполнено.")
    except Exception as e:
        logger.debug(f"[fill_easy_apply_form] Ошибка при работе с полем телефона: {e}")

    # Генерация PDF
    pdf_path = generate_entire_resume_pdf(
        openai_api_key=OPENAI_API_KEY,
        resume_yaml_path=RESUME_YAML_FILE,
        style_css_path=STYLES_CSS_FILE,
        job_description_text=job_desc
    )
    if not pdf_path or not os.path.exists(pdf_path):
        logger.debug("[fill_easy_apply_form] Не удалось сгенерировать PDF резюме.")
        return "error_form"
    logger.debug(f"[fill_easy_apply_form] PDF резюме сгенерировано: {pdf_path}")

    # Загрузка
    file_input = await page.query_selector(
        "input[name='fileToUpload'][type='file'], input[data-testid='upload-input-cv'][type='file']"
    )
    if not file_input:
        logger.debug("[fill_easy_apply_form] Поле загрузки файла резюме не найдено.")
        return "error_form"

    try:
        await file_input.set_input_files(pdf_path)
        await ahuman_delay(1, 2)
        logger.debug("[fill_easy_apply_form] PDF резюме загружено в форму.")
    except Exception as e:
        logger.debug(f"[fill_easy_apply_form] Ошибка при загрузке резюме: {e}")
        return "error_form"

    # ищем кнопку отправки
    submit_selectors = [
        "button[data-testid='submit-application-button']",
        "button:has-text('Submit application')",
        "button:has-text('Apply now')",
        "button:has-text('Bewerbung abschicken')",
    ]
    submit_btn = None
    for sel in submit_selectors:
        submit_btn = await page.query_selector(sel)
        if submit_btn:
            logger.debug(f"[fill_easy_apply_form] Найдена кнопка отправки по селектору: {sel}")
            break

    if not submit_btn:
        logger.debug("[fill_easy_apply_form] Кнопка 'Submit application' не найдена.")
        return "error_form"

    await move_cursor_to_element(page, submit_btn)
    await submit_btn.click()
    await ahuman_delay(3, 5)
    logger.debug("[fill_easy_apply_form] Кнопка отправки нажата.")

    # Проверяем успех
    if await check_submission_success(page):
        logger.debug("[fill_easy_apply_form] Отклик успешно отправлен.")
        return "done"
    else:
        logger.debug("[fill_easy_apply_form] Не удалось подтвердить успешную отправку отклика.")
        return "uncertain"


async def check_submission_success(page: Page) -> bool:
    """
    Проверяем, что заявка отправлена.
    """
    logger.debug("[check_submission_success] Проверка статуса отправки отклика.")
    selectors = [
        "h1:has-text('Application submitted')",
        "h1:has-text('Thank you for your application')",
        "h2:has-text('Application submitted')",
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            logger.debug(f"[check_submission_success] Найдён заголовок успешной отправки по селектору: {sel}")
            return True
    logger.debug("[check_submission_success] Признаков успешной отправки не найдено.")
    return False
