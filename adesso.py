# --- Начало файла: scrapers/adesso.py ---
import csv
import os
import time
import random
import logging
import shutil

from langdetect import detect
from bs4 import BeautifulSoup

from config import (
    OPENAI_API_KEY,
    resume_data,
    file_path
)
from scrapers.utils import (
    update_csv_file,
    random_mouse_movements,
    load_resume_data
)
from scrapers.gpt_resume_builder import generate_entire_resume_pdf, _build_pdf_filename


def accept_cookies_adesso(page) -> None:
    """
    Принимает куки на adesso-site, если возможно.
    """
    try:
        cookie_accept_btn = page.query_selector("#cookie-accept")
        if cookie_accept_btn:
            cookie_accept_btn.click()
            time.sleep(1)
            logging.info("[adesso] Cookies accepted.")
        else:
            logging.info("[adesso] Cookie banner не найден.")
    except Exception as e:
        logging.warning(f"[adesso] Ошибка при принятии куки: {e}")


def check_language(page, languages):
    """
    Проверяет язык текста (itemprop='description'). Если указано 'lang' - берём его,
    иначе пробуем detect().
    Возвращает True/False.
    """
    if isinstance(languages, str):
        languages = [lang.strip().lower() for lang in languages.split(',')]
    else:
        languages = [lang.lower() for lang in languages]

    try:
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        description_elem = soup.find(attrs={"itemprop": "description"})
        if not description_elem:
            return False

        candidate_lang = None
        if description_elem.has_attr("lang"):
            candidate_lang = description_elem.get("lang").split('-')[0].lower()
        elif description_elem.has_attr("xml:lang"):
            candidate_lang = description_elem.get("xml:lang").split('-')[0].lower()
        else:
            text = description_elem.get_text(separator=" ", strip=True)
            if text:
                candidate_lang = detect(text).lower()
            else:
                return False

        return candidate_lang in languages

    except Exception:
        return False


def open_job_adesso(page, job_url, languages):
    logging.info(f"[adesso] Открываем вакансию: {job_url}")
    page.goto(job_url)
    time.sleep(random.uniform(2, 4))
    accept_cookies_adesso(page)

    if not check_language(page, languages):
        logging.info("[adesso] Язык не подходит, пропускаем.")
        return False

    return True


def click_apply_button_adesso(page):
    """
    Ищет элемент adesso-apply-button и кликает.
    """
    try:
        apply_btn = page.query_selector("adesso-apply-button")
        if apply_btn:
            with page.expect_navigation(timeout=10000):
                apply_btn.click()
            logging.info("[adesso] Нажата кнопка 'Jetzt bewerben'.")
            return True
        else:
            logging.info("[adesso] Кнопка 'Jetzt bewerben' не найдена.")
            return False
    except Exception as e:
        logging.info(f"[adesso] Не удалось кликнуть 'Jetzt bewerben': {e}")
        return False


def wait_for_form_adesso(page):
    """
    Ждём появления #apply-data (форма).
    """
    try:
        page.wait_for_selector("#apply-data", timeout=10000)
        logging.info("[adesso] Форма заявки прогрузилась.")
        return True
    except:
        logging.info("[adesso] Форма не прогрузилась, попробуем reload.")
        page.reload()
        try:
            page.wait_for_selector("#apply-data", timeout=10000)
            logging.info("[adesso] Форма найдена после reload.")
            return True
        except:
            logging.info("[adesso] Форма так и не найдена.")
            return False


def fill_personal_data_adesso(page, resume_data):
    """
    Заполняет поля формы (salutation, Vorname, Nachname, E-Mail, etc.)
    """
    personal_info = resume_data.get("personal_information", {})

    salutation_map = {
        "male": "Herr",
        "female": "Frau",
        "divers": "Divers"
    }
    user_gender = personal_info.get("gender", "").lower()
    salutation_value = salutation_map.get(user_gender, "")

    if salutation_value:
        try:
            page.select_option("select#custSalutation", label=salutation_value)
        except:
            pass

    # Vorname
    first_name = personal_info.get("name", "")
    try:
        page.fill("#field-firstName", first_name)
    except:
        pass

    # Nachname
    last_name = personal_info.get("surname", "")
    try:
        page.fill("#field-lastName", last_name)
    except:
        pass

    # Email
    email = personal_info.get("email", "")
    try:
        page.fill("#field-contactEmail", email)
    except:
        pass

    # Telefon
    phone = personal_info.get("phone", "")
    try:
        page.fill("#field-cellPhone", phone)
    except:
        pass

    # Straße
    address = personal_info.get("address", "")
    try:
        page.fill("#field-address", address)
    except:
        pass

    # PLZ
    zip_code = personal_info.get("zip", "")
    try:
        page.fill("#field-zip", zip_code)
    except:
        pass

    # Ort
    city = personal_info.get("city", "")
    try:
        page.fill("#field-city", city)
    except:
        pass

    # Land
    country = personal_info.get("country", "")
    if country:
        try:
            page.select_option("select#country", label=country)
        except:
            pass

    # Deutschkenntnisse
    user_de = personal_info.get("german_level", "")
    if user_de:
        try:
            page.select_option("select#question-1", label=user_de)
        except:
            pass


