"""Read the list of symbols from stonks.txt."""
from __future__ import annotations

from pathlib import Path


class WatchlistError(ValueError):
    """The watchlist file is missing or holds no symbols."""


def read_watchlist(path: Path) -> list[str]:
    """Return uppercase symbols in file order, ignoring blanks, comments and duplicates."""
    path = Path(path)
    if not path.is_file():
        raise WatchlistError(f"watchlist not found: {path}")
    symbols: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.split("#", 1)[0].strip().upper()
        if text and text not in symbols:
            symbols.append(text)
    if not symbols:
        raise WatchlistError(f"no symbols in {path}")
    return symbols
