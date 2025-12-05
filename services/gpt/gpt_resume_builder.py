# xing_o1_02_2025/services/gpt/gpt_resume_builder.py

import os
import re
import shutil
from datetime import datetime

from weasyprint import HTML
from openai import OpenAI

from core.logger import logger
from core.constants import ABBREVIATIONS, GENERATED_PDFS_DIR, OPENAI_API_KEY, GPT_RESUME_MODEL
from services.scraping.utils import load_resume_data

MAX_PATH_LENGTH = 200


def _apply_abbreviations(text: str) -> str:
    for full, abbrev in ABBREVIATIONS.items():
        if full in text:
            text = text.replace(full, abbrev)
    return text


def _sanitize_filename(raw_text: str, max_length: int = 50) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", raw_text)
    safe = safe.strip("_- .")
    if len(safe) > max_length:
        safe = safe[:max_length]
    return safe


def _build_pdf_filename(
    folder_path: str,
    candidate_first_name: str,
    candidate_last_name: str,
    timestamp: str = "",
    suffix: str = "resume",
) -> str:
    """
    Формирует безопасное короткое имя PDF-файла с учётом ограничений длины пути.
    """
    folder_abs = os.path.abspath(folder_path)
    base_offset = len(folder_abs) + len(os.path.sep) + len(".pdf")
    max_filename_length = MAX_PATH_LENGTH - base_offset

    parts = [suffix, candidate_first_name, candidate_last_name]
    if timestamp:
        parts.append(timestamp)

    total_segments = len(parts)
    remaining_length = max_filename_length - (total_segments - 1)

    sanitized_parts = []
    for part in parts:
        share = max(1, remaining_length // total_segments)
        sanit = _sanitize_filename(_apply_abbreviations(part) or "", share)
        sanitized_parts.append(sanit)
        remaining_length -= len(sanit)
        total_segments -= 1

    final_name = "_".join(sanitized_parts) + ".pdf"
    return os.path.join(folder_abs, final_name)


def clean_gpt_html_section(gpt_output: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "", gpt_output, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "")
    return cleaned.strip()


def _extract_text_from_response(response) -> str:
    """
    Универсальный способ достать текст из Responses API
    для генерации HTML-фрагмента резюме.
    """
    if getattr(response, "output_text", None):
        return response.output_text or ""

    try:
        return response.output[0].content[0].text
    except Exception:
        return ""


class GPTResumeBuilder:
    def __init__(self, openai_api_key: str | None, style_css_path: str):
        api_key = openai_api_key or OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "[GPTResumeBuilder] OPENAI_API_KEY не задан (ни передан в функцию, "
                "ни в env, ни в core.constants)."
            )
        self.client = OpenAI(api_key=api_key)
        self.style_css_path = style_css_path
        self.sections_html: list[str] = []

    def generate_section(self, prompt_template: str, data_context: dict) -> str:
        """Вызывает GPT для генерации HTML-секции резюме по заданному prompt-шаблону."""
        prompt = prompt_template.format(**data_context)
        logger.info("[GPTResumeBuilder] Запрос к GPT на генерацию секции резюме.")

        system_prompt = (
            "You are an expert CV writer.\n"
            "Generate a single HTML fragment for a resume section based on the "
            "user prompt. Do NOT include <html>, <head> or <body> tags – only "
            "the inner markup for the section."
        )

        response = self.client.responses.create(
            model=GPT_RESUME_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )

        content = _extract_text_from_response(response)
        content = clean_gpt_html_section(content)
        logger.debug(f"[GPTResumeBuilder] GPT ответ (section): {content}")
        return content.strip()

    def add_section(self, section_html: str):
        self.sections_html.append(section_html)

    def build_full_html(self) -> str:
        css_str = ""
        if os.path.exists(self.style_css_path):
            with open(self.style_css_path, "r", encoding="utf-8") as css_file:
                css_str = css_file.read()

        final_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
  {css_str}
  </style>
