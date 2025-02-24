# --- Начало файла: scrapers/gpt_resume_builder.py ---
import os
import re
import logging
import openai
from datetime import datetime
from weasyprint import HTML

from config import ABBREVIATIONS
from scrapers.utils import load_resume_data


MAX_PATH_LENGTH = 200  # Максимальная длина итогового пути к PDF


def _apply_abbreviations(text: str) -> str:
    for full, abbrev in ABBREVIATIONS.items():
        if full in text:
            text = text.replace(full, abbrev)
    return text


def _sanitize_filename(raw_text: str, max_length: int = 50) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', raw_text)
    safe = safe.strip("_- .")
    if len(safe) > max_length:
        safe = safe[:max_length]
    return safe


def _build_pdf_filename(folder_path: str,
                        candidate_first_name: str,
                        candidate_last_name: str,
                        timestamp: str = "",
                        suffix: str = "resume") -> str:
    """
    Формирует безопасное короткое имя PDF-файла с учётом ограничений длины пути.
    """
    folder_abs = os.path.abspath(folder_path)
    base_offset = len(folder_abs) + len(os.path.sep) + len(".pdf")
    max_filename_length = MAX_PATH_LENGTH - base_offset

    parts = [suffix, candidate_first_name, candidate_last_name]
    parts = [_apply_abbreviations(p or "") for p in parts if p]

    if timestamp:
        parts.append(timestamp)

    total_segments = len(parts)
    remaining_length = max_filename_length - (total_segments - 1)

    sanitized_parts = []
    for part in parts:
        share = max(1, remaining_length // total_segments)
        sanit = _sanitize_filename(part, share)
        sanitized_parts.append(sanit)
        remaining_length -= len(sanit)
        total_segments -= 1

    final_name = "_".join(sanitized_parts) + ".pdf"
    return os.path.join(folder_abs, final_name)


def clean_gpt_html_section(gpt_output: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "", gpt_output, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "")
    return cleaned.strip()


class GPTResumeBuilder:
    """
    Генерирует HTML-секции (header, experience и т.д.) через GPT,
    собирает в единый HTML, конвертит в PDF (WeasyPrint).
    """

    def __init__(self, openai_api_key: str, style_css_path: str = "styles.css"):
        openai.api_key = openai_api_key
        self.style_css_path = style_css_path
        self.sections_html = []

    def generate_section(self, prompt_template: str, data_context: dict) -> str:
        """
        Запрашивает GPT для генерации HTML-секции по заданному prompt.
        """
        prompt = prompt_template.format(**data_context)
        logging.info("[GPTResumeBuilder] Запрос к GPT для секции...")

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        content = response.choices[0].message.content
        content = clean_gpt_html_section(content)
        logging.debug("[GPTResumeBuilder] GPT ответ (секция): %s", content)
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
        logging.info(f"[GPTResumeBuilder] PDF создан: {output_pdf_path}")


def generate_entire_resume_pdf(openai_api_key: str,
                               resume_yaml_path: str,
                               style_css_path: str,
                               job_description_text: str = "") -> str:
    """
    Генерирует PDF-резюме (WeasyPrint) через GPT по шаблонам из prompts/,
    учитывая (опционально) текст описания вакансии job_description_text.
    """
    from_path = os.path.join("scrapers", "prompts")

    def read_prompt(name):
        path = os.path.join(from_path, name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    prompt_header = read_prompt("prompt_header.txt")
    prompt_experience = read_prompt("prompt_experience.txt")
    prompt_education = read_prompt("prompt_education.txt")
    prompt_skills = read_prompt("prompt_skills.txt")
    prompt_projects = read_prompt("prompt_side_projects.txt")
    prompt_achievements = read_prompt("prompt_achievements.txt")
    prompt_certifications = read_prompt("prompt_certifications.txt")
    prompt_profile = read_prompt("prompt_profile.txt")

    resume_data = load_resume_data(resume_yaml_path)

    experience_details = resume_data.get("experience_details", [])
    education_details = resume_data.get("education_details", [])
    projects = resume_data.get("projects", [])
    achievements = resume_data.get("achievements", [])
    certifications = resume_data.get("certifications", [])
    languages = resume_data.get("languages", [])
    professional_summary = resume_data.get("professional_summary", [])
    personal_info = resume_data.get("personal_information", {})

    # Собираем все skills
    all_skills = []
    for exp in experience_details:
        sk = exp.get("skills_acquired", [])
        all_skills.extend(sk)
    all_skills = list(set(all_skills))

    builder = GPTResumeBuilder(openai_api_key, style_css_path)

    # Секции
    header_section = builder.generate_section(prompt_header, {
        "personal_info": personal_info,
        "job_description": job_description_text
    })
    builder.add_section(header_section)

    profile_section = builder.generate_section(prompt_profile, {
        "personal_info": personal_info,
        "experience_details": experience_details,
        "job_description": job_description_text,
        "professional_summary": professional_summary
    })
    builder.add_section(profile_section)

    experience_section = builder.generate_section(prompt_experience, {
        "experience_details": experience_details,
        "job_description": job_description_text
    })
    builder.add_section(experience_section)

    education_section = builder.generate_section(prompt_education, {
        "education_details": education_details,
        "job_description": job_description_text
    })
    builder.add_section(education_section)

    skills_section = builder.generate_section(prompt_skills, {
        "skills_acquired": all_skills,
        "languages": languages,
        "job_description": job_description_text
    })
    builder.add_section(skills_section)

    if projects:
        projects_section = builder.generate_section(prompt_projects, {
            "projects": projects,
            "job_description": job_description_text
        })
        builder.add_section(projects_section)

    if achievements:
        achievements_section = builder.generate_section(prompt_achievements, {
            "achievements": achievements,
            "job_description": job_description_text
        })
        builder.add_section(achievements_section)

    if certifications:
        certs_section = builder.generate_section(prompt_certifications, {
            "certifications": certifications,
            "job_description": job_description_text
        })
        builder.add_section(certs_section)

    # Создаём итоговый PDF
    output_dir = "generated_pdfs"
    os.makedirs(output_dir, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    candidate_first = personal_info.get("name", "")
    candidate_last = personal_info.get("surname", "")

    pdf_path = _build_pdf_filename(
        folder_path=output_dir,
        candidate_first_name=candidate_first,
        candidate_last_name=candidate_last,
        timestamp=timestamp_str,
        suffix="resume"
    )

    builder.write_pdf(pdf_path)
    return pdf_path
# --- Конец файла: scrapers/gpt_resume_builder.py ---
