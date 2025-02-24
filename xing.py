# --- Начало файла: scrapers/xing.py ---
import csv
import logging
import os
import pickle
import random
import time

from langdetect import detect, LangDetectException
from playwright.sync_api import Page, TimeoutError

from config import (
    XING_COOKIES_FILE,
    CSV_HEADERS,
    MAX_SCROLLS,
    MAX_JOBS_COLLECTED,
    GPT_SCORE
)
from scrapers.utils import (
    human_delay,
    move_cursor_to_element,
    update_csv_file
)


def login(page: Page, email, password) -> None:
    """
    Авторизация на xing.com
    """
    logging.info("[xing] Проверка авторизации...")
    try:
        page.goto("https://www.xing.com/")
        page.wait_for_load_state("networkidle")
        human_delay(1, 2)
    except Exception as e:
        logging.warning(f"[xing] Ошибка при переходе на xing.com: {e}")

    if _is_logged_in(page):
        logging.info("[xing] Уже авторизованы (текущий сеанс).")
        return

    _load_cookies(page)

    if _is_logged_in(page):
        logging.info("[xing] Авторизованы по кукам.")
        return

    # Пытаемся свежий логин
    if os.path.exists(XING_COOKIES_FILE):
        try:
            os.remove(XING_COOKIES_FILE)
        except:
            pass

    logging.info("[xing] Пытаемся свежую авторизацию...")
    try:
        page.goto("https://login.xing.com/")
        page.wait_for_load_state("networkidle")
        human_delay(1, 2)

        # Поле email
        page.fill("#username", email)
        human_delay(1, 2)
        # Поле password
        page.fill("#password", password)
        human_delay(1, 2)

        btn_login = page.query_selector("button:has-text('Log in')")
        if btn_login:
            move_cursor_to_element(page, btn_login)
            btn_login.click()
        else:
            logging.warning("[xing] Кнопка 'Log in' не найдена.")

        human_delay(3, 5)
        page.wait_for_load_state("networkidle")

        if _is_logged_in(page):
            # Сохраняем куки
            cookies = page.context.cookies()
            with open(XING_COOKIES_FILE, "wb") as f:
                pickle.dump(cookies, f)
            logging.info("[xing] Авторизация успешна, куки сохранены.")
        else:
            logging.error("[xing] Не удалось авторизоваться свежим логином.")
    except Exception as e:
        logging.error(f"[xing] Ошибка при авторизации: {e}")


def _load_cookies(page: Page):
    if os.path.exists(XING_COOKIES_FILE):
        logging.info("[xing] Загружаем куки из файла.")
        with open(XING_COOKIES_FILE, "rb") as f:
            cookies = pickle.load(f)
        page.context.add_cookies(cookies)
        try:
            page.goto("https://www.xing.com/")
            page.wait_for_load_state("networkidle")
            logging.info("[xing] Куки подхвачены.")
        except Exception as e:
            logging.warning(f"[xing] Ошибка после добавления куки: {e}")


def _is_logged_in(page: Page) -> bool:
    """
    Смотрим, есть ли элементы, доступные только залогиненному пользователю.
    """
    try:
        # Несколько вариантов проверки
        if page.query_selector("img[data-testid='header-profile-logo']"):
            return True
        if page.query_selector("a[data-testid='layout-me']"):
            return True
    except:
        pass
    return False


