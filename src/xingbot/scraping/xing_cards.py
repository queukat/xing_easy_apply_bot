from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import Page

XING_BASE = "https://www.xing.com"


def is_http_url(u: str) -> bool:
    """True if url is absolute http/https."""
    try:
        p = urlparse((u or "").strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def normalize_xing_url(u: str) -> str:
    """
    Normalizes job urls from XING.

    - Strips whitespace
    - Makes `/jobs/...` absolute (https://www.xing.com/jobs/...)
    - Leaves already absolute URLs intact
    """
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("/"):
        return urljoin(XING_BASE, u)
    return u


def parse_search_cards_from_html(html: str) -> list[SearchCard]:
    """Parse XING search cards from raw HTML (for deterministic offline tests)."""
    html = html or ""
    if not html.strip():
        return []

    card_blocks = re.findall(
        r"<article[^>]*data-testid=['\"]job-search-result['\"][^>]*>(.*?)</article>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not card_blocks:
        return []

    out: list[SearchCard] = []
    seen: set[str] = set()
    for block in card_blocks:
        href_match = re.search(
            r"<a[^>]*href=['\"]([^'\"]+)['\"]",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not href_match:
            continue
        href_raw = href_match.group(1).strip()
        href = normalize_xing_url(href_raw)
        if not href:
            continue

        canonical = canonicalize_url(href)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)

        title = ""
        title_patterns = [
            r"<[^>]*data-testid=['\"]job-teaser-list-title['\"][^>]*>(.*?)</[^>]+>",
            r"<h[1-6][^>]*>(.*?)</h[1-6]>",
            r"<a[^>]*class=['\"][^'\"]*job-teaser-title[^'\"]*['\"][^>]*>(.*?)</a>",
        ]
        for pat in title_patterns:
            m = re.search(pat, block, flags=re.IGNORECASE | re.DOTALL)
            if not m:
                continue
            candidate = re.sub(r"<[^>]+>", "", m.group(1) or "").strip()
            if candidate:
                title = candidate
                break
        if not title:
            anchor_title = re.sub(
                r"<[^>]+>",
                "",
                re.search(
                    r"<a[^>]*>(.*?)</a>",
                    block,
                    flags=re.IGNORECASE | re.DOTALL,
                ).group(1),
            )
            title = (anchor_title or "").strip()
        if not title:
            continue

        is_external = False
        ext_reason = ""
        try:
            p = urlparse(href)
            if "xing.com" not in (p.netloc or "").lower():
                is_external = True
                ext_reason = f"external_netloc={(p.netloc or '').lower()}"
        except Exception:
            pass

        out.append(
            SearchCard(
                href=href,
                canonical_url=canonical,
                title=title,
                is_external=is_external,
                external_reason=ext_reason,
            )
        )

    return out


def canonicalize_url(u: str) -> str:
    """
    Canonical form for de-duplication.

    For XING job pages (`xing.com/jobs/...`) tracking parameters are common (e.g. `?ijt=...`).
    We remove query/fragment ONLY for those internal job pages.

    For external links we keep query, because it can be significant.
    """
    u = (u or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        if not p.scheme:
            u = normalize_xing_url(u)
            p = urlparse(u)

        is_xing = "xing.com" in (p.netloc or "").lower()
        is_jobs = (p.path or "").startswith("/jobs/")
        if is_xing and is_jobs:
            p = p._replace(query="", fragment="")
        return urlunparse(p)
    except Exception:
        return u


def _strip_click_suffix(s: str) -> str:
    """
    XING sometimes appends 'Click to ...' to aria-labels. Remove that suffix.
    """
    s = (s or "").strip()
    if not s:
        return ""
    for sep in (". Click", " . Click", ". Öffnen", ". Open"):
        if sep in s:
            return s.split(sep, 1)[0].strip()
    return s


async def _safe_attr(page_or_locator: Any, attr: str) -> str:
    try:
        val = await page_or_locator.get_attribute(attr)
        return (val or "").strip()
    except Exception:
        return ""


async def _safe_text(locator: Any) -> str:
    """
    Best-effort text extraction from a Locator/ElementHandle-like object.
    """
    try:
        txt = await locator.text_content()
        return (txt or "").strip()
    except Exception:
        try:
            txt = await locator.inner_text()
            return (txt or "").strip()
        except Exception:
            return ""


@dataclass(frozen=True)
class SearchCard:
    href: str
    canonical_url: str
    title: str
    is_external: bool
    external_reason: str = ""


@dataclass(frozen=True)
class XingJobDetails:
    url: str
    title: str
    company: Optional[str]
    location: Optional[str]
    employment_type: Optional[str]
    work_mode: Optional[str]
    salary_text: Optional[str]
    published_at_iso: Optional[str]
    description_text: str
    raw_html_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def parse_search_cards(page: Page) -> list[SearchCard]:
    """
    Parse job cards from a XING search results page.

    Notes:
      - We deduplicate by canonical_url (removing tracking query from internal /jobs/ links).
      - `is_external=True` only when the card link points outside xing.com.
    """
    cards_loc = page.locator("article[data-testid='job-search-result']")
    n = await cards_loc.count()

    out: list[SearchCard] = []
    seen: set[str] = set()

    for i in range(n):
        card = cards_loc.nth(i)

        # href
        href_raw = ""
        try:
            a = card.locator("a[href]").first
            href_raw = (await a.get_attribute("href") or "").strip()
        except Exception:
            href_raw = ""

        href = normalize_xing_url(href_raw)
        if not href:
            continue

        canonical = canonicalize_url(href)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)

        # title
        title = ""
        try:
            tloc = card.locator("[data-testid='job-teaser-list-title']").first
            if await tloc.count() > 0:
                title = (await tloc.inner_text()).strip()
        except Exception:
            title = ""

        if not title:
            # aria-label on the link often contains full title
            try:
                a = card.locator("a[href]").first
                aria = (await a.get_attribute("aria-label") or "").strip()
                title = _strip_click_suffix(aria)
            except Exception:
                title = ""

        if not title:
            # last resort
            try:
                h = card.locator("h2,h3").first
                if await h.count() > 0:
                    title = (await h.inner_text()).strip()
            except Exception:
                title = ""

        if not title:
            continue

        # external?
        is_external = False
        ext_reason = ""
        try:
            if is_http_url(href):
                p = urlparse(href)
                netloc = (p.netloc or "").lower()
                if "xing.com" not in netloc:
                    is_external = True
                    ext_reason = f"external_netloc={netloc}"
        except Exception:
            pass

        out.append(
            SearchCard(
                href=href,
                canonical_url=canonical,
                title=title,
                is_external=is_external,
                external_reason=ext_reason,
            )
        )

    return out


async def _click_show_more_if_present(page: Page) -> None:
    """
    Some job pages truncate description behind a 'Show more' / 'Mehr anzeigen' button.
    """
    btn = page.locator(
        'button:has-text("Show more"), button:has-text("Mehr anzeigen"), button:has-text("Show More")'
    ).first
    try:
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click()
            await page.wait_for_timeout(150)
    except Exception:
        pass


async def parse_details_from_page(page: Page, url: str) -> XingJobDetails:
    """
    Parse key fields from a XING job details page.

    Preconditions:
      - `page` is already navigated to `url` and loaded (domcontentloaded is usually enough).

    Returns:
      XingJobDetails with best-effort fields (many are optional).
    """
    await _click_show_more_if_present(page)

    # title
    title = ""
    try:
        title_container = page.locator('[data-testid="job-details-title"]').first
        if await title_container.count() > 0:
            title = (await title_container.locator("h1,h2").first.text_content() or "").strip()
    except Exception:
        title = ""

    if not title:
        try:
            title = (await page.locator("h1").first.text_content() or "").strip()
        except Exception:
            title = ""

    # company
    company: Optional[str] = None
    company_selectors = [
        '[data-testid="job-details-company-info-name"]',
        '[data-testid="job-details-company-info"] a',
        'a[href*="/company/"]',
    ]
    for sel in company_selectors:
        try:
            c = page.locator(sel).first
            if await c.count() > 0:
                t = (await c.text_content() or "").strip()
                if t:
                    company = t
                    break
        except Exception:
            continue

    # location
    location: Optional[str] = None
    location_selectors = [
        '[data-testid="job-details-location"]',
        '[data-testid="job-details-company-info-location"]',
        '[data-testid="job-details-company-info"] [data-testid*="location"]',
        "[class*='job-intro__AdditionalInfos'] p",
        "[class*='job-intro'] p",
    ]
    for sel in location_selectors:
        try:
            locs = page.locator(sel)
            cnt = await locs.count()
            if cnt <= 0:
                continue

            # Try: pick a text that is not company and looks like a location
            candidates: list[str] = []
            for i in range(min(cnt, 8)):
                t = (await locs.nth(i).text_content() or "").strip()
                if not t:
                    continue
                if company and t.strip().lower() == company.strip().lower():
                    continue
                candidates.append(t)

            # Heuristic: the last additional info often is location
            if candidates:
                location = candidates[-1]
                break
        except Exception:
            continue

    # published time
    published_at_iso: Optional[str] = None
    try:
        t = page.locator('[data-testid="job-details-published-date"] time[datetime]').first
        if await t.count() > 0:
            published_at_iso = (await t.get_attribute("datetime") or "").strip() or None
    except Exception:
        published_at_iso = None

    # highlights (employment type / work mode / salary)
    employment_type: Optional[str] = None
    work_mode: Optional[str] = None
    salary_text: Optional[str] = None

    try:
        highlights = page.locator('ul[aria-label^="Main details for this job"] li')
        if await highlights.count() == 0:
            highlights = page.locator('ul[aria-label*="Main details"] li')
        for i in range(await highlights.count()):
            txt = (await highlights.nth(i).text_content() or "").strip()
            if not txt:
                continue
            low = txt.lower()
            if employment_type is None and ("full-time" in low or "part-time" in low):
                employment_type = txt
            elif salary_text is None and ("€" in txt or "eur" in low):
                salary_text = txt
            elif work_mode is None and ("on-site" in low or "remote" in low or "hybrid" in low):
                work_mode = txt
    except Exception:
        pass

    # description
    description = ""
    description_selectors = [
        '[data-testid="expandable-content"]',
        'section[data-testid="job-details-description"]',
        "main",
    ]
    for sel in description_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            t = (await loc.text_content() or "").strip()
            if t and len(t) > len(description):
                description = t
        except Exception:
            continue

    if not description:
        # ultimate fallback
        try:
            description = (await page.locator("body").first.text_content() or "").strip()
        except Exception:
            description = ""

    return XingJobDetails(
        url=canonicalize_url(url),
        title=title or "(unknown)",
        company=company,
        location=location,
        employment_type=employment_type,
        work_mode=work_mode,
        salary_text=salary_text,
        published_at_iso=published_at_iso,
        description_text=description.strip(),
    )
