import pytest

from stonksteller.watchlist import WatchlistError, read_watchlist


def test_parses_symbols_skipping_blanks_comments_and_duplicates(tmp_path):
    f = tmp_path / "stonks.txt"
    f.write_text("# my list\n aapl \n\nNVDA\nnvda\nTSLA # car\n")
    assert read_watchlist(f) == ["AAPL", "NVDA", "TSLA"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(WatchlistError, match="not found"):
        read_watchlist(tmp_path / "nope.txt")


def test_empty_file_raises(tmp_path):
    f = tmp_path / "stonks.txt"
    f.write_text("# nothing\n\n")
    with pytest.raises(WatchlistError, match="no symbols"):
        read_watchlist(f)
