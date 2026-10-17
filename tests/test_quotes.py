from datetime import date

import numpy as np
import pandas as pd
import pytest

from stonksteller.quotes import Quote, merge_fast_info, pct_change, quotes_from_history


def make_history(data):
    """data[symbol][iso_date] = (open, close); shaped like yf.download(group_by='ticker')."""
    dates = sorted({d for rows in data.values() for d in rows})
    index = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    columns = pd.MultiIndex.from_product([list(data), ["Open", "High", "Low", "Close"]])
    frame = pd.DataFrame(np.nan, index=index, columns=columns)
    for sym, rows in data.items():
        for d, (o, c) in rows.items():
            frame.loc[pd.Timestamp(d), (sym, "Open")] = o
            frame.loc[pd.Timestamp(d), (sym, "Close")] = c
    return frame


AAPL = {"2026-10-12": (338.22, 340.97), "2026-10-15": (346.95, 342.00), "2026-10-16": (346.09, 343.46)}
TODAY, WEEK_START, PREV = date(2026, 10, 16), date(2026, 10, 12), date(2026, 10, 15)


def test_quote_fields_and_percentages_from_history():
    [q] = quotes_from_history(make_history({"AAPL": AAPL}), ["AAPL"], TODAY, WEEK_START, PREV)
    assert q == Quote("AAPL", price=343.46, open=346.09, prev_close=342.00, week_open=338.22)
    assert q.pct_open == pytest.approx(-0.7599, abs=1e-3)
    assert q.pct_day == pytest.approx(0.4269, abs=1e-3)
    assert q.pct_week == pytest.approx(1.5493, abs=1e-3)


def test_unknown_symbols_are_all_none_and_order_is_kept():
    hist = make_history({"AAPL": AAPL, "FAKE": {}})
    quotes = quotes_from_history(hist, ["AAPL", "FAKE", "MISSING"], TODAY, WEEK_START, PREV)
    assert [q.symbol for q in quotes] == ["AAPL", "FAKE", "MISSING"]
    assert quotes[1] == Quote("FAKE") and quotes[2] == Quote("MISSING")


def test_first_session_of_week_week_equals_open():
    hist = make_history({"AAPL": {"2026-10-09": (331.70, 336.64), "2026-10-12": (338.22, 340.97)}})
    [q] = quotes_from_history(hist, ["AAPL"], date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 9))
    assert q.week_open == q.open == 338.22
    assert q.pct_week == q.pct_open


def test_missing_today_row_leaves_price_and_open_none():
    hist = make_history({"AAPL": {"2026-10-12": (338.22, 340.97), "2026-10-15": (346.95, 342.00)}})
    [q] = quotes_from_history(hist, ["AAPL"], TODAY, WEEK_START, PREV)
    assert q == Quote("AAPL", price=None, open=None, prev_close=342.00, week_open=338.22)


def test_tz_aware_index_is_handled():
    hist = make_history({"AAPL": AAPL})
    hist.index = hist.index.tz_localize("America/New_York")
    [q] = quotes_from_history(hist, ["AAPL"], TODAY, WEEK_START, PREV)
    assert q.price == 343.46


def test_single_level_columns_for_a_single_symbol():
    hist = make_history({"AAPL": AAPL})["AAPL"]   # plain Open/High/Low/Close columns
    [q] = quotes_from_history(hist, ["AAPL"], TODAY, WEEK_START, PREV)
    assert q.price == 343.46


def test_merge_fast_info_fills_only_missing_fields():
    q = Quote("AAPL", price=None, open=None, prev_close=342.00, week_open=338.22)
    assert merge_fast_info(q, last_price=343.46, open_=346.09, prev_close=999.0) == \
        Quote("AAPL", 343.46, 346.09, 342.00, 338.22)


def test_pct_change_guards_against_missing_or_zero_reference():
    assert pct_change(None, 10.0) is None
    assert pct_change(10.0, None) is None
    assert pct_change(10.0, 0.0) is None
    assert pct_change(110.0, 100.0) == pytest.approx(10.0)
    assert Quote("X", price=10.0, open=0.0).pct_open is None
