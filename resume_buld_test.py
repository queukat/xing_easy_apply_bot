# xing_o1_02_2025/resume_buld_test.py

from core.logger import logger
from core.constants import OPENAI_API_KEY
from services.gpt.gpt_resume_builder import generate_entire_resume_pdf

def main():
    logger.info("[resume_buld_test] Тестовая генерация резюме.")
    job_desc = """
    Пример описания вакансии (сюда можно передать реальный текст из job posting).
    """
    pdf_path = generate_entire_resume_pdf(
        openai_api_key=OPENAI_API_KEY,
        resume_yaml_path="resume.yaml",
        style_css_path="styles.css",
        job_description_text=job_desc
    )
    print("Готовое резюме:", pdf_path)

if __name__ == "__main__":
    main()