</head>
<body>
"""
        for section in self.sections_html:
            final_html += section + "\n"

        final_html += "</body>\n</html>"
        return final_html

    def write_pdf(self, output_pdf_path: str):
        html_str = self.build_full_html()
        HTML(string=html_str).write_pdf(output_pdf_path)
        logger.info(f"[GPTResumeBuilder] PDF создан: {output_pdf_path}")


def generate_entire_resume_pdf(
    openai_api_key: str | None,
    resume_yaml_path: str,
    style_css_path: str,
    job_description_text: str = "",
) -> str:
    """
    Генерирует PDF-резюме целиком на основе YAML-данных и prompt-шаблонов.
    """
    from_path = os.path.join("services", "scraping", "prompts")

    def read_prompt(name: str) -> str:
        path = os.path.join(from_path, name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # Читаем prompt-файлы
    prompt_header = read_prompt("prompt_header.txt")
    prompt_experience = read_prompt("prompt_experience.txt")
    prompt_education = read_prompt("prompt_education.txt")
    prompt_skills = read_prompt("prompt_skills.txt")
    prompt_projects = read_prompt("prompt_side_projects.txt")
    prompt_achievements = read_prompt("prompt_achievements.txt")
    prompt_certifications = read_prompt("prompt_certifications.txt")
    prompt_profile = read_prompt("prompt_profile.txt")

    resume_data = load_resume_data(resume_yaml_path)

    experience_details = resume_data.get("experience_details", []) or []
    education_details = resume_data.get("education_details", []) or []
    projects = resume_data.get("projects", []) or []
    achievements = resume_data.get("achievements", []) or []
    certifications = resume_data.get("certifications", []) or []
    languages = resume_data.get("languages", []) or []
    professional_summary = resume_data.get("professional_summary", []) or []
    personal_info = resume_data.get("personal_information", {}) or {}

    # --- агрегируем skills_acquired из опыта ---
    skills_acquired_flat: list[str] = []
    for exp in experience_details:
        for skill in exp.get("skills_acquired", []) or []:
            s = str(skill).strip()
            if s:
                skills_acquired_flat.append(s)

    # dedupe с сохранением порядка
    seen = set()
    skills_acquired_unique: list[str] = []
    for s in skills_acquired_flat:
        if s not in seen:
            seen.add(s)
            skills_acquired_unique.append(s)

    # языки в читаемую строку
    language_names = [
        (lng.get("language") or "").strip()
        for lng in languages
        if (lng.get("language") or "").strip()
    ]
    languages_str = ", ".join(language_names)

    # единый контекст для всех промтов
    common_ctx = {
        "experience_details": experience_details,
        "education_details": education_details,
        "projects": projects,
        "achievements": achievements,
        "certifications": certifications,
        "languages": languages_str,
        "skills_acquired": skills_acquired_unique,
        "professional_summary": professional_summary,
        "personal_info": personal_info,
        "job_description": job_description_text,
    }

    builder = GPTResumeBuilder(openai_api_key=openai_api_key, style_css_path=style_css_path)

    # Header
    builder.add_section(
        builder.generate_section(
            prompt_header,
            common_ctx,
        )
    )

    # Experience
    if experience_details:
        builder.add_section(
            builder.generate_section(
                prompt_experience,
                common_ctx,
            )
        )

    # Education
    if education_details:
        builder.add_section(
            builder.generate_section(
                prompt_education,
                common_ctx,
            )
        )

    # Skills
    builder.add_section(
        builder.generate_section(
            prompt_skills,
            common_ctx,
        )
    )

    # Profile / summary block
    builder.add_section(
        builder.generate_section(
            prompt_profile,
            common_ctx,
        )
    )

    # Projects
    if projects:
        builder.add_section(
            builder.generate_section(
                prompt_projects,
                common_ctx,
            )
        )

    # Achievements
    if achievements:
        builder.add_section(
            builder.generate_section(
                prompt_achievements,
                common_ctx,
            )
        )

    # Certifications
    if certifications:
        builder.add_section(
            builder.generate_section(
                prompt_certifications,
                common_ctx,
            )
        )

    os.makedirs(GENERATED_PDFS_DIR, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    candidate_first = personal_info.get("name", "")
    candidate_last = personal_info.get("surname", "")

    # 1) Путь для загрузки в форму — БЕЗ таймстемпа
    upload_pdf_path = _build_pdf_filename(
        folder_path=GENERATED_PDFS_DIR,
        candidate_first_name=candidate_first,
        candidate_last_name=candidate_last,
        timestamp="",          # 👈 без таймстемпа
        suffix="resume",
    )

    # 2) Путь для архива — С таймстемпом
    archive_pdf_path = _build_pdf_filename(
        folder_path=GENERATED_PDFS_DIR,
        candidate_first_name=candidate_first,
        candidate_last_name=candidate_last,
        timestamp=timestamp_str,   # 👈 с таймстемпом
        suffix="resume",
    )

    # 3) Генерируем PDF для загрузки
    builder.write_pdf(upload_pdf_path)
    logger.info(f"[GPTResumeBuilder] PDF для загрузки создан: {upload_pdf_path}")

    # 4) Делаем архивную копию с таймстемпом
    try:
        shutil.copy2(upload_pdf_path, archive_pdf_path)
        logger.info(f"[GPTResumeBuilder] PDF архивирован с таймстемпом: {archive_pdf_path}")
    except Exception as e:
        logger.warning(
            f"[GPTResumeBuilder] Не удалось создать архивную копию резюме "
            f"({archive_pdf_path}): {e}"
        )

    # ВОЗВРАЩАЕМ путь, который пойдёт в форму (без таймстемпа)
    return upload_pdf_path
