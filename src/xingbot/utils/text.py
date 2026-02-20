from __future__ import annotations

import os
import re
from typing import Any

import yaml

from xingbot.logging import logger


def load_yaml(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("[yaml] failed to load {}: {}", path, e)
        return {}


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def build_resume_text(resume_data: dict[str, Any]) -> str:
    """
    Компактная “плоская” версия резюме для GPT.
    """
    if not isinstance(resume_data, dict):
        return ""

    parts: list[str] = []

    pi = resume_data.get("personal_information") or {}
    if isinstance(pi, dict):
        head = f"{pi.get('name','')} {pi.get('surname','')}".strip()
        loc = f"{pi.get('city','')}, {pi.get('country','')}".strip(", ")
        if head or loc:
            parts.append(_norm_space(f"{head} | {loc}"))

    prof_sum = resume_data.get("professional_summary") or []
    if isinstance(prof_sum, list) and prof_sum:
        parts.append("Summary:")
        for line in prof_sum[:5]:
            parts.append(f"- {_norm_space(str(line))}")

    exp = resume_data.get("experience_details") or []
    if isinstance(exp, list) and exp:
        parts.append("Experience:")
        for item in exp[:4]:
            if not isinstance(item, dict):
                continue
            title = _norm_space(str(item.get("position", "")))
            company = _norm_space(str(item.get("company", "")))
            period = _norm_space(str(item.get("employment_period", "")))
            header = " | ".join([p for p in [title, company, period] if p])
            if header:
                parts.append(f"* {header}")
            bullets = item.get("key_responsibilities") or []
            if isinstance(bullets, list):
                for b in bullets[:6]:
                    parts.append(f"  - {_norm_space(str(b))}")

    skills_seen: set[str] = set()
    skills_flat: list[str] = []
    for item in exp if isinstance(exp, list) else []:
        if not isinstance(item, dict):
            continue
        for s in item.get("skills_acquired") or []:
            ss = _norm_space(str(s))
            if ss and ss.lower() not in skills_seen:
                skills_seen.add(ss.lower())
                skills_flat.append(ss)

    if skills_flat:
        parts.append("Skills:")
        parts.append(", ".join(skills_flat[:80]))

    langs = resume_data.get("languages") or []
    if isinstance(langs, list) and langs:
        names = []
        for l in langs:
            if isinstance(l, dict):
                nm = _norm_space(str(l.get("language", "")))
                if nm:
                    names.append(nm)
        if names:
            parts.append("Languages: " + ", ".join(names))

    return "\n".join(parts).strip()
