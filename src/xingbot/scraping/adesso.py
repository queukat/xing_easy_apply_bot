from __future__ import annotations

import asyncio
import csv
import os
import shutil

from bs4 import BeautifulSoup
from langdetect import detect
from playwright.async_api import Page, TimeoutError

from core.constants import OPENAI_API_KEY, RESUME_YAML_FILE, STYLES_CSS_FILE
from core.enums import ApplyStatus, JobCsvColumn
from core.logger import logger
from src.xingbot.gpt.gpt_resume_builder import _build_pdf_filename, generate_entire_resume_pdf
from services.scraping.utils import ahuman_delay, load_resume_data

JOB_LISTINGS_FILE_PATH_ADESSO = "../job_listings.csv"


async def accept_cookies_adesso(page: Page) -> None:
    try:
        cookie_accept_btn = await page.query_selector("#cookie-accept")
        if cookie_accept_btn:
            await cookie_accept_btn.click()
            await ahuman_delay(1, 2)
            logger.info("[Adesso] Cookies accepted.")
    except Exception as e:
        logger.warning("[Adesso] Error when accepting cookies: {}", e)


async def check_language(page: Page, languages) -> bool:
    if isinstance(languages, str):
        languages = [lang.strip().lower() for lang in languages.split(",")]
    else:
        languages = [str(lang).lower() for lang in (languages or [])]

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
    logger.info("[Adesso] Open vacancy: {}", job_url)
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
    except TimeoutError:
        logger.warning("[Adesso] Timeout while loading {}", job_url)
        return False

    await ahuman_delay(2, 4)
    await accept_cookies_adesso(page)

    if not await check_language(page, languages):
        logger.info("[Adesso] Language not suitable, skipping.")
        return False

    return True


async def click_apply_button_adesso(page: Page) -> bool:
    try:
        apply_btn = await page.query_selector("adesso-apply-button")
        if not apply_btn:
            return False

        try:
            async with page.expect_navigation(timeout=10000):
                await apply_btn.click()
        except TimeoutError:
            logger.debug("[Adesso] Navigation timeout after clicking apply button.")
        await ahuman_delay(2, 3)
        return True
    except Exception as e:
        logger.info("[Adesso] Failed to click apply: {}", e)
        return False


async def wait_for_form_adesso(page: Page) -> bool:
    try:
        await page.wait_for_selector("#apply-data", timeout=10000)
        return True
    except TimeoutError:
        try:
            await page.reload()
            await ahuman_delay(2, 3)
            await page.wait_for_selector("#apply-data", timeout=10000)
            return True
        except TimeoutError:
            return False


async def fill_personal_data_adesso(page: Page, resume_data: dict) -> None:
    personal_info = resume_data.get("personal_information", {}) or {}

    salutation_map = {"male": "Herr", "female": "Frau", "divers": "Divers"}
    user_gender = (personal_info.get("gender") or "").lower()
    salutation_value = salutation_map.get(user_gender, "")

    if salutation_value:
        try:
            await page.select_option("select#custSalutation", label=salutation_value)
        except Exception:
            pass

    try:
        await page.fill("#field-firstName", personal_info.get("name", "") or "")
    except Exception:
        pass

    try:
        await page.fill("#field-lastName", personal_info.get("surname", "") or "")
    except Exception:
        pass

    try:
        await page.fill("#field-contactEmail", personal_info.get("email", "") or "")
    except Exception:
        pass

    try:
        await page.fill("#field-cellPhone", personal_info.get("phone", "") or "")
    except Exception:
        pass

    try:
        await page.fill("#field-address", personal_info.get("address", "") or "")
    except Exception:
        pass

    try:
        await page.fill("#field-zip", personal_info.get("zip", "") or "")
    except Exception:
        pass

    try:
        await page.fill("#field-city", personal_info.get("city", "") or "")
    except Exception:
        pass

    country = personal_info.get("country", "") or ""
    if country:
        try:
            await page.select_option("select#country", label=country)
        except Exception:
            pass

    user_de = personal_info.get("german_level", "") or ""
    if user_de:
        try:
            await page.select_option("select#question-1", label=user_de)
        except Exception:
            pass


