# xing_o1_02_2025/services/utils/file_manager.py

import os
import re
import json
import time
import yaml
from typing import Dict, Any

from core.logger import logger

class FileManager:
    """
    Класс для операций с файлами (чтение/запись YAML, JSON, генерация имени PDF и т.д.).
    """

    def __init__(self):
        self._json_cache = {}

    @staticmethod
    def _sanitize_filename(text: str, max_length: int = 100) -> str:
        text = re.sub(r'[\n\r\t]', ' ', text)
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'\s+', '_', text).strip('_')
        return text[:max_length]

    def create_resume_filename(self,
                               first_name: str,
                               last_name: str,
                               company: str,
                               job_title: str) -> str:
        """
        Генерирует имя PDF: "CV_{first_name}_{last_name}_{company}_{job_title}_{timestamp}.pdf".
        Удаляет (m/w/d) из job_title.
        """
        job_title = re.sub(r"\(\s*m\s*/\s*w\s*/\s*d\s*\)", "", job_title, flags=re.IGNORECASE).strip()
        base_parts = [
            "CV",
            first_name,
            last_name,
            company,
            job_title,
            str(int(time.time()))
        ]
        sanitized_parts = [self._sanitize_filename(p) for p in base_parts if p]
        filename = "_".join(sanitized_parts) + ".pdf"
        logger.debug(f"[FileManager] Сформировано имя файла: {filename}")
        return filename

    @staticmethod
    def read_yaml(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def write_json(data: dict, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[FileManager] JSON записан в: {path}")
