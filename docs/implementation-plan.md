# StonksTeller Implementation Plan

> Note (2026-10-17): after this plan was executed, posting switched from a bot token to a channel webhook (`DISCORD_WEBHOOK_URL`). Task 7, Task 8 and Task 9 below describe the original bot-token version; `docs/design.md` has the current behaviour.


**Goal:** A `stonks` CLI plus a scheduled GitHub Actions workflow that posts an hourly Discord embed of watchlist prices and changes during NYSE hours, with no backend.

**Architecture:** A `src/stonksteller` package of small single-purpose modules: watchlist parsing, config loading, market-calendar checks, quote fetching (only yfinance import), rendering (pure: quotes in, embed dicts out), Discord posting (only Discord HTTP), and a CLI that wires them with explicit exit codes. Network modules are thin; everything else is unit-tested with pinned dates and values. Two workflows: the scheduled poster and a test runner.

**Tech Stack:** Python 3.10+, uv (pyproject + uv.lock, hatchling), yfinance 1.7, exchange_calendars 4.13, requests, python-dotenv, tomli (py<3.11), pytest. GitHub Actions: `actions/checkout@v7`, `astral-sh/setup-uv@v10`.

**Spec:** `docs/design.md`

## Global Constraints

- Code runs on Python 3.10 and newer (`requires-python = ">=3.10"`); TOML via `tomllib` on 3.11+, `tomli` below.
- All "today" and title times derive from `datetime.now(ZoneInfo("America/New_York"))`, never the runner clock.
- Market calendar is `XNYS` only; "open" is `session_open <= now < session_close + 20 minutes`.
- Exactly one Discord message per successful run; never truncate the table.
- Exit codes: 0 success or market closed; 1 data or Discord failure; 2 bad input (missing file, bad config, missing secrets, oversized watchlist).
- Partial failure rule: more than half of symbols without a price means exit 1 and no post; at or below half, post with `n/a` rows.
- Discord caps: 4096 chars per embed description, 10 embeds, 6000 chars combined per message; the 6000 cap raises before posting.
- Percentages render `+0.82%` / `-1.30%` (sign, two decimals); prices `248.12`; missing values `n/a`; symbols uppercase.
- Colors: green `0x2ECC71`, red `0xE74C3C`, grey `0x95A5A6`. Footer text `Yahoo Finance`.
- Cron `35 13-21 * * 1-5`; secrets `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`; the token never appears in logs or error messages.
- Commit after each task with a conventional-commit message.

## Review Focus

Input classes the spec implies that a careless build would get wrong; each has a pinned test in the task that owns it:

1. DST: 13:35 UTC is 09:35 ET in July (open) but 08:35 ET in January (closed). Test in Task 4.
2. Early close: on 2026-11-27 the session ends 13:00 ET; 13:10 ET must still post (grace), 13:25 ET must not. Test in Task 4.
3. Holiday Monday: the week of Labor Day 2026 starts Tue Sep 8, so `week` compares to Tuesday's open. Test in Task 4.
4. Oversized watchlist: 200 symbols must raise a clear error locally, not a Discord 400. Test in Task 6.
5. Zero or missing reference price (halted stock, no trades yet): percentage is `n/a`, never a ZeroDivisionError. Test in Task 5.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `uv.lock` (generated), `src/stonksteller/__init__.py`, `.gitignore`, `.env.example`, `stonks.txt`, `config.toml`

**Interfaces:**
- Produces: importable package `stonksteller`; console script `stonks = "stonksteller.cli:main"` (module arrives in Task 8); dev dependency group `dev` with pytest.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "stonksteller"
version = "0.1.0"
description = "Posts an hourly watchlist snapshot to Discord during market hours"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "yfinance>=1.7",
    "exchange_calendars>=4.13",
    "requests>=2.32",
    "python-dotenv>=1.0",
    "tomli>=2.0; python_version < '3.11'",
]

[project.scripts]
stonks = "stonksteller.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/stonksteller"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `src/stonksteller/__init__.py`** containing `__version__ = "0.1.0"`.

