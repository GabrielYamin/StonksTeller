from datetime import date, datetime, timezone

import pytest

from stonksteller.market import (get_calendar, is_market_open, previous_session,
                                 reference_session, week_start_session)

UTC = timezone.utc


@pytest.fixture(scope="module")
def cal():
    return get_calendar(start="2026-01-01", end="2026-12-31")


@pytest.mark.parametrize("instant, expected", [
    (datetime(2026, 7, 15, 13, 35, tzinfo=UTC), True),    # 09:35 EDT
    (datetime(2026, 1, 15, 13, 35, tzinfo=UTC), False),   # 08:35 EST, before open
    (datetime(2026, 1, 15, 14, 35, tzinfo=UTC), True),    # 09:35 EST
    (datetime(2026, 10, 16, 13, 29, tzinfo=UTC), False),  # one minute before open
    (datetime(2026, 10, 16, 13, 30, tzinfo=UTC), True),   # open
    (datetime(2026, 10, 16, 20, 19, tzinfo=UTC), True),   # inside 20-minute grace
    (datetime(2026, 10, 16, 20, 20, tzinfo=UTC), False),  # grace over
    (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), False),   # Saturday
    (datetime(2026, 11, 26, 15, 0, tzinfo=UTC), False),   # Thanksgiving
    (datetime(2026, 11, 27, 18, 10, tzinfo=UTC), True),   # early close 13:00 ET, in grace
    (datetime(2026, 11, 27, 18, 25, tzinfo=UTC), False),  # early close, grace over
])
def test_is_market_open(cal, instant, expected):
    assert is_market_open(instant, cal) is expected


def test_naive_datetime_rejected(cal):
    with pytest.raises(ValueError):
        is_market_open(datetime(2026, 10, 16, 15, 0), cal)


def test_reference_session(cal):
    assert reference_session(date(2026, 10, 16), cal) == date(2026, 10, 16)
    assert reference_session(date(2026, 10, 17), cal) == date(2026, 10, 16)


def test_previous_session(cal):
    assert previous_session(date(2026, 10, 16), cal) == date(2026, 10, 15)
    assert previous_session(date(2026, 10, 12), cal) == date(2026, 10, 9)


def test_week_start_session(cal):
    assert week_start_session(date(2026, 10, 16), cal) == date(2026, 10, 12)
    assert week_start_session(date(2026, 10, 12), cal) == date(2026, 10, 12)
    assert week_start_session(date(2026, 9, 10), cal) == date(2026, 9, 8)   # Labor Day week
