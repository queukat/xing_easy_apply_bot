# xing_o1_02_2025/commands/clean_job_list.py

import csv
import os
import sys
from core.logger import logger

def clean_job_list(
    input_file: str = 'job_listings.csv',
    output_file: str = 'job_listings_clean.csv'
) -> None:
    """
    Удаляет дубликаты строк (уникальность по первой колонке-URL) в CSV-файле.
    Результат сохраняет в output_file.
    """
    if not os.path.exists(input_file):
        logger.error(f"[clean_job_list] Файл {input_file} не найден.")
        sys.exit(1)

    seen = set()
    with open(input_file, 'r', newline='', encoding='utf-8') as fin, \
         open(output_file, 'w', newline='', encoding='utf-8') as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)

        header = next(reader, None)
        if header:
            writer.writerow(header)
            for row in reader:
                if not row:
                    continue
                link = row[0].strip()
                if link not in seen:
                    seen.add(link)
                    writer.writerow(row)

    logger.info(f"[clean_job_list] Очистка завершена, результат в {output_file}.")


if __name__ == "__main__":
    clean_job_list()
