from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path("log")
LOG_DIR.mkdir(parents=True, exist_ok=True)

CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

_VALID_LEVELS = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _read_env_value(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v is not None:
        return v

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return default

    try:
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, val = line.split("=", 1)
            if k.strip() == key:
                return val.strip().strip().strip("'\"")
    except Exception:
        return default

    return default


def _normalize_level(level: str | None = None) -> str:
    raw = (level or _read_env_value("LOG_LEVEL", "INFO")).upper().strip()
    return raw if raw in _VALID_LEVELS else "INFO"


def configure_logging(level: str | None = None) -> str:
    effective_level = _normalize_level(level)
    logger.remove()
    logger.add(
        sys.stdout,
        format=CONSOLE_FORMAT,
        level=effective_level,
        colorize=True,
        backtrace=False,
        diagnose=False,
    )

    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}:{function}:{line} - {message}"
    logger.add(
        str(LOG_DIR / "xingbot_{time:YYYYMMDD}.log"),
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        level="DEBUG",
        format=file_format,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )
    return effective_level


_CONSOLE_LEVEL = configure_logging()


def get_console_log_level() -> str:
    return _CONSOLE_LEVEL


def set_console_log_level(level: str | None = None) -> str:
    global _CONSOLE_LEVEL
    _CONSOLE_LEVEL = configure_logging(level)
    return _CONSOLE_LEVEL

__all__ = ["logger", "get_console_log_level", "set_console_log_level"]