- [ ] **Step 3: Write `.gitignore`**

Entries: `.env`, `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `*.egg-info/`, `dist/`, `build/`, `.ruff_cache/`, `.mypy_cache/`, `.idea/`, `.vscode/`, `.DS_Store`, `Thumbs.db`.

- [ ] **Step 4: Write `.env.example`**

```
DISCORD_BOT_TOKEN=paste-your-bot-token-here
DISCORD_CHANNEL_ID=123456789012345678
```

- [ ] **Step 5: Write `stonks.txt`** with a comment line explaining the format (one symbol per line, `#` starts a comment) followed by `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `TSLA`.

- [ ] **Step 6: Write `config.toml`** with every key at its default and a one-line comment each, exactly the keys in the spec's `[display]` block: `title = "Stonks"`, `columns = ["price", "open", "day", "week"]`, `sort = "file"`, `emoji = true`, `color_by = "open"`.

- [ ] **Step 7: Lock and install**

Run: `uv lock && uv sync && uv run python -c "import stonksteller, yfinance, exchange_calendars, requests, dotenv; print('ok')"`
Expected: `uv.lock` exists, output ends with `ok`.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/stonksteller/__init__.py .gitignore .env.example stonks.txt config.toml docs/
git commit -m "chore: scaffold stonksteller package, config, and design docs"
```

---

### Task 2: Watchlist parsing

**Files:**
- Create: `src/stonksteller/watchlist.py`
- Test: `tests/test_watchlist.py`

**Interfaces:**
- Produces: `class WatchlistError(ValueError)`; `read_watchlist(path: Path) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_watchlist.py -v`
Expected: FAIL, `ModuleNotFoundError: stonksteller.watchlist`.

- [ ] **Step 3: Implement `read_watchlist(path: Path) -> list[str]` in `src/stonksteller/watchlist.py`**

Strip text from `#` to end of line, trim, skip empties, uppercase, dedupe keeping first occurrence. Messages: `f"watchlist not found: {path}"`, `f"no symbols in {path}"`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_watchlist.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stonksteller/watchlist.py tests/test_watchlist.py
git commit -m "feat: parse stonks.txt watchlist"
```

---

### Task 3: Display config

**Files:**
- Create: `src/stonksteller/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `COLUMNS = ("price", "open", "day", "week")`, `PCT_COLUMNS = ("open", "day", "week")`; frozen dataclass `DisplayConfig(title: str = "Stonks", columns: tuple[str, ...] = COLUMNS, sort: str = "file", emoji: bool = True, color_by: str = "open")`; `class ConfigError(ValueError)`; `load_config(path: Path) -> DisplayConfig`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from stonksteller.config import ConfigError, DisplayConfig, load_config

def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "config.toml")
    assert cfg == DisplayConfig()
    assert (cfg.title, cfg.columns, cfg.sort, cfg.emoji, cfg.color_by) == (
        "Stonks", ("price", "open", "day", "week"), "file", True, "open")

def test_reads_values(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[display]\ntitle = "Watch"\ncolumns = ["price", "week"]\n'
        'sort = "week"\nemoji = false\ncolor_by = "day"\n')
    assert load_config(tmp_path / "config.toml") == DisplayConfig(
        title="Watch", columns=("price", "week"), sort="week", emoji=False, color_by="day")

