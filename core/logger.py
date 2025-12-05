# xing_o1_02_2025/core/logger.py

import sys
from loguru import logger

# Удаляем все существующие хендлеры (по умолчанию у loguru уже есть один)
logger.remove()

# Формат логов: время [уровень] функция - сообщение
# Loguru позволяет подставлять поля record (time, level, function, file и т.д.). :contentReference[oaicite:1]{index=1}
CONSOLE_FORMAT = "{time:HH:mm:ss} [{level}] {function} - {message}"

# Добавляем вывод логов в консоль
logger.add(
    sys.stdout,
    format=CONSOLE_FORMAT,
    level="DEBUG",
)

# Формат для файла (можно расширить: модуль, файл, строка)
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} [{level}] {module}:{function}:{line} - {message}"

# Добавляем вывод логов в файл с ротацией
logger.add(
    "log/my_app_{time}.log",
    rotation="10 MB",       # Размер файла, при котором будет происходить ротация
    retention="14 days",    # Срок хранения старых лог-файлов
    compression="zip",      # Архивирование старых логов
    level="DEBUG",
    format=FILE_FORMAT,
    encoding="utf-8",
)

# Пример использования:
# from logger import logger
# logger.info("Сообщение для проверки работы логгера...")
