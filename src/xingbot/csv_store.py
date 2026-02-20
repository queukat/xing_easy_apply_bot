from __future__ import annotations

import csv
import os
from pathlib import Path

from xingbot.enums import JobCsvColumn
from xingbot.logging import logger


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def write_csv_rows_atomic(path: Path, headers: list[str], data: list[list[str]]) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(data)
    os.replace(tmp, path)


def pad_row(row: list[str], headers: list[str]) -> list[str]:
    if len(row) < len(headers):
        return row + [""] * (len(headers) - len(row))
    return row[: len(headers)]


def normalize_schema(headers: list[str], data: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """
    Приводим CSV к канонической схеме в правильном порядке колонок.
    """
    target = JobCsvColumn.headers()
    if headers == target:
        return target, [pad_row(r, target) for r in data]

    old = {h: i for i, h in enumerate(headers or [])}
    new_data: list[list[str]] = []
    for r in data:
        r = r or []
        out: list[str] = []
        for h in target:
            j = old.get(h)
            out.append(r[j] if j is not None and j < len(r) else "")
        new_data.append(out)

    logger.warning("[csv] Header normalized to canonical schema: {}", target)
    return target, new_data


def ensure_job_listings_csv(path: Path) -> None:
    headers, data = read_csv_rows(path)
    target = JobCsvColumn.headers()

    if not headers:
        write_csv_rows_atomic(path, target, [])
        logger.info("[csv] Created {} with headers.", path)
        return

    if headers != target:
        headers, data = normalize_schema(headers, data)
        write_csv_rows_atomic(path, headers, data)