@pytest.mark.parametrize("body", [
    '[display]\ncolour_by = "open"\n',              # unknown key
    '[dsplay]\ntitle = "x"\n',                       # unknown section
    '[display]\ncolumns = ["price", "volume"]\n',    # unknown column
    '[display]\ncolumns = ["price", "price"]\n',     # duplicate column
    '[display]\ncolumns = []\n',                     # no columns
    '[display]\nsort = "price"\n',                   # sort must be "file" or a pct column
    '[display]\ncolor_by = "price"\n',               # color_by must be a pct column
    '[display]\nemoji = "yes"\n',                    # wrong type
    '[display]\ntitle = ""\n',                       # empty title
    '[display\n',                                    # malformed TOML
])
def test_invalid_config_raises(tmp_path, body):
    (tmp_path / "config.toml").write_text(body)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "config.toml")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/stonksteller/config.py`**

Import `tomllib` with `tomli` fallback. `load_config` returns `DisplayConfig()` when the file is missing; wraps `TOMLDecodeError` in `ConfigError`; rejects any section other than `display` and any key not a dataclass field; validates types and the membership rules in the test comments; converts `columns` to a tuple. Every `ConfigError` message names the offending key.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stonksteller/config.py tests/test_config.py
git commit -m "feat: load and validate display config"
```

---

### Task 4: Market calendar helpers

**Files:**
- Create: `src/stonksteller/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Produces: `ET = ZoneInfo("America/New_York")`; `GRACE = timedelta(minutes=20)`; `get_calendar(start: str | None = None, end: str | None = None) -> ExchangeCalendar` (XNYS); `is_market_open(now: datetime, cal) -> bool` (raises `ValueError` on a naive datetime); `reference_session(today: date, cal) -> date` (today if a session, else the last session before it); `previous_session(session: date, cal) -> date`; `week_start_session(session: date, cal) -> date` (first session of the Monday-to-Sunday week containing `session`).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_market.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/stonksteller/market.py`**

Use `exchange_calendars.get_calendar("XNYS", start=..., end=...)`. `is_market_open`: convert `now` to ET date, `cal.is_session(pd.Timestamp(d))`, then compare `pd.Timestamp(now)` against `cal.session_open(d)` and `cal.session_close(d) + GRACE`. `reference_session`: `cal.date_to_session(d, direction="previous").date()`. `previous_session`: `cal.previous_session(d).date()`. `week_start_session`: `cal.date_to_session(monday, direction="next").date()` where `monday = session - timedelta(days=session.weekday())`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_market.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stonksteller/market.py tests/test_market.py
git commit -m "feat: NYSE market-hours and session helpers"
```

---

### Task 5: Quotes

**Files:**
- Create: `src/stonksteller/quotes.py`
- Test: `tests/test_quotes.py`

**Interfaces:**
- Produces: frozen dataclass `Quote(symbol: str, price: float | None = None, open: float | None = None, prev_close: float | None = None, week_open: float | None = None)` with properties `pct_open`, `pct_day`, `pct_week` (`float | None`, percent units); `pct_change(price: float | None, ref: float | None) -> float | None`; `quotes_from_history(history: pd.DataFrame, symbols: Sequence[str], today: date, week_start: date, prev_session: date) -> list[Quote]` (pure, same order as `symbols`); `merge_fast_info(quote: Quote, last_price: float | None, open_: float | None, prev_close: float | None) -> Quote`; `fetch_quotes(symbols: Sequence[str], today: date, week_start: date, prev_session: date) -> list[Quote]` (network).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_quotes.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement the pure parts of `src/stonksteller/quotes.py`**

`pct_change`: `(price / ref - 1) * 100`, `None` if either is `None` or `ref <= 0`. `quotes_from_history`: normalize the index (drop tz if present, `.normalize()`, compare by `.date()`), take the `(symbol, "Open")` / `(symbol, "Close")` columns when the symbol is in level 0 of the columns, read a cell as `float` or `None` when the row is absent or NaN; `price` and `open` from the `today` row, `prev_close` from the `prev_session` row's Close, `week_open` from the `week_start` row's Open. `merge_fast_info` replaces only `None` fields with non-`None` arguments.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_quotes.py -v`
Expected: 7 passed.

- [ ] **Step 5: Implement `fetch_quotes` (network, no unit test)**

Call `yfinance.download(list(symbols), period="1mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)`, pass the frame to `quotes_from_history`, then for each quote whose `price` is `None` but whose `prev_close` or `week_open` is set (a known symbol with no in-progress row), read `yfinance.Ticker(symbol).fast_info` keys `last_price`, `open`, `regular_market_previous_close` inside a `try` that logs a warning and leaves the quote unchanged on any exception, and merge with `merge_fast_info`. Log one warning line listing symbols that ended with no price.

