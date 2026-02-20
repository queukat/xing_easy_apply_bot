from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

logger.remove()

LOG_DIR = Path("log")
LOG_DIR.mkdir(parents=True, exist_ok=True)

CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


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


def _normalize_level() -> str:
    level = _read_env_value("LOG_LEVEL", "INFO").upper().strip()
    return level if level in {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"

logger.add(
    sys.stdout,
    format=CONSOLE_FORMAT,
    level=_normalize_level(),
    colorize=True,
    backtrace=False,
    diagnose=False,
)

FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}:{function}:{line} - {message}"
logger.add(
    str(LOG_DIR / "xingbot_{time:YYYYMMDD}.log"),
    rotation="10 MB",
    retention="14 days",
    compression="zip",
    level="DEBUG",
    format=FILE_FORMAT,
    encoding="utf-8",
    backtrace=True,
    diagnose=False,
)

__all__ = ["logger"]
