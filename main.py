import sys
import signal
import asyncio

import nest_asyncio
nest_asyncio.apply()

from core.logger import logger
from core.config import init_browser
from core.constants import (
    STATS_FILE_PATH,
    JOB_LISTINGS_FILE_PATH,
    OPENAI_API_KEY,
    XING_EMAIL,
    XING_PASSWORD,
    RELEVANCE_SCORE_THRESHOLD,
    INITIAL_XING_URLS
)

from services.scraping.xing_scraper import (
    scrape_xing_jobs,
    apply_to_relevant_jobs
)

from services.scraping.join import apply_incomplete_applications
from services.scraping.adesso import process_adesso_links_in_file
from services.scraping.utils import load_resume_data
from services.gpt.gpt_evaluator import evaluate_jobs
from commands.migrate import migrate_stats_to_joblistings


def show_menu():
    print("\nВыберите действие:")
    print("1 - Сбор вакансий (Xing)")
    print("2 - GPT-оценка")
    print("3 - Отклики (Xing)")
    print("4 - Все этапы (1 -> 2 -> 3)")
    print("5 - [Join] Обработка незавершённых заявок")
    print("6 - [Adesso] Поиск ссылок в CSV и автоподача")
    print("7 - Миграция из stats.csv в job_listings.csv")
    print("8 - Генерация резюме (GPT Resume Builder)")
    print("9 - Статистика по XING (сбор + отклики)")  # 👈 НОВОЕ
    print("0 - Выход")
    return input("Введите номер: ")


async def run_all_stages(page):
    """
    Последовательный запуск:
      1) Сбор вакансий
      2) GPT-оценка
      3) Отклики
    """
    logger.info("Запуск всех этапов...")

    try:
        # 1) Сбор
        logger.info("Начинаем сбор вакансий (XING)...")
        await scrape_xing_jobs(
            page=page,
            urls=INITIAL_XING_URLS,
            job_listings_csv=JOB_LISTINGS_FILE_PATH,
            stats_csv=STATS_FILE_PATH,
            email=XING_EMAIL,
            password=XING_PASSWORD
        )

        # 2) GPT-оценка
        logger.info("Запускаем GPT-оценку вакансий...")
        resume_data = load_resume_data()
        await evaluate_jobs(JOB_LISTINGS_FILE_PATH, resume_data)

        # 3) Отклики
        logger.info("Начинаем отклики (Easy Apply) по вакансиям...")
        await apply_to_relevant_jobs(
            page=page,
            job_listings_csv=JOB_LISTINGS_FILE_PATH,
            email=XING_EMAIL,
            password=XING_PASSWORD,
            min_score=RELEVANCE_SCORE_THRESHOLD
        )

    except KeyboardInterrupt:
        logger.warning("Прервано пользователем (Ctrl+C).")


async def main_async():
    """
    Асинхронный «interactive» режим с меню.
    """
    # Можно настроить loguru тут, например в файл:
    # logger.add("app.log", rotation="1 week", level="INFO")

    # Инициализируем браузер один раз на всё время исполнения main_async.
    pw, context, page = await init_browser(headless=False)

    try:
        while True:
            choice = show_menu()

            if choice == '1':
                logger.info("Начинаем сбор вакансий (XING)...")
                await scrape_xing_jobs(
                    page=page,
                    urls=INITIAL_XING_URLS,
                    job_listings_csv=JOB_LISTINGS_FILE_PATH,
                    stats_csv=STATS_FILE_PATH,
                    email=XING_EMAIL,
                    password=XING_PASSWORD
                )

            elif choice == '2':
                logger.info("Запускаем GPT-оценку вакансий...")
                resume_data = load_resume_data()
                await evaluate_jobs(JOB_LISTINGS_FILE_PATH, resume_data)

            elif choice == '3':
                logger.info("Начинаем отклики (Easy Apply) по вакансиям...")
                await apply_to_relevant_jobs(
                    page=page,
                    job_listings_csv=JOB_LISTINGS_FILE_PATH,
                    email=XING_EMAIL,
                    password=XING_PASSWORD,
                    min_score=RELEVANCE_SCORE_THRESHOLD
                )

            elif choice == '4':
                # Вызываем run_all_stages, если хотим заново открыть браузер —
                # но можете передать в неё уже открытые context, page, если
                # это у вас предусмотрено логикой
                await run_all_stages(page)

            elif choice == '5':
                logger.info("Обрабатываем незавершённые заявки (Join)...")
                await apply_incomplete_applications(page, context)

            elif choice == '6':
                logger.info("Поиск и автоподача (Adesso)...")
                resume_data = load_resume_data()
                await process_adesso_links_in_file(page, JOB_LISTINGS_FILE_PATH, resume_data)

            elif choice == '7':
                logger.info("Миграция из stats.csv в job_listings.csv...")
                migrate_stats_to_joblistings(STATS_FILE_PATH, JOB_LISTINGS_FILE_PATH)

            elif choice == '8':
                logger.info("Генерация резюме (GPT Resume Builder)...")
                from services.gpt.gpt_resume_builder import generate_entire_resume_pdf
                pdf_path = generate_entire_resume_pdf(
                    openai_api_key=OPENAI_API_KEY,
                    resume_yaml_path="resume.yaml",
                    style_css_path="styles.css"
                )
                logger.info(f"Сгенерировано резюме: {pdf_path}")

            elif choice == '9':
                logger.info("Показываем статистику по XING...")
                from commands.xing_stats import show_xing_stats
                show_xing_stats()


            elif choice == '0':
                logger.info("Выходим...")
                break
            else:
                logger.warning("Неверный ввод, попробуйте снова.")

    except KeyboardInterrupt:
        logger.warning("Прервано пользователем (Ctrl+C).")
    finally:
        logger.info("Закрываем браузер...")
        await context.close()
        await pw.stop()


def main():
    # Запускаем асинхронную функцию через asyncio.run
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