- [ ] **Step 6: Commit**

```bash
git add src/stonksteller/quotes.py tests/test_quotes.py
git commit -m "feat: compute quotes and changes from Yahoo daily history"
```

---

### Task 6: Rendering

**Files:**
- Create: `src/stonksteller/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `Quote` and `pct_change` semantics from Task 5; `DisplayConfig`, `PCT_COLUMNS` from Task 3.
- Produces: `GREEN = 0x2ECC71`, `RED = 0xE74C3C`, `GREY = 0x95A5A6`, `ROWS_PER_EMBED = 25`, `MAX_DESCRIPTION = 4096`, `MAX_MESSAGE = 6000`, `FOOTER = "Yahoo Finance"`; `class WatchlistTooLarge(ValueError)`; `format_price(value: float | None) -> str`; `format_pct(value: float | None) -> str`; `pct_for(quote: Quote, column: str) -> float | None`; `sort_quotes(quotes: Sequence[Quote], sort: str) -> list[Quote]`; `render_table(quotes: Sequence[Quote], config: DisplayConfig) -> list[str]` (header line then one line per quote, no fences); `mood_color(quotes: Sequence[Quote], color_by: str) -> int`; `title_for(config: DisplayConfig, now: datetime) -> str`; `build_embeds(quotes: Sequence[Quote], config: DisplayConfig, now: datetime) -> list[dict]`; `render_text(quotes: Sequence[Quote], config: DisplayConfig, now: datetime) -> str` (title, blank line, table lines; for dry runs).

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from stonksteller.config import DisplayConfig
from stonksteller.quotes import Quote
from stonksteller.render import (GREEN, GREY, RED, WatchlistTooLarge, build_embeds, format_pct,
                                 format_price, mood_color, render_table, render_text, sort_quotes)

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

def test_table_emoji_and_column_selection():
    lines = render_table([AAPL, NVDA, FAKE], DisplayConfig(columns=("price", "week"), color_by="week"))
    assert lines[0] == "SYM    PRICE    WEEK"
    assert lines[1] == "AAPL  343.46  +1.55% 🟢"
    assert lines[2] == "NVDA  214.13  -6.38% 🔴"
    assert lines[3] == "FAKE     n/a     n/a ⚪"

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
    assert embed["description"].startswith("```\nSYM") and embed["description"].endswith("\n```")
    assert embed["color"] == RED
    assert embed["footer"] == {"text": "Yahoo Finance"}
    assert embed["timestamp"] == "2026-10-16T15:35:00+00:00"

def test_splits_into_several_embeds():
    quotes = [Quote(f"S{i:03d}", 10.0, 10.0, 10.0, 10.0) for i in range(60)]
    embeds = build_embeds(quotes, DisplayConfig(), NOW)
    assert len(embeds) == 3
    assert "title" in embeds[0] and "title" not in embeds[1] and "title" not in embeds[2]
    assert "footer" in embeds[2] and "footer" not in embeds[0] and "footer" not in embeds[1]
    assert all(e["description"].startswith("```\nSYM") for e in embeds)
    assert embeds[1]["description"].count("\nS0") == 25
    assert all(e["color"] == GREY for e in embeds)

def test_too_many_symbols_raises_before_posting():
    quotes = [Quote(f"S{i:03d}", 10.0, 10.0, 10.0, 10.0) for i in range(200)]
    with pytest.raises(WatchlistTooLarge, match="6000"):
        build_embeds(quotes, DisplayConfig(), NOW)

