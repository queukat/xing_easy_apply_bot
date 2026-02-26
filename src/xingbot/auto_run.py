from __future__ import annotations

import argparse
import asyncio
import random
from typing import Sequence

from xingbot.browser import close_browser, open_browser
from xingbot.gpt.evaluator import evaluate_jobs
from xingbot.logging import logger, set_console_log_level
from xingbot.scraping.xing_scraper import apply_to_relevant_jobs, scrape_xing_jobs
from xingbot.settings import Settings


def _sleep_seconds(min_hours: float = 4.0, max_hours: float = 6.0) -> float:
    return random.uniform(min_hours * 3600.0, max_hours * 3600.0)


async def run_pipeline_once(
    settings: Settings,
    *,
    dry_run: bool,
    confirm_send: bool,
    max_actions: int | None,
    action_interval_s: float | None,
    skip_evaluate: bool,
) -> None:
    session = await open_browser(settings)
    try:
        logger.info("[auto] Run pipeline: collect -> evaluate -> apply")
        await scrape_xing_jobs(session.page, settings)
        if not skip_evaluate:
            await evaluate_jobs(settings)
        await apply_to_relevant_jobs(
            session.page,
            settings,
            min_score=None,
            dry_run=dry_run,
            confirm_send=confirm_send,
            max_actions=max_actions,
            action_interval_s=action_interval_s,
        )
    finally:
        await close_browser(session)


async def auto_run_forever(
    settings: Settings,
    *,
    min_sleep_hours: float,
    max_sleep_hours: float,
    dry_run: bool,
    confirm_send: bool,
    max_actions: int | None,
    action_interval_s: float | None,
    skip_evaluate: bool,
) -> None:
    while True:
        try:
            await run_pipeline_once(
                settings,
                dry_run=dry_run,
                confirm_send=confirm_send,
                max_actions=max_actions,
                action_interval_s=action_interval_s,
                skip_evaluate=skip_evaluate,
            )
        except Exception:
            logger.exception("[auto] Pipeline run failed.")

        s = _sleep_seconds(min_sleep_hours, max_sleep_hours)
        logger.info("[auto] Sleep {} seconds", int(s))
        await asyncio.sleep(s)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run XING automation pipeline on schedule.")
    parser.add_argument(
        "--log-level",
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
        help="Override console log level for this run.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pipeline iteration and exit.",
    )
    parser.add_argument(
        "--min-sleep-hours",
        type=float,
        default=4.0,
        help="Minimum sleep duration between iterations in hours (default: 4).",
    )
    parser.add_argument(
        "--max-sleep-hours",
        type=float,
        default=6.0,
        help="Maximum sleep duration between iterations in hours (default: 6).",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run mode for apply stage (default: true).",
    )
    parser.add_argument(
        "--confirm-send",
        action="store_true",
        help="Require interactive confirmation for each apply click.",
    )
    parser.add_argument(
        "--max-actions",
        type=int,
        default=None,
        help="Override max actions per apply run.",
    )
    parser.add_argument(
        "--action-interval-s",
        type=float,
        default=None,
        help="Override min action interval in seconds.",
    )
    parser.add_argument(
        "--skip-evaluate",
        action="store_true",
        help="Skip GPT evaluation stage.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.log_level:
        level = set_console_log_level(args.log_level)
        logger.info("[logging] Console level overridden to {}", level)
    if args.min_sleep_hours <= 0 or args.max_sleep_hours <= 0:
        parser.error("sleep hours must be > 0")
    if args.max_sleep_hours < args.min_sleep_hours:
        parser.error("max-sleep-hours must be >= min-sleep-hours")
    if not args.dry_run and not args.confirm_send:
        parser.error("--no-dry-run requires --confirm-send for safety")

    settings = Settings.load()
    if args.once:
        asyncio.run(
            run_pipeline_once(
                settings,
                dry_run=bool(args.dry_run),
                confirm_send=bool(args.confirm_send),
                max_actions=args.max_actions,
                action_interval_s=args.action_interval_s,
                skip_evaluate=bool(args.skip_evaluate),
            )
        )
        return

    asyncio.run(
        auto_run_forever(
            settings,
            min_sleep_hours=float(args.min_sleep_hours),
            max_sleep_hours=float(args.max_sleep_hours),
            dry_run=bool(args.dry_run),
            confirm_send=bool(args.confirm_send),
            max_actions=args.max_actions,
            action_interval_s=args.action_interval_s,
            skip_evaluate=bool(args.skip_evaluate),
        )
    )


if __name__ == "__main__":
    main()
