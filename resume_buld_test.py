from __future__ import annotations

import os
import sys
from pathlib import Path

# чтобы "python resume_buld_test.py" работал без установки пакета
root = Path(__file__).resolve().parent
src_dir = root / "src"
if src_dir.exists():
    sys.path.insert(0, str(src_dir))

from xingbot.logging import logger
from xingbot.gpt.gpt_resume_builder import generate_entire_resume_pdf


def main() -> None:
    logger.info("[resume_buld_test] Тестовая генерация резюме.")

    job_desc = """
    Example job description.
    Senior Data Engineer role, cloud, pipelines, SQL, Python, orchestration...
    """

    pdf_path = generate_entire_resume_pdf(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        resume_yaml_path="resume.yaml",
        style_css_path="styles.css",
        job_description_text=job_desc,
    )

    print("Готовое резюме:", pdf_path)


if __name__ == "__main__":
    main()