def test_render_text_for_dry_run():
    lines = render_text([AAPL], DisplayConfig(emoji=False), NOW).splitlines()
    assert lines[0] == "Stonks · Fri Oct 16 · 11:35 ET"
    assert lines[1] == ""
    assert lines[2] == "SYM    PRICE    OPEN     DAY    WEEK"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/stonksteller/render.py`**

Table: header cells are `SYM` then each configured column uppercased; cell text via `format_price` / `format_pct`; column widths are the max cell length per column; symbol column left-justified, all others right-justified; cells joined by two spaces; when `config.emoji` is on, each data row gets a trailing space plus `🟢` (positive), `🔴` (negative) or `⚪` (zero or `n/a`) judged on `config.color_by`. `sort_quotes`: `"file"` keeps order; a column sorts descending by `pct_for`, `None` last, stable. `mood_color`: count positive vs negative on `color_by`; green if more positive, red if more negative, else grey. `title_for`: `f"{config.title} · {t:%a %b} {t.day} · {t:%H:%M} ET"` with `t = now.astimezone(ET)`. `build_embeds`: sort, render the table once, chunk data rows in groups of `ROWS_PER_EMBED`, each embed's description is a fenced block (```` ``` ```` + newline + header + rows + newline + ```` ``` ````) with the color on every embed, title only on the first, footer and `timestamp` (`now.astimezone(timezone.utc).isoformat()`) only on the last; then raise `WatchlistTooLarge` if any description exceeds `MAX_DESCRIPTION` or the sum of title, description and footer lengths across embeds exceeds `MAX_MESSAGE`, with a message that includes `6000` and the number of symbols that would fit (`MAX_MESSAGE // (row_length + 1)`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_render.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stonksteller/render.py tests/test_render.py
git commit -m "feat: render quotes as a Discord embed table"
```

---

### Task 7: Discord posting

**Files:**
- Create: `src/stonksteller/discord.py`
- Test: `tests/test_discord.py`

**Interfaces:**
- Produces: `API_BASE = "https://discord.com/api/v10"`; `class DiscordError(Exception)`; `post_message(token: str, channel_id: str, embeds: list[dict], *, session=None, sleep=time.sleep) -> None` where `session` is anything with `requests.Session`-style `post(url, json=..., headers=..., timeout=...)`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from stonksteller.discord import DiscordError, post_message

class FakeResponse:
    def __init__(self, status_code, text="", retry_after=None):
        self.status_code, self.text = status_code, text
        self.headers = {"Retry-After": retry_after} if retry_after else {}
    def json(self):
        import json
        return json.loads(self.text)

class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def post(self, url, *, json, headers, timeout):
        self.calls.append((url, json, headers, timeout))
        return self.responses.pop(0)

def post(session, embeds=None):
    slept = []
    post_message("tok", "123", embeds or [], session=session, sleep=slept.append)
    return slept

def test_posts_embeds_with_bot_auth():
    s = FakeSession([FakeResponse(200)])
    post(s, [{"title": "x"}])
    url, body, headers, timeout = s.calls[0]
    assert url == "https://discord.com/api/v10/channels/123/messages"
    assert body == {"embeds": [{"title": "x"}]}
    assert headers["Authorization"] == "Bot tok"
    assert timeout > 0

def test_retries_once_on_429_honoring_retry_after():
    s = FakeSession([FakeResponse(429, '{"retry_after": 1.5}', retry_after="1.5"), FakeResponse(200)])
    assert post(s) == [1.5]
    assert len(s.calls) == 2

def test_retries_once_on_5xx():
    s = FakeSession([FakeResponse(502, "bad gateway"), FakeResponse(200)])
    post(s)
    assert len(s.calls) == 2

def test_raises_after_failed_retry():
    s = FakeSession([FakeResponse(500, "boom"), FakeResponse(500, "boom")])
    with pytest.raises(DiscordError, match="500"):
        post(s)

def test_other_4xx_raises_without_retry_and_without_token():
    s = FakeSession([FakeResponse(403, '{"message": "Missing Access"}')])
    with pytest.raises(DiscordError, match="Missing Access") as exc:
        post(s)
    assert len(s.calls) == 1
    assert "tok" not in str(exc.value)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_discord.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/stonksteller/discord.py`**

