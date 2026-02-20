from __future__ import annotations

import os
import re
from typing import List, Tuple

from langdetect import LangDetectException, detect
from openai import AsyncOpenAI

from xingbot.csv_store import normalize_schema, pad_row, read_csv_rows, write_csv_rows_atomic
from xingbot.enums import ApplyStatus, JobCsvColumn
from xingbot.gpt.prompts import IS_RELEVANT_POSITION_TEMPLATE
from xingbot.logging import logger
from xingbot.settings import Settings
from xingbot.utils.text import build_resume_text, load_yaml

_SCORE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _extract_text_from_response(resp) -> str:
    """
    Works with OpenAI Responses API objects or dict payloads.
    """
    if resp is None:
        return ""

    if isinstance(resp, dict):
        text = resp.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        output = resp.get("output") or []
        parts: List[str] = []
        for out_item in output:
            if not isinstance(out_item, dict) or out_item.get("type") != "message":
                continue
            for content_item in out_item.get("content") or []:
                if not isinstance(content_item, dict):
                    continue
                if content_item.get("type") in ("text", "output_text"):
                    t = content_item.get("text")
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
        return "\n".join(parts).strip()

    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    try:
        output = getattr(resp, "output", None) or []
        parts: List[str] = []
        for out_item in output:
            if getattr(out_item, "type", None) != "message":
                continue
            for content_item in getattr(out_item, "content", None) or []:
                if getattr(content_item, "type", None) in ("text", "output_text"):
                    t = getattr(content_item, "text", None)
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
        return "\n".join(parts).strip()
    except Exception:
        return ""


def _parse_gpt_answer(answer_text: str) -> Tuple[str, str]:
    """
    Expects:
      Score: <num>
      Reasoning: <text>
    tolerant.
    """
    score = ""
    reason = ""

    if not answer_text:
        return score, reason

    # Debug preview
    preview = answer_text.strip().replace("\n", "\\n")
    if len(preview) > 800:
        preview = preview[:800] + " ...[truncated]..."
    logger.debug("[evaluate_jobs] GPT raw: {}", preview)

    lower = answer_text.lower()

    # find "score:"
    s_pos = lower.find("score:")
    if s_pos == -1:
        # fallback: first number in whole text
        m = _SCORE_RE.search(answer_text)
        if m:
            score = m.group(0)
        reason = answer_text.strip()
        return score, reason

    after = answer_text[s_pos + len("score:") :]

    # split to reason label
    lower_after = after.lower()
    r_pos = lower_after.find("reason:")
    rr_pos = lower_after.find("reasoning:")

    if r_pos != -1 and (rr_pos == -1 or r_pos <= rr_pos):
        score_part = after[:r_pos]
        reason_part = after[r_pos + len("reason:") :]
    elif rr_pos != -1:
        score_part = after[:rr_pos]
        reason_part = after[rr_pos + len("reasoning:") :]
    else:
        score_part = after
        reason_part = ""

    m = _SCORE_RE.search(score_part)
    score = (m.group(0) if m else score_part).strip()
    reason = (reason_part or "").strip()
    return score, reason


async def evaluate_jobs(settings: Settings) -> None:
    if not settings.job_listings_csv.exists():
        logger.warning("[evaluate] Missing file: {}", settings.job_listings_csv)
        return

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.error("[evaluate] OPENAI_API_KEY missing.")
        return

    resume_data = load_yaml(str(settings.resume_yaml))
    resume_text = build_resume_text(resume_data)

    # Allowed langs from resume (short_name)
    allowed_langs: set[str] = set()
    langs = resume_data.get("languages")
    if isinstance(langs, list):
        for item in langs:
            if isinstance(item, dict):
                short = (item.get("short_name") or "").strip().lower()
                if short:
                    allowed_langs.add(short)

    client = AsyncOpenAI(api_key=api_key)

    headers, data = read_csv_rows(settings.job_listings_csv)
    headers, data = normalize_schema(headers, data)

    idx_desc = headers.index(JobCsvColumn.DESCRIPTION.value)
    idx_score = headers.index(JobCsvColumn.GPT_SCORE.value)
    idx_reason = headers.index(JobCsvColumn.GPT_REASON.value)
    idx_status = headers.index(JobCsvColumn.APPLY_STATUS.value)

    system_prompt = (
        "You are an expert in HR and resume evaluation.\n"
        "Answer ONLY in this format:\n"
        "Score: [NUMERIC_SCORE]\n"
        "Reasoning: [BRIEF_REASON]\n"
        "No extra text."
    )

    dirty = False

    for i, row in enumerate(data):
        row = pad_row(row, headers)

        current_score = (row[idx_score] or "").strip()
        if current_score:
            continue

        status_norm = ApplyStatus.normalize(row[idx_status])

        # не перетираем уже “финальные” статусы
        if status_norm not in {
            "",
            ApplyStatus.PENDING.value,
            ApplyStatus.UNCERTAIN.value,
            ApplyStatus.ERROR_EASY.value,
        }:
            continue

        description_raw = (row[idx_desc] or "").strip()
        if not description_raw:
            continue

        # Language gate (если в резюме указан short_name)
        if allowed_langs:
            try:
                detected = detect(description_raw).lower()
                if detected not in allowed_langs:
                    row[idx_score] = ""
                    row[idx_reason] = f"Skipped (lang={detected})"
                    row[idx_status] = ApplyStatus.NOT_ALLOWED_LANG.value
                    data[i] = row
                    dirty = True
                    continue
            except LangDetectException:
                row[idx_score] = ""
                row[idx_reason] = "Skipped (lang detect error)"
                row[idx_status] = ApplyStatus.NOT_ALLOWED_LANG.value
                data[i] = row
                dirty = True
                continue

        user_prompt = IS_RELEVANT_POSITION_TEMPLATE.format(
            job_description=description_raw,
            resume=resume_text,
        )

        try:
            response = await client.responses.create(
                model=settings.gpt_eval_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            gpt_answer = _extract_text_from_response(response)
            score, reason = _parse_gpt_answer(gpt_answer)
            row[idx_score] = score
            row[idx_reason] = reason
            if not (row[idx_status] or "").strip():
                row[idx_status] = ApplyStatus.PENDING.value if score else ApplyStatus.ERROR_GPT.value
        except Exception as e:
            row[idx_score] = ""
            row[idx_reason] = f"Error: {e}"
            row[idx_status] = ApplyStatus.ERROR_GPT.value

        data[i] = row
        dirty = True

        if i % 10 == 0 and dirty:
            write_csv_rows_atomic(settings.job_listings_csv, headers, data)
            dirty = False

    if dirty:
        write_csv_rows_atomic(settings.job_listings_csv, headers, data)

    logger.info("[evaluate] Done.")
