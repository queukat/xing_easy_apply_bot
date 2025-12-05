# --- The beginning of the file: scraping/adesso.py ---
import csv
import os
import shutil
import asyncio

from langdetect import detect
from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError

from core.config import init_browser
from core.constants import OPENAI_API_KEY, RESUME_YAML_FILE, STYLES_CSS_FILE
from core.logger import logger
from services.gpt.gpt_resume_builder import (
    generate_entire_resume_pdf,
    _build_pdf_filename,
)
from services.scraping.utils import load_resume_data, ahuman_delay

JOB_LISTINGS_FILE_PATH_ADESSO = "../job_listings.csv"


async def accept_cookies_adesso(page: Page) -> None:
    """Accept cookies on Adesso site, if banner is present."""
    try:
        cookie_accept_btn = await page.query_selector("#cookie-accept")
        if cookie_accept_btn:
            await cookie_accept_btn.click()
            await ahuman_delay(1, 2)
            logger.info("[Adesso] Cookies accepted.")
        else:
            logger.info("[Adesso] Cookie banner not found.")
    except Exception as e:
        logger.warning(f"[Adesso] Error when accepting cookies: {e}")


async def check_language(page: Page, languages) -> bool:
    """
    Check language of the description (itemprop='description').
    If lang attribute exists, use it; otherwise try langdetect.
    Return True/False.
    """
    if isinstance(languages, str):
        languages = [lang.strip().lower() for lang in languages.split(",")]
    else:
        languages = [lang.lower() for lang in languages]

    try:
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        description_elem = soup.find(attrs={"itemprop": "description"})
        if not description_elem:
            return False

        candidate_lang = None
        if description_elem.has_attr("lang"):
            candidate_lang = description_elem.get("lang").split("-")[0].lower()
        elif description_elem.has_attr("xml:lang"):
            candidate_lang = description_elem.get("xml:lang").split("-")[0].lower()
        else:
            text = description_elem.get_text(separator=" ", strip=True)
            if text:
                candidate_lang = detect(text).lower()
            else:
                return False

        return candidate_lang in languages

    except Exception:
        return False


async def open_job_adesso(page: Page, job_url: str, languages) -> bool:
    logger.info(f"[Adesso] Open vacancy: {job_url}")
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
    except TimeoutError:
        logger.warning(f"[Adesso] Timeout while loading {job_url}")
        return False

    await ahuman_delay(2, 4)
    await accept_cookies_adesso(page)

    if not await check_language(page, languages):
        logger.info("[Adesso] Language is not suitable, skipping.")
        return False

    return True


async def click_apply_button_adesso(page: Page) -> bool:
    """Look for <adesso-apply-button> element and click it."""
    try:
        apply_btn = await page.query_selector("adesso-apply-button")
        if apply_btn:
            try:
                async with page.expect_navigation(timeout=10000):
                    await apply_btn.click()
            except TimeoutError:
                # Иногда форма может открываться без полноценной навигации
                logger.warning("[Adesso] Navigation timeout after clicking apply button.")
            logger.info("[Adesso] Clicked 'Jetzt bewerben'.")
            await ahuman_delay(2, 3)
            return True
        else:
            logger.info("[Adesso] Button 'Jetzt bewerben' not found.")
            return False
    except Exception as e:
        logger.info(f"[Adesso] Failed to click 'Jetzt bewerben': {e}")
        return False


async def wait_for_form_adesso(page: Page) -> bool:
    """Wait for the appearance of #apply-data form."""
    try:
        await page.wait_for_selector("#apply-data", timeout=10000)
        logger.info("[Adesso] Application form loaded.")
        return True
    except TimeoutError:
        logger.info("[Adesso] Form not loaded, trying reload.")
        try:
            await page.reload()
            await ahuman_delay(2, 3)
            await page.wait_for_selector("#apply-data", timeout=10000)
            logger.info("[Adesso] Form found after reload.")
            return True
        except TimeoutError:
            logger.info("[Adesso] Form was never found.")
            return False