Default `session` is `requests.Session()`. Headers: `Authorization: Bot {token}`, `User-Agent: StonksTeller (https://github.com/GabrielYamin/StonksTeller, 0.1.0)`. Timeout 15 seconds. On 429: wait `retry_after` from the JSON body, else the `Retry-After` header, else 1.0, then retry once. On 5xx: wait 2.0, retry once. Any other non-2xx, or a failed retry, raises `DiscordError(f"Discord returned {status}: {text[:500]}")`. The token is never interpolated into any message.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_discord.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stonksteller/discord.py tests/test_discord.py
git commit -m "feat: post embeds to a Discord channel with retry"
```

---

### Task 8: CLI

**Files:**
- Create: `src/stonksteller/cli.py`, `src/stonksteller/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `read_watchlist`, `load_config`, `get_calendar`, `is_market_open`, `reference_session`, `previous_session`, `week_start_session`, `fetch_quotes`, `build_embeds`, `render_text`, `WatchlistTooLarge`, `post_message`, `DiscordError`, `ET`. All imported by name into `cli` so tests can monkeypatch `stonksteller.cli.<name>`.
- Produces: `EXIT_OK = 0`, `EXIT_FAILURE = 1`, `EXIT_USAGE = 2`; `build_parser() -> argparse.ArgumentParser` with `--dry-run`, `--force`, `--watchlist PATH` (default `stonks.txt`), `--config PATH` (default `config.toml`); `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from stonksteller import cli
from stonksteller.discord import DiscordError
from stonksteller.market import get_calendar
from stonksteller.quotes import Quote

CAL = get_calendar()
AAPL = Quote("AAPL", 343.46, 346.09, 342.00, 338.22)

def boom(*args, **kwargs):
    raise AssertionError("must not be called")

@pytest.fixture
def workdir(tmp_path, monkeypatch):
    (tmp_path / "stonks.txt").write_text("AAPL\nFAKE\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(cli, "get_calendar", lambda: CAL)
    monkeypatch.setattr(cli, "is_market_open", lambda now, cal: True)
    monkeypatch.setattr(cli, "fetch_quotes", lambda symbols, today, week_start, prev_session: [AAPL, Quote("FAKE")])
    return tmp_path

@pytest.fixture
def posted(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "post_message", lambda token, channel_id, embeds: calls.append((token, channel_id, embeds)))
    return calls

def test_posts_when_market_open(workdir, posted):
    assert cli.main([]) == 0
    token, channel, embeds = posted[0]
    assert (token, channel, len(embeds)) == ("tok", "123", 1)

def test_market_closed_exits_zero_without_fetching(workdir, posted, monkeypatch):
    monkeypatch.setattr(cli, "is_market_open", lambda now, cal: False)
    monkeypatch.setattr(cli, "fetch_quotes", boom)
    assert cli.main([]) == 0 and posted == []

def test_force_skips_market_check(workdir, posted, monkeypatch):
    monkeypatch.setattr(cli, "is_market_open", lambda now, cal: False)
    assert cli.main(["--force"]) == 0 and len(posted) == 1

def test_dry_run_prints_table_and_needs_no_secrets(workdir, monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_BOT_TOKEN"); monkeypatch.delenv("DISCORD_CHANNEL_ID")
    monkeypatch.setattr(cli, "post_message", boom)
    assert cli.main(["--dry-run"]) == 0
    assert "AAPL  343.46" in capsys.readouterr().out

def test_missing_secrets_exit_2_before_fetching(workdir, posted, monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN")
    monkeypatch.setattr(cli, "fetch_quotes", boom)
    assert cli.main([]) == 2 and posted == []

def test_dotenv_in_cwd_is_loaded(workdir, posted, monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN"); monkeypatch.delenv("DISCORD_CHANNEL_ID")
    (workdir / ".env").write_text("DISCORD_BOT_TOKEN=filetok\nDISCORD_CHANNEL_ID=999\n")
    assert cli.main([]) == 0 and posted[0][:2] == ("filetok", "999")

def test_missing_watchlist_exit_2(workdir, posted):
    (workdir / "stonks.txt").unlink()
    assert cli.main([]) == 2 and posted == []

def test_bad_config_exit_2(workdir, posted):
    (workdir / "config.toml").write_text('[display]\nsort = "price"\n')
    assert cli.main([]) == 2 and posted == []

def test_more_than_half_failed_exit_1_without_posting(workdir, posted, monkeypatch):
    (workdir / "stonks.txt").write_text("A\nB\nC\n")
    monkeypatch.setattr(cli, "fetch_quotes", lambda *a: [Quote("A", 1.0, 1.0, 1.0, 1.0), Quote("B"), Quote("C")])
    assert cli.main([]) == 1 and posted == []

def test_exactly_half_failed_still_posts(workdir, posted):
    assert cli.main([]) == 0 and len(posted) == 1

def test_fetch_exception_exit_1(workdir, posted, monkeypatch):
    def raise_(*a): raise RuntimeError("yahoo down")
    monkeypatch.setattr(cli, "fetch_quotes", raise_)
    assert cli.main([]) == 1 and posted == []

def test_discord_error_exit_1(workdir, monkeypatch):
    def raise_(*a, **k): raise DiscordError("Discord returned 403: Missing Access")
    monkeypatch.setattr(cli, "post_message", raise_)
    assert cli.main([]) == 1

def test_oversized_watchlist_exit_2(workdir, posted, monkeypatch):
    symbols = [f"S{i:03d}" for i in range(200)]
    (workdir / "stonks.txt").write_text("\n".join(symbols) + "\n")
    monkeypatch.setattr(cli, "fetch_quotes", lambda syms, *a: [Quote(s, 10.0, 10.0, 10.0, 10.0) for s in syms])
    assert cli.main([]) == 2 and posted == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/stonksteller/cli.py` and `__main__.py`**

