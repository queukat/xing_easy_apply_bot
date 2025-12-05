# --- services/gpt/gpt_evaluator.py ---

"""
GPT-оценка вакансий.

v2.3:
- переход на GPT-5 (Responses API, AsyncOpenAI);
- убран параметр `modalities` (ломал старые версии openai-клиента);
- более надёжный парсинг ответа (Score/Reasoning);
- лёгкая статистика по пропускам/ошибкам;
- язык вакансии проверяется ДО любого LLM-запроса.
"""

from __future__ import annotations

import os
import csv
import re
from typing import List, Tuple

from openai import AsyncOpenAI
from langdetect import detect, LangDetectException

from core.logger import logger
from core.constants import OPENAI_API_KEY, GPT_EVAL_MODEL
from services.scraping.prompts import is_relavant_position_template
from services.scraping.utils import (
    update_csv_file,
    build_resume_text,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _parse_gpt_answer(answer_text: str) -> Tuple[str, str]:
    """
    Извлекает числовой score и текст reason/reasoning из ответа вида:

      Score: 8
      Reasoning: ...

    или

      Score: 8
      Reason: ...

    Возвращает (score_str, reason_str).
    """
    score = ""
    reason = ""

    if not answer_text:
        logger.warning("[evaluate_jobs] Пустой ответ GPT.")
        return score, reason

    # Логируем сырой ответ (с ограничением длины, чтобы не зашумлять логи)
    raw_preview = answer_text.strip()
    if len(raw_preview) > 1000:
        raw_preview = raw_preview[:1000] + " ...[truncated]..."
    logger.debug(
        f"[evaluate_jobs] Сырой ответ GPT: {raw_preview.replace(chr(10), '\\\\n')}"
    )

    lower_text = answer_text.lower()

    # Ищем 'score:' без учёта регистра
    score_label = "score:"
    score_pos = lower_text.find(score_label)
    if score_pos == -1:
        logger.warning(
            "[evaluate_jobs] В ответе GPT нет метки 'Score:' (ni score: ни Score:)."
        )
        return score, reason

    # Часть после 'Score:'
    after_score = answer_text[score_pos + len(score_label) :]
    lower_after = lower_text[score_pos + len(score_label) :]

    # Определяем, что встретилось раньше: Reason: или Reasoning: (тоже без учёта регистра)
    reason_label = "reason:"
    reasoning_label = "reasoning:"

    idx_reason = lower_after.find(reason_label)
    idx_reasoning = lower_after.find(reasoning_label)

    label_pos = None
    label_len = 0

    if idx_reason != -1 and (idx_reasoning == -1 or idx_reason <= idx_reasoning):
        label_pos = idx_reason
        label_len = len(reason_label)
    elif idx_reasoning != -1:
        label_pos = idx_reasoning
        label_len = len(reasoning_label)

    if label_pos is not None:
        raw_score = after_score[:label_pos]
        raw_reason = after_score[label_pos + label_len :]
    else:
        raw_score = after_score
        raw_reason = ""

    try:
        # Достаём первое число (int/float) из raw_score
        num_match = re.search(r"[-+]?\d+(\.\d+)?", raw_score)
        if num_match:
            score = num_match.group(0).strip()
        else:
            score = raw_score.strip()

        reason = raw_reason.strip()
    except Exception as ex:
        logger.warning(f"[evaluate_jobs] Ошибка парсинга ответа GPT: {ex}")

    return score, reason


def _extract_text_from_response(resp) -> str:
    """
    Универсально достаёт текст из объекта Response.

    1) Пытается взять resp.output_text (агрегированный текст из всех текстовых кусков).
    2) Если пусто — обходит resp.output и собирает все элементы типа text/output_text.
    3) Если output пустой, но есть resp.error/status, аккуратно логирует это.
    """
    if resp is None:
        return ""

    # Отдельно обрабатываем dict (на случай, если кто-то передаст "сырой" JSON)
    if isinstance(resp, dict):
        text = resp.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        output = resp.get("output") or []
        collected_parts: List[str] = []
        for out_item in output:
            if not isinstance(out_item, dict):
                continue
            if out_item.get("type") != "message":
                continue
            for content_item in out_item.get("content") or []:
                if not isinstance(content_item, dict):
                    continue
                item_type = content_item.get("type")
                if item_type in ("text", "output_text"):
                    value = content_item.get("text")
                    if isinstance(value, str):
                        collected_parts.append(value)
        return "\n".join(part for part in collected_parts if part and part.strip())

    # 1. Прямая попытка через output_text (как рекомендует официальный SDK)
    try:
        text = getattr(resp, "output_text", None)
    except Exception as e:
        logger.warning(
            f"[evaluate_jobs] Ошибка доступа к response.output_text: {repr(e)}"
        )
        text = None

    if isinstance(text, str) and text.strip():
        return text.strip()

    # 2. Через output -> message -> content -> text
    try:
        output = getattr(resp, "output", None)

        if not output:
            # Возможная ситуация: status != "completed" и/или response.error установлен
            status = getattr(resp, "status", None)
            error = getattr(resp, "error", None)

            if error is not None:
                try:
                    logger.warning(
                        f"[evaluate_jobs] Response имеет пустой output "
                        f"(status={status}), error={error!r}"
                    )
                except Exception:
                    logger.warning(
                        f"[evaluate_jobs] Response имеет пустой output "
                        f"(status={status}), error не сериализуется."
                    )
            return ""

        collected_parts: List[str] = []

        for out_item in output:
            # Нас интересуют только сообщения ассистента
            if getattr(out_item, "type", None) != "message":
                continue

            contents = getattr(out_item, "content", None) or []
            for content_item in contents:
                item_type = getattr(content_item, "type", None)

                # В актуальных версиях SDK текст представлен типом ResponseOutputText
                # с полями: type="text" или "output_text" и text: str
                if item_type in ("text", "output_text"):
                    value = getattr(content_item, "text", None)

                    if isinstance(value, str):
                        collected_parts.append(value)
                    else:
                        # Старые/нестандартные варианты, где text может быть объектом с value
                        nested_value = getattr(value, "value", None)
                        if isinstance(nested_value, str):
                            collected_parts.append(nested_value)

        joined = "\n".join(part for part in collected_parts if part and part.strip())
        return joined
    except Exception as e:
        logger.warning(
            f"[evaluate_jobs] Не удалось вытащить текст из response через output: {repr(e)}"
        )
        return ""


# --------------------------------------------------------------------------- #
# Main entry                                                                  #
# --------------------------------------------------------------------------- #


async def evaluate_jobs(file_path: str, resume_data: dict) -> None:
    """
    Асинхронно оценивает вакансии в CSV-файле (где нет GPT_Score) через GPT-5.
    Результат (GPT_Score, GPT_Reason) пишет обратно в CSV.

    Важно: язык описания вакансии проверяется через langdetect ДО вызова модели.
    """
    if not os.path.exists(file_path):
        logger.warning(
            f"[evaluate_jobs] Файл {file_path} не найден, пропускаем GPT-оценку."
        )
        return

    api_key = OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error(
            "[evaluate_jobs] OPENAI_API_KEY не задан (ни в env, ни в core.constants). "
            "GPT-оценка невозможна."
        )
        return

    client = AsyncOpenAI(api_key=api_key)

    # Языки, указанные в резюме (короткие названия, если есть)
    allowed_langs = set()
    if isinstance(resume_data.get("languages"), list):
        for lang_item in resume_data["languages"]:
            short = (lang_item.get("short_name") or "").strip().lower()
            if short:
                allowed_langs.add(short)

    # Читаем CSV
    with open(file_path, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        logger.warning("[evaluate_jobs] CSV пустой.")
        return

    headers = rows[0]
    data: List[List[str]] = rows[1:]

    # Индексы нужных колонок
    try:
        idx_url = headers.index("URL")
        idx_desc = headers.index("Description")
        idx_score = headers.index("GPT_Score")
        idx_reason = headers.index("GPT_Reason")
        idx_status = headers.index("ApplyStatus")
    except ValueError:
        logger.error(
            "[evaluate_jobs] Нет нужных колонок "
            "(URL, Description, GPT_Score, GPT_Reason, ApplyStatus)."
        )
        return

    resume_text = build_resume_text(resume_data)
    total_rows = len(data)
    logger.info(
        f"[evaluate_jobs] Начинаем GPT-оценку (модель={GPT_EVAL_MODEL}, строк={total_rows}, "
        f"допустимые языки резюме={sorted(allowed_langs) if allowed_langs else 'не ограничены'})"
    )

    # Простая статистика
    already_scored = 0
    skipped_status = 0
    skipped_empty_desc = 0
    skipped_lang = 0
    evaluated = 0
    api_errors = 0

    for i, row in enumerate(data):
        # Дополняем пустые ячейки
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        job_url = (row[idx_url] or "").strip()
        current_score = (row[idx_score] or "").strip()
        current_reason = (row[idx_reason] or "").strip()
        description_raw = (row[idx_desc] or "").strip()
        apply_status = (row[idx_status] or "").strip().lower()

        # Пропускаем, если Score уже есть или статус не требует оценки
        if current_score:
            already_scored += 1
            continue

        if apply_status not in ["", "error_easy", "uncertain"]:
            skipped_status += 1
            continue

        # Пустое описание — смысла звать GPT нет
        if not description_raw:
            skipped_empty_desc += 1
            logger.debug(
                f"[evaluate_jobs] Пустое описание у {job_url}, пропускаем GPT."
            )
            continue

        # Проверка языка ДО вызова модели
        if allowed_langs:
            try:
                detected_lang = detect(description_raw).lower()
                if detected_lang not in allowed_langs:
                    skipped_lang += 1
                    row[idx_score] = ""
                    row[idx_reason] = f"Skipped (lang={detected_lang})"
                    row[idx_status] = "not relevant"
                    data[i] = row
                    logger.info(
                        f"[evaluate_jobs] {job_url} => пропущена (язык {detected_lang})."
                    )
                    if i % 5 == 0:
                        update_csv_file(data, file_path, headers)
                    continue
            except LangDetectException:
                skipped_lang += 1
                row[idx_score] = ""
                row[idx_reason] = "Skipped (lang detect error)"
                row[idx_status] = "not relevant"
                data[i] = row
                logger.info(
                    f"[evaluate_jobs] {job_url} => пропущена (ошибка определения языка)."
                )
                if i % 5 == 0:
                    update_csv_file(data, file_path, headers)
                continue

        # Формируем prompt для GPT
        user_prompt = is_relavant_position_template.format(
            job_description=description_raw,
            resume=resume_text,
        )

        system_prompt = (
            "You are an expert in HR and resume evaluation.\n"
            "Follow the instructions in the user prompt and answer ONLY in this format:\n"
            "Score: [NUMERIC_SCORE]\n"
            "Reasoning: [BRIEF_REASON]\n\n"
            "No bullet points or extra text."
        )

        logger.debug(f"[evaluate_jobs] Запрос к GPT по вакансии {job_url}.")

        score = ""
        reason = ""

        try:
            response = await client.responses.create(
                model=GPT_EVAL_MODEL,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            gpt_answer = _extract_text_from_response(response)

            if not gpt_answer.strip():
                logger.warning(
                    f"[evaluate_jobs] Пустой ответ GPT для {job_url}. "
                    f"Raw response: {repr(response)}"
                )
            else:
                score, reason = _parse_gpt_answer(gpt_answer)
                evaluated += 1
                logger.info(
                    f"[evaluate_jobs] {job_url} => score={score}, reason={reason}"
                )

        except Exception as e:
            api_errors += 1
            logger.error(
                f"[evaluate_jobs] Ошибка OpenAI API для {job_url}: {repr(e)}"
            )
            score = ""
            reason = f"Error: {e}"

        row[idx_score] = score
        row[idx_reason] = reason
        # Статус трогаем только если ещё пустой — чтобы не затирать уже выставленные статусы
        if not row[idx_status].strip():
            row[idx_status] = "pending" if score else "error_gpt"

        data[i] = row

        # Периодически сохраняем прогресс
        if i % 5 == 0:
            update_csv_file(data, file_path, headers)

    # Финальная запись
    update_csv_file(data, file_path, headers)

    logger.info(
        f"[evaluate_jobs] GPT-оценка завершена. "
        f"Всего строк: {total_rows}, "
        f"оценено: {evaluated}, "
        f"уже оценены ранее: {already_scored}, "
        f"пропущены по статусу: {skipped_status}, "
        f"пустое описание: {skipped_empty_desc}, "
        f"язык/ошибка langdetect: {skipped_lang}, "
        f"ошибок API: {api_errors}"
    )

