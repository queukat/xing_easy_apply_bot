# xing_o1_02_2025/commands/migrate.py

import csv
import os

from core.constants import JOB_LISTINGS_HEADERS
from core.logger import logger

def migrate_stats_to_joblistings(stats_file: str, job_listings_file: str) -> None:
    """
    Переносит записи из stats.csv в job_listings.csv (по URL).
    Если URL ещё нет в job_listings.csv — добавляем новую строку.
    """
    logger.info(f"[migrate_stats_to_joblistings] Перенос из {stats_file} в {job_listings_file}.")

    existing_urls = set()
    if os.path.exists(job_listings_file):
        with open(job_listings_file, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            next(reader, None)  # пропускаем заголовок
            for row in reader:
                if row:
                    existing_urls.add(row[0].strip())

    new_rows = []
    if not os.path.exists(stats_file):
        logger.warning(f"[migrate_stats_to_joblistings] Файл {stats_file} не найден, не переносим.")
        return

    with open(stats_file, 'r', encoding='utf-8') as sf:
        reader = csv.reader(sf)
        header = next(reader, None)
        for row in reader:
            if not row:
                continue

            raw_url = row[0].strip()
            insertion_date = row[-1].strip() if len(row) > 1 else ""

            if raw_url.startswith("/jobs/"):
                full_url = "https://www.xing.com" + raw_url
            else:
                full_url = raw_url

            if full_url not in existing_urls:
                new_row = [
                    full_url,
                    "",   # ApplyStatus
                    "",   # ExternalURL
                    "",   # Description
                    "",   # GPT_Score
                    "",   # GPT_Reason
                    insertion_date or ""
                ]
                new_rows.append(new_row)
                existing_urls.add(full_url)

    file_exists = os.path.exists(job_listings_file)
    mode = 'a' if file_exists else 'w'
    with open(job_listings_file, mode, newline='', encoding='utf-8') as jf:
        writer = csv.writer(jf)
        if not file_exists:
            writer.writerow(JOB_LISTINGS_HEADERS)
        for row in new_rows:
            writer.writerow(row)

    logger.info(f"[migrate_stats_to_joblistings] Перенесено {len(new_rows)} записей.")
