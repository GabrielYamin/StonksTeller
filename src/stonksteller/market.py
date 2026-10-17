"""NYSE session helpers built on exchange_calendars."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from exchange_calendars import ExchangeCalendar

ET = ZoneInfo("America/New_York")
GRACE = timedelta(minutes=20)
CALENDAR_NAME = "XNYS"


def get_calendar(start: str | None = None, end: str | None = None) -> ExchangeCalendar:
    return xcals.get_calendar(CALENDAR_NAME, start=start, end=end)


def is_market_open(now: datetime, cal: ExchangeCalendar) -> bool:
    """True from session open until 20 minutes after session close, ET."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    session = pd.Timestamp(now.astimezone(ET).date())
    if not cal.is_session(session):
        return False
    instant = pd.Timestamp(now)
    return bool(cal.session_open(session) <= instant < cal.session_close(session) + GRACE)


def reference_session(today: date, cal: ExchangeCalendar) -> date:
    """Today if it is a session, otherwise the last session before it."""
    return cal.date_to_session(pd.Timestamp(today), direction="previous").date()


def previous_session(session: date, cal: ExchangeCalendar) -> date:
    return cal.previous_session(pd.Timestamp(session)).date()


def week_start_session(session: date, cal: ExchangeCalendar) -> date:
    """First session of the Monday-to-Sunday week containing `session`."""
    monday = session - timedelta(days=session.weekday())
    return cal.date_to_session(pd.Timestamp(monday), direction="next").date()