async def fill_personal_data_adesso(page: Page, resume_data: dict) -> None:
    """Fill personal data fields (salutation, name, email, phone, address, etc.)."""
    personal_info = resume_data.get("personal_information", {}) or {}

    salutation_map = {
        "male": "Herr",
        "female": "Frau",
        "divers": "Divers",
    }
    user_gender = (personal_info.get("gender") or "").lower()
    salutation_value = salutation_map.get(user_gender, "")

    if salutation_value:
        try:
            await page.select_option("select#custSalutation", label=salutation_value)
        except Exception:
            pass

    # Vorname
    first_name = personal_info.get("name", "") or ""
    try:
        await page.fill("#field-firstName", first_name)
    except Exception:
        pass

    # Nachname
    last_name = personal_info.get("surname", "") or ""
    try:
        await page.fill("#field-lastName", last_name)
    except Exception:
        pass

    # Email
    email = personal_info.get("email", "") or ""
    try:
        await page.fill("#field-contactEmail", email)
    except Exception:
        pass

    # Telefon
    phone = personal_info.get("phone", "") or ""
    try:
        await page.fill("#field-cellPhone", phone)
    except Exception:
        pass

    # Straße
    address = personal_info.get("address", "") or ""
    try:
        await page.fill("#field-address", address)
    except Exception:
        pass

    # PLZ
    zip_code = personal_info.get("zip", "") or ""
    try:
        await page.fill("#field-zip", zip_code)
    except Exception:
        pass

    # ORT
    city = personal_info.get("city", "") or ""
    try:
        await page.fill("#field-city", city)
    except Exception:
        pass

    # Land
    country = personal_info.get("country", "") or ""
    if country:
        try:
            await page.select_option("select#country", label=country)
        except Exception:
            pass

    # Deutschkenntnisse (if configured in resume.yaml)
    user_de = personal_info.get("german_level", "") or ""
    if user_de:
        try:
            await page.select_option("select#question-1", label=user_de)
        except Exception:
            pass


async def upload_resume_adesso(page: Page, pdf_path: str) -> None:
    """Upload resume into csb-upload[name='resume'] <input type='file'>."""
    try:
        resume_file_input = await page.query_selector(
            "csb-upload[name='resume'] input[type='file']"
        )
        if resume_file_input:
            await resume_file_input.set_input_files(pdf_path)
            logger.info("[Adesso] CV uploaded.")
            return

        # Shadow DOM fallback
        resume_file_input = await page.query_selector(
            "csb-upload[name='resume'] >>> input[type='file']"
        )
        if resume_file_input:
            await resume_file_input.set_input_files(pdf_path)
            logger.info("[Adesso] CV uploaded (shadow).")
        else:
            logger.info("[Adesso] Did not find input[type=file] for resume.")
    except Exception as e:
        logger.info(f"[Adesso] Error when uploading resume: {e}")


async def accept_privacy_adesso(page: Page) -> None:
    """Tick #field-privacy checkbox."""
    try:
        privacy_checkbox = await page.query_selector("#field-privacy")
        if privacy_checkbox:
            await privacy_checkbox.click()
            await ahuman_delay(1, 2)
            logger.info("[Adesso] Datenschutz accepted.")
    except Exception as e:
        logger.info(f"[Adesso] Error when clicking Datenschutz: {e}")


async def submit_application_adesso(page: Page) -> bool:
    """Click 'Bewerbung absenden' button."""
    try:
        apply_btn = await page.query_selector("button:has-text('Bewerbung absenden')")
        if apply_btn:
            await apply_btn.click()
            await ahuman_delay(2, 3)
            logger.info("[Adesso] 'Bewerbung absenden' clicked.")
            return True
        logger.info("[Adesso] Button 'Bewerbung absenden' not found.")
        return False
    except Exception as e:
        logger.info(f"[Adesso] Error in submit: {e}")
        return False


async def check_submission_success_adesso(page: Page) -> bool:
    """
    Check for success indicator such as:
    <adesso-loading loading-text*='erfolgreich'>
    """
    try:
        await page.wait_for_selector(
            "adesso-loading[loading-text*='erfolgreich']",
            timeout=8000,
        )
        logger.info("[Adesso] Bewerbungsformular => success screen.")
        return True
    except TimeoutError:
        return False


