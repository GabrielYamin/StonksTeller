import pytest

from stonksteller.watchlist import (WatchlistError, add_symbol, is_valid_symbol, parse_symbols,
                                    read_watchlist, remove_symbol)


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


@pytest.mark.parametrize("symbol, valid", [
    ("AAPL", True), ("BRK-B", True), ("^GSPC", True), ("BTC-USD", True), ("EURUSD=X", True),
    ("aapl", False), ("QQ$", False), ("", False), ("TOOLONGSYMBOL1", False), ("A B", False),
])
def test_is_valid_symbol(symbol, valid):
    assert is_valid_symbol(symbol) is valid


def test_add_symbol_appends_once_with_trailing_newline():
    assert add_symbol("# c\nAAPL", "qqq") == "# c\nAAPL\nQQQ\n"
    assert add_symbol("AAPL\nQQQ\n", "QQQ") == "AAPL\nQQQ\n"
    assert add_symbol("", "V") == "V\n"


def test_remove_symbol_drops_only_that_symbols_lines():
    text = "# c\nAAPL\nAVGO   # Broadcom\nqqq\nV\n"
    assert remove_symbol(text, "QQQ") == "# c\nAAPL\nAVGO   # Broadcom\nV\n"
    assert remove_symbol(text, "AVGO") == "# c\nAAPL\nqqq\nV\n"
    assert parse_symbols(remove_symbol(text, "NOPE")) == ["AAPL", "AVGO", "QQQ", "V"]
