"""Read and edit the list of symbols in stonks.txt."""
from __future__ import annotations

import re
from pathlib import Path

SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.=-]{0,11}$")   # AAPL, BRK-B, ^GSPC, BTC-USD, EURUSD=X


class WatchlistError(ValueError):
    """The watchlist file is missing or holds no symbols."""


def is_valid_symbol(symbol: str) -> bool:
    return bool(SYMBOL_RE.match(symbol))


def parse_symbols(text: str) -> list[str]:
    """Uppercase symbols in file order, ignoring blanks, comments and duplicates."""
    symbols: list[str] = []
    for raw in text.splitlines():
        symbol = _symbol_of(raw)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def read_watchlist(path: Path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        raise WatchlistError(f"watchlist not found: {path}")
    symbols = parse_symbols(path.read_text(encoding="utf-8"))
    if not symbols:
        raise WatchlistError(f"no symbols in {path}")
    return symbols


def add_symbol(text: str, symbol: str) -> str:
    """Append the symbol on its own line; unchanged if it is already listed."""
    symbol = symbol.upper()
    if symbol in parse_symbols(text):
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + symbol + "\n"


def remove_symbol(text: str, symbol: str) -> str:
    """Drop every line whose symbol is `symbol`; comments and other lines stay as they are."""
    symbol = symbol.upper()
    return "".join(line for line in text.splitlines(keepends=True) if _symbol_of(line) != symbol)


def _symbol_of(line: str) -> str:
    return line.split("#", 1)[0].strip().upper()