async def apply_for_adesso_job(
    page: Page,
    job_url: str,
    job_title: str,
    company: str,
    resume_data: dict,
    job_desc: str = "",
) -> str:
    """
    Main flow:
      1) Open vacancy
      2) Click 'Jetzt bewerben'
      3) Wait for form
      4) Generate PDFs (long + short name)
      5) Fill form, upload CV
      6) Submit
    """
    # Allowed languages list from resume.yaml
    language_list = resume_data.get("languages", []) or []
    languages = [
        (lang.get("short_name") or "").strip().lower()
        for lang in language_list
        if "short_name" in lang
    ]

    if not await open_job_adesso(page, job_url, languages):
        return "lang_skip"

    if not await click_apply_button_adesso(page):
        return "no_apply_button"

    if not await wait_for_form_adesso(page):
        return "error_form_not_found"

    # Generate full resume PDF (with timestamp in filename)
    pdf_path_long = generate_entire_resume_pdf(
        openai_api_key=OPENAI_API_KEY,
        resume_yaml_path=RESUME_YAML_FILE,
        style_css_path=STYLES_CSS_FILE,
        job_description_text=job_desc,
    )
    logger.info(f"[Adesso] Long PDF: {pdf_path_long}")

    folder = os.path.dirname(pdf_path_long)
    personal_info = resume_data.get("personal_information", {}) or {}
    candidate_first = personal_info.get("name", "") or ""
    candidate_last = personal_info.get("surname", "") or ""

    combined = f"{company}_{job_title}".strip()
    pdf_path_short = _build_pdf_filename(
        folder_path=folder,
        candidate_first_name=candidate_first,
        candidate_last_name=combined,
        timestamp="",
        suffix="resume",
    )
    shutil.copy2(pdf_path_long, pdf_path_short)
    logger.info(f"[Adesso] Short PDF (for upload): {pdf_path_short}")

    await fill_personal_data_adesso(page, resume_data)
    await upload_resume_adesso(page, pdf_path_short)
    await accept_privacy_adesso(page)

    if not await submit_application_adesso(page):
        return "submit_not_found"

    if await check_submission_success_adesso(page):
        return "done"
    else:
        return "uncertain"


async def process_adesso_links_in_file(
    page: Page,
    file_path: str,
    resume_data: dict,
) -> None:
    """
    Look for lines in CSV where ExternalURL contains 'adesso-group.com'
    and ApplyStatus = 'external', then call apply_for_adesso_job and
    update CSV.
    """
    if not os.path.exists(file_path):
        logger.error(f"[Adesso] File {file_path} was not found.")
        return

    with open(file_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.warning(f"[Adesso] {file_path} seems empty.")
        return

    headers = rows[0]
    data = rows[1:]

    try:
        idx_url = headers.index("URL")
        idx_status = headers.index("ApplyStatus")
        idx_exturl = headers.index("ExternalURL")
    except ValueError:
        logger.error("[Adesso] Missing required columns: URL / ApplyStatus / ExternalURL.")
        return

    processed_urls: set[str] = set()

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        apply_status = (row[idx_status] or "").strip().lower()
        ext_url = (row[idx_exturl] or "").strip()
        url = (row[idx_url] or "").strip()

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
            job_desc = ""  # можно вытаскивать из CSV при желании

            logger.info(f"[Adesso] Trying to apply for {ext_url} (source row URL: {url})")
            result = await apply_for_adesso_job(
                page,
                ext_url,
                job_title,
                company,
                resume_data,
                job_desc,
            )
            row[idx_status] = result
            data[i] = row

        if i % 10 == 0:
            _save_csv_immediate(file_path, headers, data)

    _save_csv_immediate(file_path, headers, data)


def _save_csv_immediate(file_path: str, headers: list[str], data: list[list[str]]) -> None:
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)
    logger.info(f"[Adesso] CSV {file_path} updated.")
# --- The end of the file: scraping/adesso.py ---


if __name__ == "__main__":
    async def _main():
        # Инициализируем браузер (предполагаем, что init_browser асинхронный)
        pw, context, page = await init_browser()
        try:
            resume_data = load_resume_data(RESUME_YAML_FILE)
            await process_adesso_links_in_file(
                page,
                JOB_LISTINGS_FILE_PATH_ADESSO,
                resume_data,
            )
        finally:
            # Закрываем контекст и Playwright, чтобы не висели процессы
            try:
                await context.close()
            except Exception:
                pass
            try:
                await pw.stop()
            except Exception:
                pass

    asyncio.run(_main())
