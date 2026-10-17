from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stonksteller.config import DisplayConfig
from stonksteller.quotes import Quote
from stonksteller.render import (GREEN, GREY, RED, WatchlistTooLarge, build_embeds, format_pct,
                                 format_price, mood_color, render_cards, render_table, render_text,
                                 sort_quotes)

NOW = datetime(2026, 10, 16, 11, 35, tzinfo=ZoneInfo("America/New_York"))
AAPL = Quote("AAPL", 343.46, 346.09, 342.00, 338.22)   # open -0.76%, day +0.43%, week +1.55%
NVDA = Quote("NVDA", 214.13, 216.56, 217.23, 228.73)   # open -1.12%, day -1.43%, week -6.38%
FAKE = Quote("FAKE")


def test_format_helpers():
    assert format_price(343.46) == "343.46" and format_price(None) == "n/a"
    assert format_pct(0.4269) == "+0.43%" and format_pct(-0.7599) == "-0.76%"
    assert format_pct(0.0) == "+0.00%" and format_pct(None) == "n/a"


def test_table_layout_without_emoji():
    assert render_table([AAPL, FAKE], DisplayConfig(emoji=False)) == [
        "SYM    PRICE    OPEN     DAY    WEEK",
        "AAPL  343.46  -0.76%  +0.43%  +1.55%",
        "FAKE     n/a     n/a     n/a     n/a",
    ]


def test_table_puts_a_light_in_every_percentage_cell():
    lines = render_table([AAPL, NVDA, FAKE], DisplayConfig(columns=("price", "week")))
    assert lines[0] == "SYM    PRICE     WEEK"
    assert lines[1] == "AAPL  343.46  🟢+1.55%"
    assert lines[2] == "NVDA  214.13  🔴-6.38%"
    assert lines[3] == "FAKE     n/a     ⚪n/a"


def test_cards_one_inline_field_per_symbol_with_labelled_lit_values():
    assert render_cards([AAPL, FAKE], DisplayConfig()) == [
        {"name": "AAPL", "value": "343.46\n🔴 -0.76% open\n🟢 +0.43% day\n🟢 +1.55% week", "inline": True},
        {"name": "FAKE", "value": "n/a\n⚪ n/a open\n⚪ n/a day\n⚪ n/a week", "inline": True},
    ]


def test_cards_without_emoji_and_with_column_selection():
    assert render_cards([NVDA], DisplayConfig(emoji=False, columns=("week", "price"))) == [
        {"name": "NVDA", "value": "-6.38% week\n214.13", "inline": True},
    ]


def test_sort_by_column_descending_with_na_last():
    assert [q.symbol for q in sort_quotes([FAKE, NVDA, AAPL], "week")] == ["AAPL", "NVDA", "FAKE"]
    assert [q.symbol for q in sort_quotes([FAKE, NVDA, AAPL], "file")] == ["FAKE", "NVDA", "AAPL"]


def test_mood_color():
    assert mood_color([AAPL, NVDA], "week") == GREY          # one up, one down
    assert mood_color([AAPL, NVDA], "open") == RED           # both down vs open
    assert mood_color([AAPL, NVDA, FAKE], "day") == GREY     # n/a counts for neither side
    assert mood_color([AAPL], "day") == GREEN
    assert mood_color([FAKE], "day") == GREY


def test_single_embed_shape():
    [embed] = build_embeds([AAPL], DisplayConfig(), NOW)
    assert embed["title"] == "Stonks · Fri Oct 16 · 11:35 ET"
    assert "description" not in embed
    assert embed["fields"] == [
        {"name": "AAPL", "value": "343.46\n🔴 -0.76% open\n🟢 +0.43% day\n🟢 +1.55% week", "inline": True}]
    assert embed["color"] == RED
    assert embed["footer"] == {"text": "Yahoo Finance"}
    assert embed["timestamp"] == "2026-10-16T15:35:00+00:00"


def test_table_layout_embed_is_a_code_block():
    [embed] = build_embeds([AAPL], DisplayConfig(layout="table", emoji=False), NOW)
    assert embed["description"] == (
        "```\nSYM    PRICE    OPEN     DAY    WEEK\nAAPL  343.46  -0.76%  +0.43%  +1.55%\n```")


def test_splits_into_several_embeds():
    quotes = [Quote(f"S{i:03d}", 10.0, 10.0, 10.0, 10.0) for i in range(60)]
    embeds = build_embeds(quotes, DisplayConfig(), NOW)
    assert len(embeds) == 3
    assert "title" in embeds[0] and "title" not in embeds[1] and "title" not in embeds[2]
    assert "footer" in embeds[2] and "footer" not in embeds[0] and "footer" not in embeds[1]
    assert [len(e["fields"]) for e in embeds] == [25, 25, 10]
    assert embeds[1]["fields"][0]["name"] == "S025"
    assert all(e["color"] == GREY for e in embeds)


def test_too_many_symbols_raises_before_posting():
    quotes = [Quote(f"S{i:03d}", 10.0, 10.0, 10.0, 10.0) for i in range(200)]
    with pytest.raises(WatchlistTooLarge, match="6000"):
        build_embeds(quotes, DisplayConfig(), NOW)


def test_render_text_for_dry_run():
    lines = render_text([AAPL], DisplayConfig(), NOW).splitlines()
    assert lines[0] == "Stonks · Fri Oct 16 · 11:35 ET"
    assert lines[1] == ""
    assert lines[2] == "AAPL  343.46  🔴 -0.76% open  🟢 +0.43% day  🟢 +1.55% week"
    table = render_text([AAPL], DisplayConfig(layout="table", emoji=False), NOW).splitlines()
    assert table[2] == "SYM    PRICE    OPEN     DAY    WEEK"
