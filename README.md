# XING Job Automation Toolkit

Проект автоматизирует сбор вакансий с XING, ранжирование и обработку откликов через единый слой `XingClient` с тестируемыми моками.

Важное ограничение: любой реальный переход по сайту выполняется аккуратно и в ручном режиме там, где это нужно по безопасности.

## Содержание

1. [Что внутри](#что-внутри)
2. [Установка](#установка)
3. [Конфигурация](#конфигурация)
4. [Запуск тестов](#запуск-тестов)
5. [Запуск через PyCharm с выбором сценариев](#запуск-через-pycharm-с-выбором-сценариев)
6. [Как работает pipeline XING](#как-работает-pipeline-xing)
7. [Логирование](#логирование)
8. [E2E на реальном сайте](#e2e-на-реальном-сайте)
9. [Диагностика и частые вопросы](#диагностика-и-частые-вопросы)
10. [Безопасность и секреты](#безопасность-и-секреты)

## Что внутри

Ключевые модули:

- `src/xingbot/settings.py` — загрузка env и runtime-конфигурации.
- `src/xingbot/xing/config.py` — typed policies для HTTP, retry и safety.
- `src/xingbot/xing/http.py` — тестопригодный async HTTP-клиент с retry/backoff и rate-limit.
- `src/xingbot/xing/client.py` — `XingClient`, метод-слой для list/collect/apply.
- `src/xingbot/scraping/xing_cards.py` — парсинг карточек и деталей вакансий.
- `src/xingbot/scraping/xing_scraper.py` — обёртки сценариев `scrape_xing_jobs(page, settings)` и `apply_to_relevant_jobs(page, settings, ...)`.
- `src/xingbot/csv_store.py` и `src/xingbot/enums.py` — схема и хранение `job_listings.csv`.
- `tests/unit` — unit-тесты логики клиента и парсинга.
- `tests/integration` — мок-интеграционные тесты через `respx`.
- `tests/e2e/test_xing_e2e.py` — заглушка, e2e по умолчанию выключен.
- `scripts/run_xing_tests.py` — удобный runner сценариев тестов.
- `scripts/xing_e2e.py` — безопасный ручной сценарий с `--confirm-send`.

## Установка

1. Установи зависимости:

```bash
poetry install
```

2. Активируй окружение:

```bash
.venv\Scripts\Activate.ps1
```

3. Подготовь переменные окружения в `.env` по шаблону `.env.example`.

```bash
Copy-Item .env.example .env
notepad .env
```

4. Проверь, что `pytest` доступен из интерпретатора проекта:

```bash
python -m pytest -q
```

## Конфигурация

### Минимальные переменные

- `XING_EMAIL`
- `XING_PASSWORD`
- `OPENAI_API_KEY` (если используешь шаг оценки резюме/респонса)
- `LOG_LEVEL`

### Runtime и safety

- `XING_URLS`
- `XING_HTTP_TIMEOUT_S`
- `XING_RETRIES`
- `XING_BACKOFF_BASE_S`
- `XING_BACKOFF_MAX_S`
- `XING_RETRY_STATUS`
- `XING_ACTION_INTERVAL_S`
- `XING_MAX_ACTIONS_PER_RUN`
- `XING_DRY_RUN_DEFAULT`
- `XING_RATE_LIMIT_ENABLED`
- `XING_CONFIRM_SEND_DEFAULT`
- `XING_PROXY`
- `HEADLESS`
- `XING_USER_AGENT`
- `XING_ALLOWED_LANGS`
- `FILTER_BY_DESCRIPTION_LANG`
- `KEEP_UNKNOWN_LANG`
- `RELEVANCE_SCORE_THRESHOLD`
- `MAX_SCROLLS`
- `MAX_JOBS_COLLECTED`

### Пример `.env`

```ini
LOG_LEVEL=INFO
HEADLESS=false

XING_EMAIL=
XING_PASSWORD=
OPENAI_API_KEY=

XING_URLS=
XING_ALLOWED_LANGS=en,de
FILTER_BY_DESCRIPTION_LANG=true
KEEP_UNKNOWN_LANG=true
RELEVANCE_SCORE_THRESHOLD=8.0
MAX_SCROLLS=40
MAX_JOBS_COLLECTED=500

XING_HTTP_TIMEOUT_S=8.0
XING_RETRIES=3
XING_BACKOFF_BASE_S=0.7
XING_BACKOFF_MAX_S=4.5
XING_RETRY_STATUS=429,500,502,503,504

XING_ACTION_INTERVAL_S=20.0
XING_MAX_ACTIONS_PER_RUN=1
XING_DRY_RUN_DEFAULT=false
XING_RATE_LIMIT_ENABLED=true
XING_CONFIRM_SEND_DEFAULT=false
XING_PROXY=

XING_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
```

## Как работает pipeline XING

### 1) Сбор вакансий

Сбор выполняет `collect_jobs`, который:
- открывает страницы из `XING_URLS` или дефолтного списка,
- грузит и нормализует существующий `job_listings.csv`,
- сохраняет новые карточки (с дедупликацией),
- при возможности добавляет описание и внешний URL,
- обновляет `stats.csv` и статусные маркеры.

### 2) Применение откликов

`apply_to_relevant_jobs` читает `job_listings.csv` и:
- фильтрует по статусу и порогу score,
- учитывает `dry-run`, `max actions`, `confirm send`,
- обновляет статус в CSV после каждой попытки,
- не шлёт заявки без подтверждения, если включена ручная валидация.

### 3) Базовый пример запуска (ручной контролируемый)

```python
import asyncio
from playwright.async_api import async_playwright

from xingbot.settings import Settings
from xingbot.scraping.xing_scraper import scrape_xing_jobs, apply_to_relevant_jobs


async def main() -> None:
    settings = Settings.load()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.headless)
        context = await browser.new_context()
        page = await context.new_page()

        await scrape_xing_jobs(page, settings)
        await apply_to_relevant_jobs(
            page,
            settings,
            min_score=8.0,
            message="Hello from pipeline",
            dry_run=True,
            max_actions=1,
        )

        await browser.close()


asyncio.run(main())
```

## Запуск тестов

### Полный прогон как в CI

```bash
pytest -q
```

### Сценарии через `scripts/run_xing_tests.py`

- `--scenario unit` — только `tests/unit`
- `--scenario integration` — `tests/integration` с маркером `integration`
- `--scenario e2e` — `tests/e2e` (только если включен флаг, иначе skip)
- `--scenario all` — весь каталог `tests`

```bash
python scripts/run_xing_tests.py --scenario unit
python scripts/run_xing_tests.py --scenario integration
python scripts/run_xing_tests.py --scenario all
python scripts/run_xing_tests.py --scenario e2e --enable-e2e
```

### Рекомендации по скорости

- unit- и integration-тесты запускаются быстро и полностью автоматизируемы;
- e2e не включается в стандартный прогон и требует явного разрешения;
- в `tests/e2e` сохранён один skip-тест с сигналом `XING_E2E_ENABLED=1`.

## Запуск через PyCharm с выбором сценариев

### Сценарий 1: быстрый unit

1. Открой **Run/Debug Configurations**
2. Добавь конфиг `Python`
3. Script: `scripts/run_xing_tests.py`
4. Python interpreter: `...\\.venv\\Scripts\\python.exe`
5. Working directory: `$PROJECT_DIR$`
6. Parameters: `--scenario unit`
7. Сохрани как `XING Unit`

### Сценарий 2: integration

1. Скопируй конфиг `XING Unit`
2. Переименуй в `XING Integration`
3. Замени Parameters на `--scenario integration`

### Сценарий 3: all

1. Переименуй ещё один конфиг в `XING All`
2. Parameters: `--scenario all`

### Сценарий 4: e2e

1. Переименуй ещё один конфиг в `XING E2E`
2. Parameters: `--scenario e2e --enable-e2e`
3. Только для ручных запусков

## Логирование

Логер настроен на `loguru` и читает `LOG_LEVEL` из окружения.

Доступные уровни:

- `TRACE`
- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Формат лога в консоли показывает:
- время,
- уровень,
- модуль и функцию,
- строку,
- сообщение.

```bash
LOG_LEVEL=DEBUG
python scripts/run_xing_tests.py --scenario all
```

## E2E на реальном сайте

В репозитории есть безопасный сценарий в `scripts/xing_e2e.py`.

- браузер запускается `headful` (`headless=False`);
- вход в аккаунт делается вручную;
- без `--confirm-send` действие не выполняется;
- в конце сохраняются скриншоты/HTML в `tests/e2e/artifacts/`.

```bash
python scripts/xing_e2e.py --job-url "https://www.xing.com/jobs/..."
python scripts/xing_e2e.py --job-url "https://www.xing.com/jobs/..." --confirm-send
```

## Диагностика и частые вопросы

Если скрипт не отправляет отклики, проверь `XING_CONFIRM_SEND_DEFAULT` и параметр `confirm_send`.
Если скрипт не отправляет отклики, проверь `XING_MAX_ACTIONS_PER_RUN` и `XING_ACTION_INTERVAL_S`.
Если скрипт не отправляет отклики, проверь, что cookies валидны и `login` не упал в `captcha/2FA`.
Если сбор слишком долгий, снизь `MAX_SCROLLS`.
Если сбор слишком долгий, снизь `MAX_JOBS_COLLECTED`.
Если сбор слишком долгий, уменьшай время ожиданий.
Если тесты медленные, запускай только нужный сценарий `--scenario unit` или `--scenario integration`.

## Безопасность и секреты

- Файл `.env` должен содержать только локальные значения и не коммитится.
- Для репозитория используем `.env.example` с пустыми/заглушечными значениями.
- `.gitignore` настроен на исключение `user_data`, `log`, `debug_artifacts`, `xing_cookies.pkl`, `*storage_state*.json` и `.env`.
- На живом сайте не автоматизируются captcha/2FA; такие участки завершаются с понятным сообщением и инструкцией для ручного шага.
