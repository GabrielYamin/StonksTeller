"""Quotes and percentage changes, from Yahoo Finance daily history."""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from typing import Sequence

import pandas as pd

log = logging.getLogger(__name__)


def pct_change(price: float | None, ref: float | None) -> float | None:
    """Percent change of price against ref; None when either is missing or ref is not positive."""
    if price is None or ref is None or ref <= 0:
        return None
    return (price / ref - 1) * 100


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float | None = None
    open: float | None = None
    prev_close: float | None = None
    week_open: float | None = None

    @property
    def pct_open(self) -> float | None:
        return pct_change(self.price, self.open)

    @property
    def pct_day(self) -> float | None:
        return pct_change(self.price, self.prev_close)

    @property
    def pct_week(self) -> float | None:
        return pct_change(self.price, self.week_open)


def quotes_from_history(
    history: pd.DataFrame,
    symbols: Sequence[str],
    today: date,
    week_start: date,
    prev_session: date,
) -> list[Quote]:
    """Build one Quote per symbol from a yf.download(group_by="ticker") frame."""
    quotes = []
    for symbol in symbols:
        sub = _per_symbol(history, symbols, symbol)
        if sub is None:
            quotes.append(Quote(symbol))
            continue
        opens = _by_date(sub, "Open")
        closes = _by_date(sub, "Close")
        quotes.append(Quote(
            symbol,
            price=closes.get(today),
            open=opens.get(today),
            prev_close=closes.get(prev_session),
            week_open=opens.get(week_start),
        ))
    return quotes


def merge_fast_info(
    quote: Quote, last_price: float | None, open_: float | None, prev_close: float | None
) -> Quote:
    """Fill only the fields the history left empty."""
    return replace(
        quote,
        price=quote.price if quote.price is not None else last_price,
        open=quote.open if quote.open is not None else open_,
        prev_close=quote.prev_close if quote.prev_close is not None else prev_close,
    )


def fetch_quotes(
    symbols: Sequence[str], today: date, week_start: date, prev_session: date
) -> list[Quote]:
    """One batched Yahoo request, plus a per-symbol fallback when today's row is missing."""
    import yfinance as yf

    history = yf.download(
        list(symbols), period="1mo", interval="1d", group_by="ticker",
        auto_adjust=False, progress=False, threads=True,
    )
    quotes = quotes_from_history(history, symbols, today, week_start, prev_session)
    result = []
    for quote in quotes:
        known = quote.prev_close is not None or quote.week_open is not None
        if quote.price is None and known:
            quote = _fast_info_fallback(quote)
        result.append(quote)
    missing = [q.symbol for q in result if q.price is None]
    if missing:
        log.warning("no price for: %s", ", ".join(missing))
    return result


def symbol_known(symbol: str) -> bool:
    """True if Yahoo Finance returns any daily close for the symbol in the last month."""
    import yfinance as yf

    history = yf.download(
        [symbol], period="1mo", interval="1d", group_by="ticker",
        auto_adjust=False, progress=False, threads=False,
    )
    sub = _per_symbol(history, [symbol], symbol)
    return sub is not None and bool(_by_date(sub, "Close"))


def _fast_info_fallback(quote: Quote) -> Quote:
    import yfinance as yf

    try:
        info = yf.Ticker(quote.symbol).fast_info
        return merge_fast_info(
            quote,
            _number(info, "last_price"),
            _number(info, "open"),
            _number(info, "regular_market_previous_close"),
        )
    except Exception as exc:  # noqa: BLE001 - any Yahoo hiccup just leaves the quote as is
        log.warning("fast_info fallback failed for %s: %s", quote.symbol, exc)
        return quote


def _number(info, key: str) -> float | None:
    try:
        value = info[key]
    except Exception:  # noqa: BLE001
        return None
    if value is None or pd.isna(value):
        return None
    return float(value)


def _per_symbol(history: pd.DataFrame, symbols: Sequence[str], symbol: str) -> pd.DataFrame | None:
    columns = history.columns
    if isinstance(columns, pd.MultiIndex):
        if symbol not in columns.get_level_values(0):
            return None
        return history[symbol]
    if len(symbols) == 1 and symbol == symbols[0] and len(columns):
        return history
    return None


def _by_date(sub: pd.DataFrame, field: str) -> dict[date, float]:
    if field not in sub.columns:
        return {}
    series = sub[field]
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    out: dict[date, float] = {}
    for day, value in zip(index.normalize().date, series.to_numpy()):
        if not pd.isna(value):
            out[day] = float(value)
    return out
