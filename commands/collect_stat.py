# xing_o1_02_2025/commands/collect_stat.py

import pandas as pd
from core.logger import logger

def collect_top_domains(file_path: str = 'job_listings.csv', top_n: int = 15) -> None:
    """
    Анализирует поле 'ExternalURL' в CSV, раскладывает значения (разделитель '|'),
    извлекает домен и выводит в консоль топ-N самых частых.
    """
    logger.info(f"[collect_top_domains] Читаем данные из {file_path}")
    data = pd.read_csv(file_path)

    # Делим значения в колонке "ExternalURL"
    urls = (data['ExternalURL']
            .dropna()
            .str.split('|')
            .explode()
            .str.strip()
           )

    # Извлекаем домены
    domains = (urls
               .str.extract(r'https?://(?:www\.)?([^/]+)')[0]
               .value_counts()
               .head(top_n)
              )

    logger.info("Топ доменов по встречаемости:")
    for domain, count in domains.items():
        print(f"{domain} - {count}")

    total_unique = urls.nunique()
    print(f"Общее число уникальных ссылок: {total_unique}")


if __name__ == "__main__":
    collect_top_domains()
