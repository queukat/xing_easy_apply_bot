# commands/xing_stats.py

import csv
import os
from collections import Counter, defaultdict

from core.logger import logger
from core.constants import (
    STATS_FILE_PATH,
    JOB_LISTINGS_FILE_PATH,
    RELEVANCE_SCORE_THRESHOLD,
)


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val.replace(",", "."))
    except Exception:
        return default


def show_xing_stats(
    stats_file: str = STATS_FILE_PATH,
    job_listings_file: str = JOB_LISTINGS_FILE_PATH,
    score_threshold: float = RELEVANCE_SCORE_THRESHOLD,
) -> None:
    """
    Консольный отчёт:
    1) По stats.csv — сколько собрали с каждого initial XING URL.
    2) По job_listings.csv — сколько релевантных вакансий и на сколько было попыток отклика.
    """

    print("\n==================== XING STATS ====================")

    # --------------------------------------------------
    # Часть 1. Сбор с каждой initial-ссылки (stats.csv)
    # --------------------------------------------------
    if not os.path.exists(stats_file):
        logger.warning(f"[xing_stats] Файл {stats_file} не найден, пропускаем часть про сбор.")
    else:
        print("\n[1] Статистика сбора по initial XING URL (из stats.csv)\n")

        per_url = defaultdict(lambda: {"runs": 0, "total": 0, "last_date": ""})

        with open(stats_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)

            # ожидаемый формат сейчас: URL, CollectedCount, Date
            # но на всякий случай берём:
            #  - URL = row[0]
            #  - count = row[1] (если есть)
            #  - date = row[-1]
            for row in reader:
                if not row:
                    continue
                url = row[0].strip()
                count = 0
                if len(row) > 1:
                    count = _safe_float(row[1], 0.0)
                date = row[-1].strip() if len(row) >= 3 else ""

                stats = per_url[url]
                stats["runs"] += 1
                stats["total"] += count
                stats["last_date"] = date or stats["last_date"]

        if not per_url:
            print("Пока нет записей в stats.csv.")
        else:
            print(f"{'N':>3}  {'Ссылка':<60}  {'Запусков':>8}  {'Всего собрано':>14}  {'Среднее за запуск':>18}  {'Последняя дата':>14}")
            print("-" * 120)
            for i, (url, info) in enumerate(per_url.items(), start=1):
                runs = info["runs"]
                total = info["total"]
                avg = total / runs if runs else 0
                last_date = info["last_date"]
                short_url = (url[:57] + "...") if len(url) > 60 else url
                print(
                    f"{i:>3}  {short_url:<60}  {runs:>8}  {int(total):>14}  {avg:>18.2f}  {last_date:>14}"
                )

    # --------------------------------------------------
    # Часть 2. Отклики по job_listings.csv
    # --------------------------------------------------
    if not os.path.exists(job_listings_file):
        logger.warning(f"[xing_stats] Файл {job_listings_file} не найден, пропускаем часть про отклики.")
        print("\n====================================================\n")
        return

    print("\n[2] Статистика по откликам (из job_listings.csv)\n")

    with open(job_listings_file, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        print("job_listings.csv пустой.")
        print("\n====================================================\n")
        return

    headers = rows[0]
    data = rows[1:]

    # индексы нужных колонок
    try:
        idx_status = headers.index("ApplyStatus")
        idx_score = headers.index("GPT_Score")
    except ValueError:
        print("В job_listings.csv нет нужных колонок (ApplyStatus, GPT_Score).")
        print("\n====================================================\n")
        return

    total_rows = len(data)
    status_counter = Counter()

    total_with_score = 0
    total_relevant = 0
    relevant_empty_status = 0
    relevant_non_empty_status = 0

    for row in data:
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        status_raw = (row[idx_status] or "").strip()
        score_raw = (row[idx_score] or "").strip()

        status = status_raw.lower() if status_raw else ""
        status_counter[status or "<empty>"] += 1

        if score_raw:
            total_with_score += 1
        score_val = _safe_float(score_raw, 0.0)

        if score_val >= score_threshold:
            total_relevant += 1
            if status == "" or status == "pending":
                relevant_empty_status += 1
            else:
                relevant_non_empty_status += 1

    print(f"Всего строк в job_listings.csv: {total_rows}")
    print(f"Из них с непустым GPT_Score: {total_with_score}")
    print(f"Порог релевантности (RELEVANCE_SCORE_THRESHOLD): {score_threshold}")
    print(f"Релевантных вакансий (GPT_Score ≥ {score_threshold}): {total_relevant}")
    print(f"  ├─ из них без статуса отклика (ApplyStatus пустой/\"pending\"): {relevant_empty_status}")
    print(f"  └─ из них с каким-либо статусом (бот хоть что-то сделал):     {relevant_non_empty_status}")

    if total_relevant > 0:
        pct_touched = 100.0 * relevant_non_empty_status / total_relevant
        print(f"\nДоля релевантных, по которым был какой-то отклик: {pct_touched:.1f} %")

    print("\nРазбивка по ApplyStatus (все строки):")
    print(f"{'ApplyStatus':<20}  {'Количество':>10}")
    print("-" * 32)
    for st, cnt in status_counter.most_common():
        print(f"{st:<20}  {cnt:>10}")

    print("\n(Под \"какой-то отклик\" понимается любой непустой ApplyStatus, "
          "будь то 'external', 'chat', 'done', 'error_easy' и т.п.)")

    print("\n====================================================\n")


if __name__ == "__main__":
    show_xing_stats()
