from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI
from playwright.sync_api import sync_playwright

from xingbot.logging import logger
from xingbot.utils.text import load_yaml

MAX_PATH_LENGTH = 200

# Небольшие сокращения (чтобы имена файлов не раздувались)
ABBREVIATIONS = {
    "Engineer": "Eng",
    "Engineering": "Eng",
    "Developer": "Dev",
    "Senior": "Sr",
    "Junior": "Jr",
    "Platform": "Plat",
    "Architecture": "Arch",
    "Architect": "Arch",
    "Consultant": "Cons",
}

DEFAULT_PROMPT_FILES = {
    "header": "prompt_header.txt",
    "experience": "prompt_experience.txt",
    "education": "prompt_education.txt",
    "skills": "prompt_skills.txt",
    "projects": "prompt_side_projects.txt",
    "achievements": "prompt_achievements.txt",
    "certifications": "prompt_certifications.txt",
    "profile": "prompt_profile.txt",
}


def _apply_abbreviations(text: str) -> str:
    out = text or ""
    for full, abbrev in ABBREVIATIONS.items():
        out = out.replace(full, abbrev)
    return out


def _sanitize_filename(raw_text: str, max_length: int = 60) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", raw_text or "")
    safe = safe.strip("_- .")
    if len(safe) > max_length:
        safe = safe[:max_length]
    return safe or "file"


