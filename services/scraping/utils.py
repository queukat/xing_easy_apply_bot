# --- services/scraping/utils.py ---

"""
Разные вспомогательные утилиты-«обёртки» для Playwright-скриптов
(задержки, случайные движения мыши, CSV-помощники и пр.).

*Новое в v2.1*
Добавлена асинхронная версия задержки `ahuman_delay()` ­– теперь
её можно безопасно вызывать внутри `async`-корутин, не блокируя
event-loop.
"""

from __future__ import annotations

import asyncio
import csv
import os
import random
import time
from typing import Any, List, Sequence

import pyautogui
from playwright.async_api import ElementHandle, Page
from playwright.sync_api import Page as SyncPage  # для sync join-скрипта

from core.logger import logger

pyautogui.FAILSAFE = False


# --------------------------------------------------------------------------- #
# Blocking / non-blocking “human” delays                                      #
# --------------------------------------------------------------------------- #
# def human_delay(min_time: float = 2.0, max_time: float = 5.0) -> None:
#     """
#     **Синхронная** пауза (используется внутри sync-скриптов).
#
#     Блокирует поток – поэтому в `async`-коде пользоваться ЕЮ больше
#     **нельзя**.
#     """
#     delay = random.uniform(min_time, max_time)
#     logger.debug(f"[human_delay] sleep ≈ {delay:.2f} s (sync)")
#     time.sleep(delay)


async def ahuman_delay(min_time: float = 2.0, max_time: float = 5.0) -> None:
    """
    **Асинхронная** версия «человеческой» задержки.

    Используйте внутри `async def` функций вместо `human_delay`, чтобы
    не блокировать event-loop.
    """
    delay = random.uniform(min_time, max_time)
    logger.debug(f"[ahuman_delay] sleep ≈ {delay:.2f} s (async)")
    await asyncio.sleep(delay)


# --------------------------------------------------------------------------- #
# Random mouse moves (sync, подходит только для desktop окружений)            #
# --------------------------------------------------------------------------- #
def random_mouse_movements(duration: float = 5.0) -> None:
    end_time = time.time() + duration
    screen_width, screen_height = pyautogui.size()

    while time.time() < end_time:
        x = random.randint(0, screen_width)
        y = random.randint(0, screen_height)
        move_duration = random.uniform(0.1, 0.5)
        pyautogui.moveTo(x, y, duration=move_duration)
        pause_duration = random.uniform(0.2, 2)
        time.sleep(pause_duration)


# --------------------------------------------------------------------------- #
# Element helpers                                                             #
# --------------------------------------------------------------------------- #
async def move_cursor_to_element(page: Page, element: ElementHandle) -> None:
    box = await element.bounding_box()
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    await page.mouse.move(x, y)


# --------------------------------------------------------------------------- #
# CSV helpers                                                                 #
# --------------------------------------------------------------------------- #
def update_csv_file(data: Sequence[Sequence[Any]], file_path: str, headers: List[str]) -> None:
    with open(file_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(data)
    logger.info(f"[update_csv_file] File {file_path} updated.")


def load_existing_urls(file_path: str) -> set[str]:
    existing_urls = set()
    if os.path.exists(file_path):
        with open(file_path, "r", newline="", encoding="utf-8") as file:
            reader = csv.reader(file)
            next(reader, None)
            for row in reader:
                if row:
                    existing_urls.add(row[0])
    else:
        logger.info(f"[load_existing_urls] File {file_path} not found.")
    return existing_urls


# --------------------------------------------------------------------------- #
# Resume helpers (unchanged)                                                  #
# --------------------------------------------------------------------------- #
import yaml  # noqa: E402  (local import to keep upper block compact)

def load_resume_data(yaml_file: str = "resume.yaml") -> dict:
    if not os.path.exists(yaml_file):
        logger.warning(f"[load_resume_data] File {yaml_file} not found.")
        return {}
    with open(yaml_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# def build_resume_text(resume_data: dict) -> str:
#     personal_info = resume_data.get("personal_information", {})
#     summary_list = resume_data.get("professional_summary", [])
#
#     lines = []
#     full_name = f"{personal_info.get('name', '')} {personal_info.get('surname', '')}".strip()
#     lines.append(f"Name: {full_name}")
#     lines.append(f"Email: {personal_info.get('email', '')}")
#     lines.append(f"Location: {personal_info.get('city', '')}, {personal_info.get('country', '')}")
#
#     if isinstance(summary_list, list) and summary_list:
#         lines.append("Professional Summary:")
#         lines.extend(summary_list)
#
#     return "\n".join(lines)

def build_resume_text(resume_data: dict) -> str:
    return yaml.safe_dump(resume_data, allow_unicode=True, sort_keys=False)


def _save_debug_data(page: Page, prefix: str = "debug_screenshot") -> None:
    """Сохраняет скриншот страницы и HTML в файлы с уникальными именами."""
    timestamp = int(time.time())
    # Убедимся, что папка для отладочных файлов существует:
    debug_dir = "debug_artifacts"
    os.makedirs(debug_dir, exist_ok=True)

    screenshot_path = os.path.join(debug_dir, f"{prefix}_{timestamp}.png")
    html_path = os.path.join(debug_dir, f"{prefix}_{timestamp}.html")

    try:
        page.screenshot(path=screenshot_path, full_page=True)
    except Exception as e:
        print(f"Не удалось сделать скриншот: {e}")

    try:
        html_content = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        print(f"Не удалось сохранить HTML: {e}")

    print(f"Debug data saved: {screenshot_path}, {html_path}")
# --- end of the file: scraping/utils.py ---