def start_scraping_process(job_listings_file_path: str,
                           stats_file_path: str,
                           urls: list,
                           page: Page,
                           email: str,
                           password: str,
                           allowed_langs=None) -> None:
    """
    1) Логин
    2) Сбор вакансий по списку ссылок
    """
    # Если CSV не существует — создадим заголовки
    if not os.path.exists(job_listings_file_path):
        with open(job_listings_file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
        logging.info(f"[xing] Создан пустой файл {job_listings_file_path} с заголовками.")

    _initialize_stats_file(stats_file_path)

    login(page, email, password)

    for url in urls:
        logging.info(f"[xing] Переходим к поиску: {url}")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        total_collected = _scroll_and_collect(
            page=page,
            file_path=job_listings_file_path,
            max_scrolls=MAX_SCROLLS,
            allowed_langs=allowed_langs
        )
        logging.info(f"[xing] Собрано {total_collected} новых вакансий с {url}")
        _append_stats(stats_file_path, url, total_collected)


def _scroll_and_collect(page: Page,
                        file_path: str,
                        max_scrolls: int = 40,
                        allowed_langs=None) -> int:
    """
    Прокручивает страницу, собирает вакансии, открывает в новой вкладке,
    проверяет язык, определяет ApplyStatus и т.д.
    """

    existing_urls = set()
    with open(file_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        for row in reader:
            if row:
                existing_urls.add(row[0].strip())

    existing_external_links = set()
    total_urls_collected = 0
    scroll_count = 0
    unchanged_scrolls = 0
    last_total = 0

    urls_buffer = []
    mode = 'a'

    while scroll_count < max_scrolls:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(random.randint(4, 6))

        # Клик "Show more"
        show_more_button = page.query_selector("button:has-text('Show more')")
        if show_more_button:
            logging.info("[xing] 'Show more' clicked.")
            move_cursor_to_element(page, show_more_button)
            show_more_button.click()
            time.sleep(random.uniform(2, 3))

        job_cards = page.query_selector_all("article.result__Item-sc-3632ed31-0")
        if not job_cards:
            logging.info("[xing] Нет карточек вакансий, прерываем.")
            break

        new_added = 0

        for card in job_cards:
            link_el = card.query_selector('a[data-testid="job-search-result"]')
            if not link_el:
                continue
            job_url = link_el.get_attribute("href")
            if not job_url:
                continue

            # Полная ссылка
            if job_url.startswith("/jobs/"):
                full_url = "https://www.xing.com" + job_url
            else:
                full_url = job_url.strip()

            if full_url in existing_urls:
                continue  # уже есть

            apply_status, external_url, description = _inspect_job_in_new_tab(
                page, full_url, existing_external_links, allowed_langs
            )

            existing_urls.add(full_url)
            row = [
                full_url,
                apply_status,
                external_url,
                description,
                "",
                "",
                time.strftime("%Y-%m-%d")
            ]
            urls_buffer.append(row)
            new_added += 1
            total_urls_collected += 1

            if total_urls_collected >= MAX_JOBS_COLLECTED:
                logging.info(f"[xing] Достигнут лимит {MAX_JOBS_COLLECTED}")
                break

        # Сохраняем каждые ~5
        if new_added > 0 and len(urls_buffer) >= 5:
            with open(file_path, mode, newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(urls_buffer)
            urls_buffer.clear()

        if total_urls_collected >= MAX_JOBS_COLLECTED:
            break

        # Проверка, увеличилось ли
        if total_urls_collected == last_total:
            unchanged_scrolls += 1
        else:
            unchanged_scrolls = 0

        if unchanged_scrolls >= 5:
            logging.info("[xing] 5 итераций без новых вакансий — выходим.")
            break

        last_total = total_urls_collected
        scroll_count += 1

    # Допишем остатки
    if urls_buffer:
        with open(file_path, mode, newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(urls_buffer)
        urls_buffer.clear()

    return total_urls_collected


def _inspect_job_in_new_tab(page: Page,
                            job_url: str,
                            existing_external_links: set,
                            allowed_langs=None) -> tuple:
    """
    Открывает вакансию в новой вкладке, проверяет язык, ищет Easy Apply / External / Chat,
    возвращает (apply_status, external_url, description).
    Если язык не подходит, ставим apply_status='not relevant (lang=...)', description=''
    """

    apply_status = ""
    external_url = ""
    description = ""

    try:
        with page.context.expect_page() as new_page_info:
            page.evaluate("url => window.open(url, '_blank')", job_url)
        new_tab = new_page_info.value

        # даём 30 секунд на загрузку
        new_tab.wait_for_load_state("networkidle", timeout=30000)

        # Сначала извлекаем описание (или пустое)
        description = _extract_job_description(new_tab)
        # Если нужно проверить язык
        if allowed_langs:
            # пытемся определить
            if description:
                try:
                    detected_lang = detect(description).lower()
                    if detected_lang not in allowed_langs:
                        logging.info(f"[xing] Вакансия {job_url} пропущена (lang={detected_lang}).")
                        apply_status = f"not relevant (lang={detected_lang})"
                        description = ""
                        new_tab.close()
                        return apply_status, external_url, description
                except LangDetectException:
                    logging.info(f"[xing] Вакансия {job_url} пропущена (ошибка определения языка).")
                    apply_status = "not relevant (lang err)"
                    description = ""
                    new_tab.close()
                    return apply_status, external_url, description

        # Ищем Easy apply (приоритет)
        if _has_easy_apply_button(new_tab):
            apply_status = ""
        else:
            # Если нет easy apply, проверяем External
            ext_link = _find_employer_website(new_tab)
            if ext_link:
                if ext_link in existing_external_links:
                    apply_status = "duplicate"
                else:
                    existing_external_links.add(ext_link)
                    apply_status = "external"
                external_url = ext_link
                description = ""
            else:
                # Chat?
                if _try_selector(new_tab, "button[data-testid='applyAction']", 3000):
                    apply_status = "chat"
                else:
                    apply_status = "error_easy"

        new_tab.close()
    except TimeoutError:
        logging.warning(f"[xing] Не удалось открыть {job_url}: превышен таймаут 30000мс.")
        apply_status = "timeout"
    except Exception as e:
        logging.warning(f"[xing] Не удалось открыть {job_url}: {e}")
        apply_status = "error_load"

    return apply_status, external_url, description


def _extract_job_description(tab: Page) -> str:
    """
    Пробует вытянуть текст описания.
    """
    # Иногда есть кнопка "Show more"
    try:
        more_btn = tab.query_selector("button[data-xds='TextButton']")
        if more_btn and "show more" in more_btn.inner_text().strip().lower():
            move_cursor_to_element(tab, more_btn)
            more_btn.click()
            time.sleep(1)
    except:
        pass

    # сам текст
    try:
        desc_elem = tab.query_selector("div[class^='description-module__DescriptionWrapper']")
        if desc_elem:
            return desc_elem.inner_text().strip()
    except:
        pass
    return ""


def _has_easy_apply_button(tab: Page) -> bool:
    """
    Ищем кнопку "Easy apply".
    Пример HTML:
    <span class="button-styles__Text-sc-c68c3d6-5 pPodO">Easy apply</span>
    """
    # 1) Сразу ищем span с текстом "Easy apply"
    #    или button:has-text("Easy apply")
    # 2) Если нашли - значит Easy apply есть
    try:
        # Небольшое усложнение: "button:has-text('Easy apply')"
        # Иногда текст хранится в <span>. Лучше поищем любые варианты:
        easy_button = tab.query_selector("button:has-text('Easy apply')")
        if easy_button:
            return True
        # Альтернативный способ:
        span_el = tab.query_selector("span.button-styles__Text-sc-c68c3d6-5:has-text('Easy apply')")
        if span_el:
            return True
    except:
        pass
    return False


def _find_employer_website(tab: Page) -> str:
    """
    Ищем "Visit employer website". Если находим - открываем, берём url, закрываем.
    """
    try:
        # Селектор button[data-testid='apply-button']
        button = tab.query_selector("button[data-testid='apply-button']")
        if button:
            text_btn = (button.inner_text() or "").lower()
            if "visit employer website" in text_btn:
                with tab.context.expect_page() as new_page_info:
                    button.click()
                new_page = new_page_info.value
                new_page.wait_for_load_state()
                ret_url = new_page.url
                new_page.close()
                return ret_url
        # Либо a[data-testid='applyAction']
        link_els = tab.query_selector_all("a[data-testid='applyAction']")
        for link in link_els:
            href = link.get_attribute("href")
            if href:
                return href
    except:
        pass
    return ""


def _try_selector(tab: Page, selector: str, timeout: int = 3000) -> bool:
    try:
        el = tab.wait_for_selector(selector, timeout=timeout)
        return el is not None
    except:
        return False


def _initialize_stats_file(stats_file_path: str) -> None:
    if not os.path.exists(stats_file_path):
        with open(stats_file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["URL", "Collected Jobs Count", "Date"])


def _append_stats(stats_file_path: str, url: str, total_collected: int) -> None:
    with open(stats_file_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([url, total_collected, time.strftime("%Y-%m-%d")])


# ------------------- APPLY LOGIC -------------------
def visit_and_apply(file_path: str,
                    page: Page,
                    email: str,
                    password: str) -> None:
    """
    Открывает вакансии из CSV, если GPT_Score >= GPT_SCORE и ApplyStatus in ["", "uncertain", "error_easy"],
    пытается нажать Easy apply, залить резюме и податься.
    """
    # Гарантируем логин
    login(page, email, password)

    if not os.path.exists(file_path):
        logging.warning(f"[visit_and_apply] Файл {file_path} не найден.")
        return

    with open(file_path, 'r', newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    if not rows or len(rows) < 2:
        logging.info("[visit_and_apply] CSV пуст, нечего обрабатывать.")
        return

    headers = rows[0]
    data = rows[1:]

    try:
        idx_url = headers.index("URL")
        idx_status = headers.index("ApplyStatus")
        idx_score = headers.index("GPT_Score")
        idx_exturl = headers.index("ExternalURL")
        idx_desc = headers.index("Description")
    except ValueError:
        logging.error("[visit_and_apply] Не найдены нужные колонки.")
        return

    processed_count = 0
    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        job_url = row[idx_url].strip()
        apply_status = row[idx_status].strip().lower()
        gpt_score_str = row[idx_score].strip()
        external_url = row[idx_exturl].strip()
        job_desc = row[idx_desc].strip()

        if apply_status not in ["", "uncertain", "error_easy"]:
            continue

        processed_count += 1
        try:
            gpt_score = float(gpt_score_str)
        except:
            gpt_score = 0.0

        if gpt_score < GPT_SCORE:
            row[idx_status] = "not relevant"
            data[i] = row
            logging.info(f"[visit_and_apply] Вакансия {job_url} отклонена (GPT_Score < {GPT_SCORE}).")
            if i % 5 == 0:
                update_csv_file(data, file_path, headers)
            continue

        # Переходим
        logging.info(f"[visit_and_apply] Отклик на вакансию: {job_url}")
        try:
            page.goto(job_url, timeout=30000)
            page.wait_for_load_state("networkidle")
            time.sleep(2)
        except TimeoutError:
            logging.warning(f"[visit_and_apply] Не удалось загрузить {job_url} (таймаут).")
            row[idx_status] = "timeout"
            data[i] = row
            if i % 5 == 0:
                update_csv_file(data, file_path, headers)
            continue
        except Exception as e:
            logging.warning(f"[visit_and_apply] Ошибка при открытии {job_url}: {e}")
            row[idx_status] = "error_load"
            data[i] = row
            if i % 5 == 0:
                update_csv_file(data, file_path, headers)
            continue

        # Если external
        if "external" in apply_status or external_url:
            logging.info("[visit_and_apply] У вакансии статус external, пропускаем.")
            row[idx_status] = "external"
            data[i] = row
            continue

        # Если уже подано
        if _has_already_applied(page):
            row[idx_status] = "done"
            data[i] = row
            if i % 5 == 0:
                update_csv_file(data, file_path, headers)
            continue

        # Попытка нажать Easy apply
        if not _click_easy_apply(page):
            logging.info(f"[visit_and_apply] Не нашли Easy apply у {job_url}.")
            row[idx_status] = "error_easy"
            data[i] = row
            if i % 5 == 0:
                update_csv_file(data, file_path, headers)
            continue

        # Заполнить форму + загрузить резюме
        result = _fill_application_form(page, job_desc)
        row[idx_status] = result
        data[i] = row

        if i % 5 == 0:
            update_csv_file(data, file_path, headers)

    update_csv_file(data, file_path, headers)
    logging.info(f"[visit_and_apply] Завершена обработка {processed_count} вакансий.")


def _has_already_applied(page: Page) -> bool:
    """
    Если на странице "You applied for this job" и т.п.
    """
    banner = page.query_selector("div[data-xds='ContentBanner']")
    if banner and "You applied for this job" in banner.inner_text():
        return True
    return False


def _click_easy_apply(page: Page) -> bool:
    """
    Ищем кнопку Easy apply, кликаем.
    """
    try:
        # Ищем текст "Easy apply"
        btn = page.query_selector("button:has-text('Easy apply')")
        if btn:
            move_cursor_to_element(page, btn)
            btn.click()
            time.sleep(1)
            return True
        return False
    except Exception as e:
        logging.debug(f"[visit_and_apply] Ошибка при клике Easy apply: {e}")
        return False


def _fill_application_form(page: Page, job_desc: str) -> str:
    """
    Нажимает "Edit your application", загружает PDF, сабмитит.
    """
    from config import OPENAI_API_KEY
    from scrapers.gpt_resume_builder import generate_entire_resume_pdf, _build_pdf_filename
    from scrapers.utils import load_resume_data
    import shutil

    # Кнопка Edit your application
    try:
        edit_btn = page.wait_for_selector("button:has-text('Edit your application')", timeout=10000)
        if not edit_btn:
            logging.warning("[visit_and_apply] Не найдена кнопка Edit your application.")
            return "error_form"
        move_cursor_to_element(page, edit_btn)
        edit_btn.click()
        time.sleep(2)
    except:
        return "error_form"

    # Генерируем резюме
    resume_data = load_resume_data("resume.yaml")
    pdf_long = generate_entire_resume_pdf(
        openai_api_key=OPENAI_API_KEY,
        resume_yaml_path="resume.yaml",
        style_css_path="styles.css",
        job_description_text=job_desc
    )
    logging.info(f"[visit_and_apply] Сгенерированное резюме: {pdf_long}")

    folder = os.path.dirname(pdf_long)
    candidate_first = resume_data.get("personal_information", {}).get("name", "Candidate")
    candidate_last = resume_data.get("personal_information", {}).get("surname", "Unknown")

    short_pdf = _build_pdf_filename(
        folder_path=folder,
        candidate_first_name=candidate_first,
        candidate_last_name=candidate_last,
        timestamp="",
        suffix="resume"
    )
    shutil.copy2(pdf_long, short_pdf)

    # Загружаем PDF
    try:
        file_input = page.query_selector("input[name='fileToUpload']")
        if not file_input:
            logging.warning("[visit_and_apply] Не нашли input[name='fileToUpload'].")
            return "error_form"
        file_input.set_input_files(short_pdf)
        logging.info("[visit_and_apply] Резюме загружено.")
        time.sleep(2)
    except Exception as e:
        logging.warning(f"[visit_and_apply] Ошибка при загрузке резюме: {e}")
        return "error_form"

    # Сабмит
    submit_btn = page.query_selector("button:has-text('Submit application')")
    if not submit_btn:
        logging.warning("[visit_and_apply] Кнопка 'Submit application' не найдена.")
        return "error_form"
    move_cursor_to_element(page, submit_btn)
    submit_btn.click()
    time.sleep(3)

    # Проверяем подтверждение
    if _check_submission_confirmation(page):
        return "done"
    else:
        return "uncertain"


def _check_submission_confirmation(page: Page) -> bool:
    """
    Пробуем найти "Application submitted" + иконку.
    """
    try:
        # ждём либо <h1>Application submitted</h1>, либо SpotCheck/SpotConfetti
        page.wait_for_selector("xpath=//h1[contains(text(), 'Application submitted')]", timeout=8000)
        return True
    except:
        pass
    return False
# --- Конец файла: scrapers/xing.py ---
