from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XING manual-safe e2e smoke flow")
    parser.add_argument("--job-url", required=True, help="XING job URL to open")
    parser.add_argument(
        "--message",
        default="",
        help="Summary message for dry-run output (not sent automatically).",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="tests/e2e/artifacts",
        help="Directory for screenshots and html dumps.",
    )
    parser.add_argument(
        "--storage-state",
        default="tests/e2e/xing_storage_state.json",
        help="Path to persisted storage state (optional).",
    )
    parser.add_argument(
        "--confirm-send",
        action="store_true",
        help="Explicitly allow click/submit on the apply action after confirmation.",
    )
    return parser.parse_args()


def _has_human_gate(text: str) -> bool:
    flags = ("captcha", "recaptcha", "two-factor", "2fa", "verify", "security check")
    lower = (text or "").lower()
    return any(flag in lower for flag in flags)


async def _pick_apply_target(page) -> tuple[str, str]:
    selectors = [
        "button:has-text('Apply')",
        "button:has-text('Bewerben')",
        "a:has-text('Apply')",
        "a:has-text('Bewerben')",
        "button[data-testid*='apply']",
        "a[data-testid*='apply']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                return "element", sel
        except Exception:
            continue
    return "none", ""


async def _safe_inner_text(page, selector: str) -> str:
    try:
        element = page.locator(selector).first
        if await element.count() == 0:
            return ""
        return (await element.inner_text() or "").strip()
    except Exception:
        return ""


async def run() -> None:
    args = _parse_args()
    artifacts = Path(args.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)

    storage_state = Path(args.storage_state)
    storage_state.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="services/scraping/user_data",
            headless=False,
            viewport=None,
            storage_state=str(storage_state) if storage_state.exists() else None,
        )

        page = await context.new_page()
        try:
            await page.goto(args.job_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1800)

            print("[XING-E2E] Open the page and finish login/CAPTCHA manually if needed.")
            if not storage_state.exists():
                print(
                    "[XING-E2E] No storage_state found. "
                    "Login manually once, then return here and continue."
                )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            html = await page.content()

            safe_html = args.message.replace(" ", "_")[:80] or "xing_e2e"
            await page.screenshot(path=str(artifacts / f"xing_e2e_{safe_html}_{ts}.png"), full_page=True)
            (artifacts / f"xing_e2e_{safe_html}_{ts}.html").write_text(html, encoding="utf-8")

            body = (await page.inner_text("body")).lower()
            if _has_human_gate(body):
                print(
                    "[XING-E2E] Human gate detected (captcha/2FA/verify)."
                    " Stop and finish manually in browser; do not proceed."
                )
                return

            target_type, sel = await _pick_apply_target(page)
            title = await _safe_inner_text(page, "h1")
            print("[XING-E2E] URL:", args.job_url)
            print("[XING-E2E] Title:", title)
            print("[XING-E2E] Message:", args.message or "(empty)")
            print("[XING-E2E] Detect:", target_type, sel or "(not found)")

            if target_type != "element":
                print("[XING-E2E] No Apply CTA found. This job may be external.")
                return

            if not args.confirm_send:
                print("[XING-E2E] --confirm-send is required to click.")
                input("Press Enter after manual review, or Ctrl+C to abort: ")
                return

            answer = input("[XING-E2E] Confirm apply click for this job? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("[XING-E2E] Cancelled by user.")
                return

            loc = page.locator(sel).first
            if await loc.count() == 0:
                print("[XING-E2E] Apply element disappeared before click.")
                return

            await loc.click()
            await page.wait_for_timeout(1800)
            ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
            await page.screenshot(path=str(artifacts / f"xing_e2e_after_apply_{ts2}.png"), full_page=True)
            print("[XING-E2E] Apply click executed. Review the page before any next step.")
        finally:
            try:
                await context.storage_state(path=str(storage_state))
            except Exception:
                pass
            await context.close()


if __name__ == "__main__":
    asyncio.run(run())
