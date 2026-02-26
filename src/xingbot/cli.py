from __future__ import annotations

import argparse
import asyncio
from typing import Sequence

from xingbot.auto_run import auto_run_forever, run_pipeline_once
from xingbot.browser import close_browser, open_browser
from xingbot.gpt.evaluator import evaluate_jobs
from xingbot.logging import logger, set_console_log_level
from xingbot.scraping.xing_scraper import apply_to_relevant_jobs, scrape_xing_jobs
from xingbot.settings import Settings
from xingbot.stats import show_stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="XING automation CLI")
    parser.add_argument(
        "--log-level",
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
        help="Override console log level for this run.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="Collect jobs into job_listings.csv")
    sub.add_parser("evaluate", help="Evaluate collected jobs with GPT")
    sub.add_parser("stats", help="Print collection/apply stats")

    apply_p = sub.add_parser("apply", help="Apply to relevant jobs")
    apply_p.add_argument("--min-score", type=float, default=None, help="Override score threshold.")
    apply_p.add_argument("--message", default="", help="Optional payload message.")
    apply_p.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run apply mode (default: true).",
    )
    apply_p.add_argument(
        "--confirm-send",
        action="store_true",
        help="Prompt before each real click/submit.",
    )
    apply_p.add_argument("--max-actions", type=int, default=None, help="Override max actions per run.")
    apply_p.add_argument(
        "--action-interval-s",
        type=float,
        default=None,
        help="Override min action interval in seconds.",
    )

    run_p = sub.add_parser("run", help="Run full pipeline once: collect -> evaluate -> apply")
    run_p.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run apply mode (default: true).",
    )
    run_p.add_argument("--confirm-send", action="store_true", help="Prompt before each real apply click.")
    run_p.add_argument("--max-actions", type=int, default=None, help="Override max actions per run.")
    run_p.add_argument("--action-interval-s", type=float, default=None, help="Override action interval.")
    run_p.add_argument("--skip-evaluate", action="store_true", help="Skip GPT evaluate stage.")

    auto_p = sub.add_parser("auto-run", help="Run pipeline in loop with random sleep")
    auto_p.add_argument("--min-sleep-hours", type=float, default=4.0, help="Minimum sleep hours.")
    auto_p.add_argument("--max-sleep-hours", type=float, default=6.0, help="Maximum sleep hours.")
    auto_p.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run apply mode (default: true).",
    )
    auto_p.add_argument("--confirm-send", action="store_true", help="Prompt before each real apply click.")
    auto_p.add_argument("--max-actions", type=int, default=None, help="Override max actions per run.")
    auto_p.add_argument("--action-interval-s", type=float, default=None, help="Override action interval.")
    auto_p.add_argument("--skip-evaluate", action="store_true", help="Skip GPT evaluate stage.")

    return parser


async def _cmd_collect(settings: Settings) -> None:
    session = await open_browser(settings)
    try:
        await scrape_xing_jobs(session.page, settings)
    finally:
        await close_browser(session)


async def _cmd_apply(args: argparse.Namespace, settings: Settings) -> None:
    if not args.dry_run and not args.confirm_send:
        raise RuntimeError("--no-dry-run requires --confirm-send for safety.")

    session = await open_browser(settings)
    try:
        await apply_to_relevant_jobs(
            session.page,
            settings,
            min_score=args.min_score,
            message=args.message,
            dry_run=bool(args.dry_run),
            confirm_send=bool(args.confirm_send),
            max_actions=args.max_actions,
            action_interval_s=args.action_interval_s,
        )
    finally:
        await close_browser(session)


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.log_level:
        level = set_console_log_level(args.log_level)
        logger.info("[logging] Console level overridden to {}", level)
    settings = Settings.load()

    if args.command == "collect":
        asyncio.run(_cmd_collect(settings))
        return
    if args.command == "evaluate":
        asyncio.run(evaluate_jobs(settings))
        return
    if args.command == "stats":
        show_stats(settings)
        return
    if args.command == "apply":
        asyncio.run(_cmd_apply(args, settings))
        return
    if args.command == "run":
        if not args.dry_run and not args.confirm_send:
            parser.error("--no-dry-run requires --confirm-send for safety")
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
    if args.command == "auto-run":
        if args.min_sleep_hours <= 0 or args.max_sleep_hours <= 0:
            parser.error("sleep hours must be > 0")
        if args.max_sleep_hours < args.min_sleep_hours:
            parser.error("max-sleep-hours must be >= min-sleep-hours")
        if not args.dry_run and not args.confirm_send:
            parser.error("--no-dry-run requires --confirm-send for safety")
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
        return

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
