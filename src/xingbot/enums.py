from __future__ import annotations

from enum import Enum


class ApplyStatus(str, Enum):
    # neutral
    EMPTY = ""
    PENDING = "pending"
    UNCERTAIN = "uncertain"

    # positive outcomes
    DONE = "done"

    # routing
    EXTERNAL = "external"

    # filtering / skipping
    NOT_RELEVANT = "not relevant"
    NOT_ALLOWED_LANG = "not_allowed_lang"
    DUPLICATE = "duplicate"

    # errors
    TIMEOUT = "timeout"
    ERROR_LOAD = "error_load"
    ERROR_EASY = "error_easy"
    ERROR_GPT = "error_gpt"

    @classmethod
    def normalize(cls, raw: str | None) -> str:
        return (raw or "").strip().lower()


class JobCsvColumn(str, Enum):
    URL = "URL"
    APPLY_STATUS = "ApplyStatus"
    EXTERNAL_URL = "ExternalURL"
    DESCRIPTION = "Description"
    GPT_SCORE = "GPT_Score"
    GPT_REASON = "GPT_Reason"
    INSERTION_DATE = "InsertionDate"

    @classmethod
    def headers(cls) -> list[str]:
        return [c.value for c in cls]