def _build_pdf_filename(
    folder_path: str,
    candidate_first_name: str,
    candidate_last_name: str,
    timestamp: str = "",
    suffix: str = "resume",
) -> str:
    """
    Builds a safe, short PDF filename while respecting MAX_PATH_LENGTH.
    """
    folder_abs = os.path.abspath(folder_path)
    base_offset = len(folder_abs) + len(os.path.sep) + len(".pdf")
    max_filename_length = MAX_PATH_LENGTH - base_offset

    parts = [suffix, candidate_first_name, candidate_last_name]
    if timestamp:
        parts.append(timestamp)

    # распределяем длину по сегментам
    total_segments = len(parts)
    remaining = max_filename_length - (total_segments - 1)  # underscores

    sanitized_parts = []
    for part in parts:
        share = max(1, remaining // total_segments)
        sanit = _sanitize_filename(_apply_abbreviations(part), share)
        sanitized_parts.append(sanit)
        remaining -= len(sanit)
        total_segments -= 1

    final_name = "_".join(sanitized_parts) + ".pdf"
    return os.path.join(folder_abs, final_name)


def clean_gpt_html_section(gpt_output: str) -> str:
    """
    Убираем мусор типа ```html и <br>, который GPT иногда лепит.
    """
    cleaned = (gpt_output or "").strip()
    cleaned = cleaned.replace("```html", "").replace("```", "")
    cleaned = re.sub(r"<br\s*/?>", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _extract_text_from_response(response: Any) -> str:
    """
    Extracts text from OpenAI Responses API output (SDK object or dict).
    """
    if response is None:
        return ""

    if isinstance(response, dict):
        txt = response.get("output_text")
        if isinstance(txt, str) and txt.strip():
            return txt.strip()
        out = response.get("output") or []
        parts: list[str] = []
        for item in out:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for c in item.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") in ("text", "output_text"):
                    t = c.get("text")
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
        return "\n".join(parts).strip()

    txt = getattr(response, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()

    try:
        out = getattr(response, "output", None) or []
        parts: list[str] = []
        for item in out:
            if getattr(item, "type", None) != "message":
                continue
            for c in getattr(item, "content", None) or []:
                if getattr(c, "type", None) in ("text", "output_text"):
                    t = getattr(c, "text", None)
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
        return "\n".join(parts).strip()
    except Exception:
        return ""


def load_resume_data(resume_yaml_path: str) -> dict[str, Any]:
    data = load_yaml(resume_yaml_path)
    return data if isinstance(data, dict) else {}


def _read_prompt_file(prompts_dir: Path, filename: str) -> str:
    path = prompts_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _resolve_prompts_dir() -> Path:
    # src/xingbot/gpt/gpt_resume_builder.py -> .../src/xingbot/gpt
    here = Path(__file__).resolve().parent
    prompts_dir = here / "prompts"
    if prompts_dir.is_dir():
        return prompts_dir
    raise FileNotFoundError(f"Prompts dir not found: {prompts_dir}")


class GPTResumeBuilder:
    def __init__(self, openai_api_key: str | None, style_css_path: str, model: str | None = None):
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("[GPTResumeBuilder] OPENAI_API_KEY is missing.")

        self.client = OpenAI(api_key=api_key)
        self.model = model or os.getenv("GPT_RESUME_MODEL", "gpt-5-mini")
        self.style_css_path = style_css_path
        self.sections_html: list[str] = []

    def generate_section(self, prompt_template: str, data_context: dict[str, Any]) -> str:
        prompt = prompt_template.format(**data_context)

        system_prompt = (
            "You are an expert CV writer.\n"
            "Generate a single HTML fragment for ONE resume section based on the user prompt.\n"
            "Do NOT include <html>, <head> or <body> tags.\n"
            "Return ONLY the inner HTML markup.\n"
        )

        logger.info("[GPTResumeBuilder] Requesting GPT to generate resume section...")

        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )

        content = _extract_text_from_response(response)
        content = clean_gpt_html_section(content)

        if not content.strip():
            raise RuntimeError("[GPTResumeBuilder] Empty GPT response for section.")

        return content.strip()

    def add_section(self, section_html: str) -> None:
        self.sections_html.append(section_html)

    def build_full_html(self) -> str:
        css_str = ""
        if self.style_css_path and os.path.exists(self.style_css_path):
            css_str = Path(self.style_css_path).read_text(encoding="utf-8")

        # Важно: внешние @import (google fonts) могут долго грузиться.
        # Поэтому PDF-рендер ниже ждёт только 'load' + небольшую паузу.
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

    def write_pdf(self, output_pdf_path: str) -> None:
        html_str = self.build_full_html()

        out_path = Path(output_pdf_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("[GPTResumeBuilder] Rendering PDF via Playwright: {}", output_pdf_path)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # set_content: не networkidle, чтобы не зависнуть на внешних шрифтах
            page.set_content(html_str, wait_until="load")
            page.wait_for_timeout(800)
            page.emulate_media(media="print")

            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
            )

            browser.close()

        logger.info("[GPTResumeBuilder] PDF created: {}", output_pdf_path)


def generate_entire_resume_pdf(
    openai_api_key: str | None,
    resume_yaml_path: str,
    style_css_path: str,
    job_description_text: str = "",
) -> str:
    prompts_dir = _resolve_prompts_dir()

    # prompts
    prompt_header = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["header"])
    prompt_experience = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["experience"])
    prompt_education = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["education"])
    prompt_skills = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["skills"])
    prompt_projects = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["projects"])
    prompt_achievements = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["achievements"])
    prompt_certifications = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["certifications"])
    prompt_profile = _read_prompt_file(prompts_dir, DEFAULT_PROMPT_FILES["profile"])

    resume_data = load_resume_data(resume_yaml_path)

    experience_details = resume_data.get("experience_details", []) or []
    education_details = resume_data.get("education_details", []) or []
    projects = resume_data.get("projects", []) or []
    achievements = resume_data.get("achievements", []) or []
    certifications = resume_data.get("certifications", []) or []
    languages = resume_data.get("languages", []) or []
    professional_summary = resume_data.get("professional_summary", []) or []
    personal_info = resume_data.get("personal_information", {}) or {}

    # flatten skills
    skills_acquired_flat: list[str] = []
    for exp in experience_details:
        if not isinstance(exp, dict):
            continue
        for skill in exp.get("skills_acquired", []) or []:
            s = str(skill).strip()
            if s:
                skills_acquired_flat.append(s)

    seen: set[str] = set()
    skills_acquired_unique: list[str] = []
    for s in skills_acquired_flat:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            skills_acquired_unique.append(s)

    language_names = [
        (lng.get("language") or "").strip()
        for lng in languages
        if isinstance(lng, dict) and (lng.get("language") or "").strip()
    ]
    languages_str = ", ".join(language_names)

    common_ctx: dict[str, Any] = {
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

    # sections
    builder.add_section(builder.generate_section(prompt_header, common_ctx))

    if experience_details:
        builder.add_section(builder.generate_section(prompt_experience, common_ctx))

    if education_details:
        builder.add_section(builder.generate_section(prompt_education, common_ctx))

    builder.add_section(builder.generate_section(prompt_skills, common_ctx))
    builder.add_section(builder.generate_section(prompt_profile, common_ctx))

    if projects:
        builder.add_section(builder.generate_section(prompt_projects, common_ctx))

    if achievements:
        builder.add_section(builder.generate_section(prompt_achievements, common_ctx))

    if certifications:
        builder.add_section(builder.generate_section(prompt_certifications, common_ctx))

    generated_dir = Path("generated_pdfs")
    generated_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    candidate_first = str(personal_info.get("name", "") or "")
    candidate_last = str(personal_info.get("surname", "") or "")

    upload_pdf_path = _build_pdf_filename(
        folder_path=str(generated_dir),
        candidate_first_name=candidate_first,
        candidate_last_name=candidate_last,
        timestamp="",
        suffix="resume",
    )

    archive_pdf_path = _build_pdf_filename(
        folder_path=str(generated_dir),
        candidate_first_name=candidate_first,
        candidate_last_name=candidate_last,
        timestamp=timestamp_str,
        suffix="resume",
    )

    builder.write_pdf(upload_pdf_path)
    logger.info("[GPTResumeBuilder] Upload PDF created: {}", upload_pdf_path)

    try:
        shutil.copy2(upload_pdf_path, archive_pdf_path)
        logger.info("[GPTResumeBuilder] Archived PDF created: {}", archive_pdf_path)
    except Exception as e:
        logger.warning(
            "[GPTResumeBuilder] Failed to archive PDF ({}): {}",
            archive_pdf_path,
            e,
        )

    return upload_pdf_path
