# --- Начало файла: scrapers/utils.py ---
import time
import random
import logging
import csv
import os
import pyautogui
import yaml

pyautogui.FAILSAFE = False


def human_delay(min_time=2, max_time=5):
    """
    Случайная задержка (имитация поведения человека).
    """
    delay = random.uniform(min_time, max_time)
    logging.debug(f"[human_delay] Ожидание ~{delay:.2f} сек.")
    time.sleep(delay)


def random_mouse_movements(duration=5):
    """
    Случайные движения мышью (имитация).
    """
    end_time = time.time() + duration
    screen_width, screen_height = pyautogui.size()

    while time.time() < end_time:
        x = random.randint(0, screen_width)
        y = random.randint(0, screen_height)
        move_duration = random.uniform(0.1, 0.5)
        pyautogui.moveTo(x, y, duration=move_duration)
        pause_duration = random.uniform(0.2, 2)
        time.sleep(pause_duration)


def move_cursor_to_element(page, element):
    """
    Перемещение курсора в центр элемента (Playwright).
    """
    box = element.bounding_box()
    if box is None:
        return
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y)


def update_csv_file(data, file_path, headers):
    """
    Перезаписывает CSV-файл новыми данными.
    """
    with open(file_path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(data)
    logging.info(f"[update_csv_file] Файл {file_path} обновлён.")


def load_existing_urls(file_path):
    """
    Возвращает множество всех URL (из первой колонки CSV).
    """
    existing_urls = set()
    if os.path.exists(file_path):
        with open(file_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)
            for row in reader:
                if row:
                    existing_urls.add(row[0])
    else:
        logging.info(f"[load_existing_urls] Файл {file_path} не найден.")
    return existing_urls


def load_resume_data(yaml_file="resume.yaml") -> dict:
    """
    Загружает YAML-файл с данными резюме.
    """
    if not os.path.exists(yaml_file):
        logging.warning(f"[load_resume_data] Файл {yaml_file} не найден.")
        return {}
    with open(yaml_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_resume_text(resume_data: dict) -> str:
    """
    Превращает часть резюме (yaml) в текст для GPT (или для других целей).
    """
    personal_info = resume_data.get("personal_information", {})
    summary_list = resume_data.get("professional_summary", [])

    lines = []
    full_name = f"{personal_info.get('name', '')} {personal_info.get('surname', '')}".strip()
    lines.append(f"Name: {full_name}")
    lines.append(f"Email: {personal_info.get('email', '')}")
    lines.append(f"Location: {personal_info.get('city', '')}, {personal_info.get('country', '')}")

    if isinstance(summary_list, list) and summary_list:
        lines.append("Professional Summary:")
        for item in summary_list:
            lines.append(item)

    return "\n".join(lines)
# --- Конец файла: scrapers/utils.py ---
