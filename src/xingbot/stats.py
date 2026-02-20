from __future__ import annotations

import csv
from collections import Counter, defaultdict

from xingbot.enums import JobCsvColumn
from xingbot.logging import logger
from xingbot.settings import Settings


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float((val or "").replace(",", "."))
    except Exception:
        return default


def show_stats(settings: Settings) -> None:
    print("\n==================== XING STATS ====================")

    # stats.csv
    if not settings.stats_csv.exists():
        logger.warning("[stats] Missing {}", settings.stats_csv)
    else:
        print("\n[1] Collection per initial URL (stats.csv)\n")
        per_url = defaultdict(lambda: {"runs": 0, "total": 0.0, "last_date": ""})

        with settings.stats_csv.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if not row:
                    continue
                url = row[0].strip()
                count = _safe_float(row[1], 0.0) if len(row) > 1 else 0.0
                date = row[-1].strip() if len(row) >= 3 else ""

                stats = per_url[url]
                stats["runs"] += 1
                stats["total"] += count
                stats["last_date"] = date or stats["last_date"]

        if per_url:
            print(f"{'N':>3}  {'URL':<60}  {'Runs':>6}  {'Total':>10}  {'Avg':>10}  {'Last date':>12}")
            for i, (url, info) in enumerate(per_url.items(), start=1):
                runs = info["runs"]
                total = info["total"]
                avg = total / runs if runs else 0.0
                last_date = info["last_date"]
                short_url = (url[:57] + "...") if len(url) > 60 else url
                print(f"{i:>3}  {short_url:<60}  {runs:>6}  {int(total):>10}  {avg:>10.2f}  {last_date:>12}")
        else:
            print("No rows in stats.csv.")

    # job_listings.csv
    if not settings.job_listings_csv.exists():
        logger.warning("[stats] Missing {}", settings.job_listings_csv)
        print("\n====================================================\n")
        return

    print("\n[2] Apply stats (job_listings.csv)\n")

    with settings.job_listings_csv.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("job_listings.csv empty.")
        print("\n====================================================\n")
        return

    headers = rows[0]
    data = rows[1:]

    try:
        idx_status = headers.index(JobCsvColumn.APPLY_STATUS.value)
        idx_score = headers.index(JobCsvColumn.GPT_SCORE.value)
    except ValueError:
        print("Missing required columns in job_listings.csv.")
        print("\n====================================================\n")
        return

    total_rows = len(data)
    status_counter = Counter()

    total_with_score = 0
    total_relevant = 0
    relevant_non_empty_status = 0

    threshold = settings.relevance_threshold

    for row in data:
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))

        status_raw = (row[idx_status] or "").strip()
        score_raw = (row[idx_score] or "").strip()

        status_norm = status_raw.lower() if status_raw else ""
        status_counter[status_norm or "<empty>"] += 1

        if score_raw:
            total_with_score += 1
        score_val = _safe_float(score_raw, 0.0)

        if score_val >= threshold:
            total_relevant += 1
            if status_norm not in ("", "pending"):
                relevant_non_empty_status += 1

    print(f"Total rows: {total_rows}")
    print(f"Rows with GPT_Score: {total_with_score}")
    print(f"Threshold: {threshold}")
    print(f"Relevant (GPT_Score >= {threshold}): {total_relevant}")
    if total_relevant:
        pct = 100.0 * relevant_non_empty_status / total_relevant
        print(f"Share of relevant that were touched: {pct:.1f}%")

    print("\nApplyStatus breakdown:")
    for st, cnt in status_counter.most_common():
        print(f"{st:<20} {cnt:>8}")

    print("\n====================================================\n")