def upload_resume_adesso(page, pdf_path):
    """
    Загружает резюме в поле input[type='file'] (name='resume').
    """
    try:
        resume_file_input = page.query_selector("csb-upload[name='resume'] input[type='file']")
        if resume_file_input:
            resume_file_input.set_input_files(pdf_path)
            logging.info("[adesso] CV uploaded.")
        else:
            # shadow DOM?
            resume_file_input = page.query_selector("csb-upload[name='resume'] >>> input[type='file']")
            if resume_file_input:
                resume_file_input.set_input_files(pdf_path)
                logging.info("[adesso] CV uploaded (shadow).")
            else:
                logging.info("[adesso] Не нашли input[type=file] для резюме.")
    except Exception as e:
        logging.info(f"[adesso] Ошибка при загрузке резюме: {e}")


def accept_privacy_adesso(page):
    """
    Ставим чекбокс #field-privacy
    """
    try:
        privacy_checkbox = page.query_selector("#field-privacy")
        if privacy_checkbox:
            privacy_checkbox.click()
            time.sleep(1)
            logging.info("[adesso] Datenschutz akzeptiert.")
    except Exception as e:
        logging.info(f"[adesso] Ошибка при клике на Datenschutz: {e}")


def submit_application_adesso(page):
    """
    Кликаем "Bewerbung absenden".
    """
    try:
        apply_btn = page.query_selector("button:has-text('Bewerbung absenden')")
        if apply_btn:
            apply_btn.click()
            logging.info("[adesso] Bewerbung absenden clicked.")
            return True
        logging.info("[adesso] Кнопка 'Bewerbung absenden' не найдена.")
        return False
    except Exception as e:
        logging.info(f"[adesso] Ошибка при сабмите: {e}")
        return False


def check_submission_success_adesso(page):
    """
    Проверяем наличие чего-то вроде adesso-loading/loading-text='erfolgreich'
    """
    try:
        page.wait_for_selector("adesso-loading[loading-text*='erfolgreich']", timeout=8000)
        logging.info("[adesso] Bewerbungsformular => Success screen.")
        return True
    except:
        return False


def apply_for_adesso_job(page, job_url, job_title, company, resume_data, job_desc=""):
    """
    Основная функция:
     1) Открывает вакансию
     2) Нажимает 'Jetzt bewerben'
     3) Заполняет форму
     4) Заливает PDF
     5) Отправляет
    """
    # Нужно понять, на каких языках согласны подавать (вытащим из resume_data)
    language_list = resume_data.get("languages", [])
    languages = [lang.get("short_name", "").strip().lower() for lang in language_list if "short_name" in lang]

    if not open_job_adesso(page, job_url, languages):
        return "lang_skip"

    if not click_apply_button_adesso(page):
        return "no_apply_button"

    if not wait_for_form_adesso(page):
        return "error_form_not_found"

    # Генерация резюме
    pdf_path_long = generate_entire_resume_pdf(
        openai_api_key=OPENAI_API_KEY,
        resume_yaml_path="resume.yaml",
        style_css_path="styles.css",
        job_description_text=job_desc
    )
    logging.info(f"[adesso] Long PDF: {pdf_path_long}")

    folder = os.path.dirname(pdf_path_long)
    candidate_first = resume_data.get("personal_information", {}).get("name", "")
    candidate_last = resume_data.get("personal_information", {}).get("surname", "")
    combined = f"{company}_{job_title}".strip()
    pdf_path_short = _build_pdf_filename(folder_path=folder,
                                         candidate_first_name=candidate_first,
                                         candidate_last_name=combined,
                                         timestamp="",
                                         suffix="resume")
    shutil.copy2(pdf_path_long, pdf_path_short)
    logging.info(f"[adesso] Short PDF: {pdf_path_short}")

    fill_personal_data_adesso(page, resume_data)
    upload_resume_adesso(page, pdf_path_short)
    accept_privacy_adesso(page)

    if not submit_application_adesso(page):
        return "submit_not_found"

    if check_submission_success_adesso(page):
        return "done"
    else:
        return "uncertain"


def process_adesso_links_in_file(page, file_path, resume_data):
    """
    Ищет в CSV строки, где ExternalURL содержит 'adesso-group.com' и ApplyStatus='external',
    затем вызывает apply_for_adesso_job. Обновляет CSV.
    """
    if not os.path.exists(file_path):
        logging.error(f"[adesso] Файл {file_path} не найден.")
        return

    with open(file_path, 'r', newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    if not rows:
        logging.warning(f"[adesso] {file_path} пуст?")
        return

    headers = rows[0]
    data = rows[1:]

    try:
        idx_url = headers.index("URL")
        idx_status = headers.index("ApplyStatus")
        idx_exturl = headers.index("ExternalURL")
    except ValueError:
        logging.error("[adesso] Нет нужных колонок: URL/ApplyStatus/ExternalURL.")
        return

    processed_urls = set()

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        apply_status = (row[idx_status] or "").strip().lower()
        ext_url = (row[idx_exturl] or "").strip()

        if not ext_url:
            continue

        if apply_status == "external" and "adesso-group.com" in ext_url:
            if ext_url in processed_urls:
                row[idx_status] = "duplicate"
                data[i] = row
                continue

            processed_urls.add(ext_url)
            job_title = "Data Engineer"
            company = "adesso"
            job_desc = ""

            result = apply_for_adesso_job(page, ext_url, job_title, company, resume_data, job_desc)
            row[idx_status] = result
            data[i] = row

        if i % 10 == 0:
            _save_csv_immediate(file_path, headers, data)

    _save_csv_immediate(file_path, headers, data)


def _save_csv_immediate(file_path, headers, data):
    with open(file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)
    logging.info(f"[adesso] CSV {file_path} обновлен.")
# --- Конец файла: scrapers/adesso.py ---
