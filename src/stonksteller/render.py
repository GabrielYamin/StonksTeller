"""Turn quotes into Discord embeds (pure functions, no network)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .config import DisplayConfig
from .market import ET
from .quotes import Quote

GREEN, RED, GREY = 0x2ECC71, 0xE74C3C, 0x95A5A6
ROWS_PER_EMBED = 25          # also Discord's maximum number of fields per embed
MAX_DESCRIPTION = 4096
MAX_MESSAGE = 6000
FOOTER = "Yahoo Finance"
UP, DOWN, FLAT = "🟢", "🔴", "⚪"


class WatchlistTooLarge(ValueError):
    """The message would exceed what Discord accepts."""


def format_price(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def pct_for(quote: Quote, column: str) -> float | None:
    return {"open": quote.pct_open, "day": quote.pct_day, "week": quote.pct_week}[column]


def sort_quotes(quotes: Sequence[Quote], sort: str) -> list[Quote]:
    """File order, or descending by a percentage column with n/a last."""
    if sort == "file":
        return list(quotes)

    def key(quote: Quote):
        value = pct_for(quote, sort)
        return (1, 0.0) if value is None else (0, -value)

    return sorted(quotes, key=key)


def render_cards(quotes: Sequence[Quote], config: DisplayConfig) -> list[dict]:
    """One inline embed field per quote: the symbol, then one labelled line per column."""
    cards = []
    for quote in quotes:
        lines = []
        for column in config.columns:
            if column == "price":
                lines.append(format_price(quote.price))
            else:
                value = pct_for(quote, column)
                text = f"{format_pct(value)} {column}"
                lines.append(f"{_light(value)} {text}" if config.emoji else text)
        cards.append({"name": quote.symbol, "value": "\n".join(lines), "inline": True})
    return cards


def render_table(quotes: Sequence[Quote], config: DisplayConfig) -> list[str]:
    """Monospace layout: header line then one aligned line per quote. Wraps on phones."""
    header = ["SYM", *(column.upper() for column in config.columns)]
    rows = [[quote.symbol, *(_table_cell(quote, column, config.emoji) for column in config.columns)]
            for quote in quotes]
    widths = [max(len(line[i]) for line in [header, *rows]) for i in range(len(header))]

    def fmt(cells: list[str]) -> str:
        return "  ".join(
            cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i]) for i, cell in enumerate(cells)
        )

    return [fmt(header), *(fmt(cells) for cells in rows)]


def mood_color(quotes: Sequence[Quote], color_by: str) -> int:
    values = [pct_for(quote, color_by) for quote in quotes]
    ups = sum(1 for value in values if value is not None and value > 0)
    downs = sum(1 for value in values if value is not None and value < 0)
    if ups > downs:
        return GREEN
    if downs > ups:
        return RED
    return GREY


def title_for(config: DisplayConfig, now: datetime) -> str:
    local = now.astimezone(ET)
    return f"{config.title} · {local:%a %b} {local.day} · {local:%H:%M} ET"


def build_embeds(quotes: Sequence[Quote], config: DisplayConfig, now: datetime) -> list[dict]:
    """One message's worth of embeds; raises WatchlistTooLarge past Discord's limits."""
    ordered = sort_quotes(quotes, config.sort)
    color = mood_color(ordered, config.color_by)

    if config.layout == "table":
        header, *rows = render_table(ordered, config)
        chunks = [rows[i:i + ROWS_PER_EMBED] for i in range(0, len(rows), ROWS_PER_EMBED)] or [[]]
        bodies = [{"description": _fence([header, *chunk])} for chunk in chunks]
    else:
        cards = render_cards(ordered, config)
        chunks = [cards[i:i + ROWS_PER_EMBED] for i in range(0, len(cards), ROWS_PER_EMBED)] or [[]]
        bodies = [{"fields": chunk} for chunk in chunks]

    embeds = []
    for i, body in enumerate(bodies):
        embed: dict = {**body, "color": color}
        if i == 0:
            embed["title"] = title_for(config, now)
        if i == len(bodies) - 1:
            embed["footer"] = {"text": FOOTER}
            embed["timestamp"] = now.astimezone(timezone.utc).isoformat()
        embeds.append(embed)

    total = sum(_embed_length(embed) for embed in embeds)
    longest = max(len(embed.get("description", "")) for embed in embeds)
    if longest > MAX_DESCRIPTION or total > MAX_MESSAGE:
        per_symbol = max(total // max(len(ordered), 1), 1)
        raise WatchlistTooLarge(
            f"{len(ordered)} symbols render to {total} characters; Discord allows {MAX_MESSAGE} "
            f"per message (about {MAX_MESSAGE // per_symbol} symbols). Trim the watchlist."
        )
    return embeds


def render_text(quotes: Sequence[Quote], config: DisplayConfig, now: datetime) -> str:
    """Plain-text version for --dry-run."""
    ordered = sort_quotes(quotes, config.sort)
    if config.layout == "table":
        body = render_table(ordered, config)
    else:
        body = [
            "  ".join([card["name"], *card["value"].split("\n")])
            for card in render_cards(ordered, config)
        ]
    return "\n".join([title_for(config, now), "", *body])


def _table_cell(quote: Quote, column: str, emoji: bool) -> str:
    if column == "price":
        return format_price(quote.price)
    value = pct_for(quote, column)
    text = format_pct(value)
    return f"{_light(value)}{text}" if emoji else text


def _light(value: float | None) -> str:
    if value is None or value == 0:
        return FLAT
    return UP if value > 0 else DOWN


def _fence(lines: Sequence[str]) -> str:
    return "```\n" + "\n".join(lines) + "\n```"


def _embed_length(embed: dict) -> int:
    """Characters Discord counts toward the 6000-per-message cap."""
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + len(embed.get("footer", {}).get("text", ""))
        + sum(len(field["name"]) + len(field["value"]) for field in embed.get("fields", []))
    )