`main` order: configure logging to stderr (`%(levelname)s %(message)s`, INFO); `load_dotenv(Path.cwd() / ".env")` (default `override=False` so CI env wins); parse args; `read_watchlist` and `load_config` (errors log and return 2); unless `--dry-run`, read both env vars and return 2 if either is missing; `cal = get_calendar()`, `now = datetime.now(ET)`; unless `--force`, return 0 with an info log when `not is_market_open(now, cal)`; `today = reference_session(now.date(), cal)`, `week_start = week_start_session(today, cal)`, `prev = previous_session(today, cal)`; `fetch_quotes(symbols, today, week_start, prev)` (any exception logs and returns 1); count quotes with `price is None` and return 1 with a log naming them when `failed * 2 > len(quotes)`; `build_embeds` (`WatchlistTooLarge` logs and returns 2); on `--dry-run` print `render_text(...)` and return 0; `post_message(token, channel_id, embeds)` (`DiscordError` logs and returns 1); log `posted N symbols` and return 0. `__main__.py` is `raise SystemExit(main())`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q`
Expected: all tests pass (13 in this file).

- [ ] **Step 5: Check the console script and module entry**

Run: `uv run stonks --help && uv run python -m stonksteller --help`
Expected: both print usage listing `--dry-run`, `--force`, `--watchlist`, `--config`.

- [ ] **Step 6: Commit**

```bash
git add src/stonksteller/cli.py src/stonksteller/__main__.py tests/test_cli.py
git commit -m "feat: stonks CLI with market check, dry run, and exit codes"
```

---

### Task 9: GitHub Actions workflows

**Files:**
- Create: `.github/workflows/post.yml`, `.github/workflows/test.yml`

**Interfaces:**
- Consumes: console script `stonks` and its `--dry-run` / `--force` flags from Task 8; `uv.lock` from Task 1.

- [ ] **Step 1: Write `.github/workflows/post.yml`**

```yaml
name: Post stonks