async def upload_resume_adesso(page: Page, pdf_path: str) -> None:
    try:
        resume_file_input = await page.query_selector("csb-upload[name='resume'] input[type='file']")
        if resume_file_input:
            await resume_file_input.set_input_files(pdf_path)
            return

            resume_file_input = await page.query_selector("csb-upload[name='resume'] >>> input[type='file']")
            if resume_file_input:
                await resume_file_input.set_input_files(pdf_path)
    except Exception as e:
        logger.info("[Adesso] Upload error: {}", e)


async def accept_privacy_adesso(page: Page) -> None:
    try:
        privacy_checkbox = await page.query_selector("#field-privacy")
        if privacy_checkbox:
            await privacy_checkbox.click()
            await ahuman_delay(1, 2)
    except Exception:
        pass


async def submit_application_adesso(page: Page) -> bool:
    try:
        apply_btn = await page.query_selector("button:has-text('Bewerbung absenden')")
        if not apply_btn:
            return False
        await apply_btn.click()
        await ahuman_delay(2, 3)
        return True
    except Exception:
        return False


async def check_submission_success_adesso(page: Page) -> bool:
    try:
        await page.wait_for_selector("adesso-loading[loading-text*='erfolgreich']", timeout=8000)
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
    language_list = resume_data.get("languages", []) or []
    languages = [
        (lang.get("short_name") or "").strip().lower()
        for lang in language_list
        if isinstance(lang, dict) and (lang.get("short_name") or "").strip()
    ]

    if not await open_job_adesso(page, job_url, languages):
        return ApplyStatus.LANG_SKIP.value

    if not await click_apply_button_adesso(page):
        return ApplyStatus.NO_APPLY_BUTTON.value

    if not await wait_for_form_adesso(page):
        return ApplyStatus.ERROR_FORM_NOT_FOUND.value

    def _gen_pdf() -> str:
        return generate_entire_resume_pdf(
            openai_api_key=OPENAI_API_KEY,
            resume_yaml_path=RESUME_YAML_FILE,
            style_css_path=STYLES_CSS_FILE,
            job_description_text=job_desc,
        )

    pdf_path_long = await asyncio.to_thread(_gen_pdf)

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

    await fill_personal_data_adesso(page, resume_data)
    await upload_resume_adesso(page, pdf_path_short)
    await accept_privacy_adesso(page)

    if not await submit_application_adesso(page):
        return ApplyStatus.SUBMIT_NOT_FOUND.value

    return ApplyStatus.DONE.value if await check_submission_success_adesso(page) else ApplyStatus.UNCERTAIN.value


async def process_adesso_links_in_file(page: Page, file_path: str, resume_data: dict) -> None:
    if not os.path.exists(file_path):
        logger.error("[Adesso] File {} not found.", file_path)
        return

    with open(file_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.warning("[Adesso] {} empty.", file_path)
        return

    headers = rows[0]
    data = rows[1:]

    try:
        idx_url = headers.index(JobCsvColumn.URL.value)
        idx_status = headers.index(JobCsvColumn.APPLY_STATUS.value)
        idx_exturl = headers.index(JobCsvColumn.EXTERNAL_URL.value)
    except ValueError:
        logger.error("[Adesso] Missing required columns.")
        return

    processed_urls: set[str] = set()

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        apply_status = (row[idx_status] or "").strip().lower()
        ext_url = (row[idx_exturl] or "").strip()
        url = (row[idx_url] or "").strip()

        if apply_status == ApplyStatus.EXTERNAL.value and "adesso-group.com" in ext_url:
            if ext_url in processed_urls:
                row[idx_status] = ApplyStatus.DUPLICATE.value
                data[i] = row
                continue

            processed_urls.add(ext_url)

            job_title = "Data Engineer"
            company = "adesso"
            job_desc = ""

            logger.info(
                "[Adesso] Applying: {} (source row URL: {})",
                ext_url,
                url,
            )
            result = await apply_for_adesso_job(page, ext_url, job_title, company, resume_data, job_desc)
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
    logger.info("[Adesso] CSV {} updated.", file_path)


if __name__ == "__main__":
    async def _main():
        from core.config import init_browser

        pw, context, page = await init_browser()
        try:
            resume_data = load_resume_data(RESUME_YAML_FILE)
            await process_adesso_links_in_file(page, JOB_LISTINGS_FILE_PATH_ADESSO, resume_data)
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await pw.stop()
            except Exception:
                pass

    asyncio.run(_main())
