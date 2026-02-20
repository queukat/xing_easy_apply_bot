from __future__ import annotations

from pathlib import Path

from xingbot.scraping.xing_cards import parse_search_cards_from_html


def test_parse_search_cards_from_html_fixture() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "xing_search_cards.fixture.html"
    raw = fixture.read_text(encoding="utf-8")

    cards = parse_search_cards_from_html(raw)

    assert len(cards) == 3
    assert cards[0].canonical_url == "https://www.xing.com/jobs/abc-1"
    assert cards[1].canonical_url == "https://www.xing.com/jobs/def-2"
    assert cards[2].is_external