on:
  schedule:
    - cron: "35 13-21 * * 1-5"   # hourly 13:35–21:35 UTC Mon–Fri; the script skips closed hours
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Print the message in the log instead of posting"
        type: boolean
        default: false
      force:
        description: "Skip the market-hours check"
        type: boolean
        default: false

permissions:
  contents: read

concurrency:
  group: post
  cancel-in-progress: false

jobs:
  post:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.12"
          enable-cache: true
      - run: uv sync --frozen --no-dev
      - name: Post to Discord
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_CHANNEL_ID: ${{ secrets.DISCORD_CHANNEL_ID }}
        run: >-
          uv run --frozen --no-dev stonks
          ${{ inputs.dry_run == true && '--dry-run' || '' }}
          ${{ inputs.force == true && '--force' || '' }}
```

- [ ] **Step 2: Write `.github/workflows/test.yml`**

Name `Tests`; triggers `push` and `pull_request`; `permissions: contents: read`; one job on `ubuntu-latest` with the same checkout and setup-uv steps, then `uv sync --frozen` and `uv run --frozen pytest -q`.

- [ ] **Step 3: Validate the YAML and the frozen lock**

Run: `uv run --with pyyaml python -c "import yaml; p=yaml.safe_load(open('.github/workflows/post.yml')); t=yaml.safe_load(open('.github/workflows/test.yml')); assert p[True]['schedule'][0]['cron']=='35 13-21 * * 1-5'; assert 'dry_run' in p[True]['workflow_dispatch']['inputs']; assert set(t[True])=={'push','pull_request'}; print('ok')" && uv sync --frozen && echo lock-ok`
Expected: `ok` then `lock-ok`. (PyYAML parses the bare `on:` key as boolean `True`.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/post.yml .github/workflows/test.yml
git commit -m "ci: scheduled Discord post and test workflows"
```

---

### Task 10: README and end-to-end dry run

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above; documents the user-facing surface only.

- [ ] **Step 1: Write `README.md`** with these sections, in this order:

1. One-paragraph description and the example message block from the spec's Display section.
2. **Quick start (local):** clone; `uv sync`; `cp .env.example .env` and fill it; `uv run stonks --dry-run`; `uv run stonks --force` to post right now. A two-line alternative without uv: `python -m venv .venv`, activate, `pip install -e .`, then `stonks --dry-run`.
3. **Creating the Discord bot:** Developer Portal, New Application, Bot tab, Reset Token and copy it; OAuth2 URL Generator with scope `bot` and permissions View Channel, Send Messages, Embed Links (permissions integer `19456`); open the URL to invite it; enable Developer Mode in Discord settings, right-click the channel, Copy Channel ID.
4. **Running on GitHub Actions:** Settings, Secrets and variables, Actions, add `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID`; the schedule and what it means (hourly 9:35 to 15:35 ET, seven posts per trading day, fires at closed UTC hours on purpose, 20-minute grace, runs may start a few minutes late); manual runs from the Actions tab with the `dry_run` and `force` checkboxes.
5. **Watchlist (`stonks.txt`)** format rules from the spec.
6. **Display config (`config.toml`)** table of the five keys, allowed values, defaults.
7. **Behaviour and limits:** exit codes; the more-than-half failure rule; the ~100 symbol ceiling; data is Yahoo Finance and may lag.
8. **Troubleshooting:** scheduled workflows pause after 60 days without commits (push anything to resume); `403 Missing Access` means the bot isn't in the channel; yfinance breaking after a Yahoo change (`uv lock --upgrade-package yfinance`, run tests, commit the lock).

- [ ] **Step 2: Run the real pipeline in dry-run mode**

Run: `uv run stonks --dry-run --force`
Expected: exit 0; stdout shows the title line and a table with one row per symbol in `stonks.txt`, prices populated (on a weekend, the last session's closing values). Paste the first four lines of output into the commit message body.

- [ ] **Step 3: Run the whole suite one last time**

Run: `uv run pytest -q`
Expected: all passed, 0 failed.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, config, schedule, and troubleshooting"
```
