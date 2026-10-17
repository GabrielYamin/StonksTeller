# StonksTeller design

Date: 2026-10-17
Status: approved in conversation; written up for the builder.

## Intent

A GitHub Actions job that, every hour while the US stock market is open,
reads a watchlist from `stonks.txt` and posts one Discord message showing
each symbol's price and how it has moved since today's open, since the
previous close, and since the start of the week. The same script must run
on a developer's machine with a `.env` file. There is no server, database,
or hosted backend of any kind: the job fetches data, makes one HTTP call
to Discord, and exits.

The user wants a glanceable hourly pulse of their watchlist in a channel
they already look at. Nothing to open, nothing to host.

## Goals

- `stonks.txt`, one symbol per line, is the only thing you edit to change
  what gets reported.
- Each run posts one message containing a monospace table: symbol, price,
  % vs today's open, % vs previous close, % vs week start.
- Runs on a schedule in GitHub Actions and on demand from the Actions
  page. Runs locally with the same command.
- Skips silently (exit 0, no post) when the market is closed: weekends,
  NYSE holidays, outside session hours, after an early close.
- A small config file in the repo controls which columns show, sort
  order, and whether rows carry a green/red emoji.
- The webhook URL never lives in the repo: `.env` locally, a GitHub
  Actions secret in CI.

## Non-goals

- Interactive Discord components (buttons, selects). Discord delivers
  clicks over HTTP and needs a reply within 3 seconds; a scheduled Action
  can't receive that. Decided: no buttons for now. The code is structured
  so a later interaction endpoint (for example a Cloudflare Worker) can
  reuse the data and rendering modules unchanged.
- Charts, images, sparkline rendering.
- Threshold alerts ("tell me when NVDA drops 5%").
- Exchanges other than NYSE/Nasdaq. Symbols with Yahoo suffixes may happen
  to work, but the market-hours check is NYSE only.
- Any persistence between runs. No message editing, no state files, no
  caching across runs.

## Anti-goals (what would make this a failure even if it "works")

- Posting when the market is closed, or posting twice for one hour.
- A single bad symbol (typo, delisting) killing the whole post.
- Posting a message full of stale or empty numbers when Yahoo is down.
  Total data failure must fail the job loudly and post nothing.
- Spamming the channel: exactly one message per successful run.
- Leaking the webhook URL into logs or the repo.

## Constraints

- GitHub Actions `schedule` is UTC-only and has no DST awareness, and
  scheduled runs are routinely delayed 3 to 15 minutes, worst at the top
  of the hour.
- GitHub disables scheduled workflows on repos with no commits for 60
  days. Document this; nothing to build.
- Discord embed description limit is 4096 characters, a message may carry
  up to 10 embeds, and the combined length of all embeds in one message is
  capped at 6000 characters. That last cap is the binding one: at roughly
  45 characters per row it allows about 100 symbols per message. Discord
  webhook rate limits are far above one call an hour.
- Local Python is 3.10. Code must run on 3.10 and newer.
- No paid services, no API keys beyond the Discord webhook URL.

## Decisions (made by the user, or marked as my call)

### Data source: Yahoo Finance via `yfinance`

My call, accepted by the user. No key, one batched request for all
symbols. Unofficial; breaks occasionally when Yahoo changes something and
the library patches it. The data-fetching module is the only place that
knows about yfinance, so swapping to Finnhub later is one file.

Freshness: Yahoo's US quotes are real-time or near it for NYSE/Nasdaq.
The footer says "Yahoo Finance" so nobody mistakes it for a broker feed.

### The numbers

For each symbol, all computed in `America/New_York`:

| Column | Meaning |
|--------|---------|
| `price` | Latest traded price. |
| `open` | `(price / today's open) - 1`. |
| `day` | `(price / previous session's close) - 1`. My call to include; it is what most people mean by "today's change". |
| `week` | `(price / week-start open) - 1`, where week start is the first NYSE session of the current Monday-to-Sunday week in ET. On the week's first session this equals `open`. |

Percentages render with a sign and two decimals: `+0.82%`, `-1.30%`.
Prices render with two decimals. Symbols are uppercased.

A symbol whose data can't be fetched renders as a row with the symbol
and `n/a` in every other column. A symbol whose current-day row is
missing (no trades yet) gets `n/a` in the columns that depend on it.

Partial failure rule (my call): if more than half of the symbols have no
price at all, treat it as a data outage: log which symbols failed, exit
1, post nothing. At or below half, post with `n/a` rows. So a watchlist
with one or two typos still posts, while a Yahoo outage, which fails
most symbols at once, never produces a table of dashes in the channel.

### Watchlist file: `stonks.txt`

One symbol per line. Blank lines and lines starting with `#` are ignored.
Whitespace is trimmed. Duplicate symbols are reported once, keeping the
first position. Order in the file is the default display order.
An empty or missing file is an error (exit 2), not an empty post.

### Display

One Discord message per run, built from embeds, no plain-text content.

Changed after the first build (2026-10-17): the user found a single
trailing light ambiguous and the monospace table unreadable on phones
(Discord mobile wraps code-block lines at roughly 35 characters). A
one-line-per-symbol proportional layout was tried next and rejected from a
phone screenshot: Discord collapses the spacing and the emoji glyphs crowd
the numbers. The default is now Discord's own grid: inline embed fields.

- Title: `Stonks · Fri Oct 17 · 11:35 ET` (the fetch time, in ET).
- `layout = "cards"` (default): one inline field per symbol, no
  description. Field name is the symbol; the value is one line per
  configured column in order: the price as a bare number, and each
  percentage as light, value, label (`🟢 +0.43% day`). Discord lays
  inline fields out three across, on desktop and on phones, and each card
  is self-contained so nothing has to align across cards.
- `layout = "table"`: a fenced code block holding an aligned table with a
  header row; each percentage cell is the light immediately followed by
  the value (`🟢+1.55%`). Desktop only in practice.
- Lights: `🟢` positive, `🔴` negative, `⚪` zero or n/a. `emoji = false`
  removes them in both layouts.
- Embed color: green `0x2ECC71` if more symbols are positive than
  negative on the `color_by` column, red `0xE74C3C` if more are negative,
  grey `0x95A5A6` on a tie or all-n/a.
- Footer text: `Yahoo Finance`. Embed `timestamp` set to the fetch time
  so Discord shows a localized time to each reader.
- Chunking: 25 symbols per embed (Discord's field limit, and a sensible
  table height); only the first embed carries the title and only the last
  the footer. If the message would exceed Discord's 6000-character cap
  (counted over titles, descriptions, footers, and field names and
  values), the run fails with exit 2 and a message naming the cap and the
  approximate symbol limit; nothing is posted and nothing is truncated.
  One message per run is an anti-goal worth keeping, and a watchlist past
  ~100 symbols is not what this tool is for. The README documents the
  ceiling.

Example as it should look in Discord:

```
Stonks · Fri Oct 17 · 11:35 ET

AAPL                NVDA                TSLA
248.12              182.40              431.05
🟢 +0.82% open      🔴 -1.31% open      🔴 -2.20% open
🟢 +1.30% day       🔴 -0.44% day       🔴 -2.90% day
🟢 +2.14% week      🟢 +4.70% week      🔴 -3.91% week

Yahoo Finance · Today at 11:35
```

### Config file: `config.toml`

Lives in the repo root next to `stonks.txt`. Missing file means all
defaults. Unknown keys are an error so typos don't silently do nothing.

```toml
[display]
title = "Stonks"                      # embed title prefix
columns = ["price", "open", "day", "week"]  # which, and in what order
sort = "file"                         # "file", or a percentage column name;
                                      # column sorts descending (biggest gain first)
emoji = true
color_by = "open"                     # column driving the embed color
layout = "cards"                      # "cards" (inline fields) or "table" (monospace)
```

`color_by` must be a percentage column; it need not be in `columns`.
`sort` by a column puts n/a rows last.

### Posting: channel webhook

Changed after the first build (2026-10-17): the user chose a webhook over a
bot. With buttons out of scope, a webhook is simpler: one secret, no
application to create, no invite or permission setup, and the display
name and avatar are set on the webhook itself.

- `POST {DISCORD_WEBHOOK_URL}?wait=true` with a JSON body
  `{"embeds": [...]}`. `wait=true` makes Discord return the created
  message (200) instead of a bare 204, so validation errors surface.
- The URL is validated before any fetching: it must be
  `https://<discord host>/api/webhooks/<id>/<token>`, else exit 2.
- Non-2xx response: log status and body, exit 1. One retry on HTTP 429
  honoring `retry_after`, one retry on 5xx. Network exceptions are
  reported by class name only, because `requests` puts the URL, which is
  the secret, in its messages.
- If interactive components are ever wanted, they need a bot token plus an
  interaction endpoint; the posting module is the only file to change.

Each run posts a fresh message; the channel becomes a log. Editing a
single message in place was considered and rejected for now (needs state
between runs).

### Secrets and local run

Environment variable `DISCORD_WEBHOOK_URL`. The
CLI loads `.env` from the current directory if present (python-dotenv)
and never writes it. `.env.example` is committed with placeholder values;
`.env` is gitignored.

CLI:

```
stonks                 # fetch, check market, post
stonks --dry-run       # fetch, print the rendered table to stdout, don't post;
                       # webhook URL not required
stonks --force         # skip the market-hours check (combinable)
stonks --watchlist PATH --config PATH   # defaults: ./stonks.txt, ./config.toml
```

Exit codes: 0 success or market closed; 1 data or Discord failure;
2 bad input (missing file, bad config, missing or malformed webhook URL).

Logs go to stderr, one line per notable event, never including the webhook URL.

### Market-hours check

Uses the `exchange_calendars` library, calendar `XNYS`, which knows
holidays and early closes. "Open" means: now (ET) is on or after today's
session open and before session close plus a 20-minute grace period. The
grace absorbs GitHub's scheduling delay so the last run of the day
(15:35 ET) still posts if it fires late. The `--force` flag bypasses the
check entirely.

The check is a pure function of (now, calendar) so tests can pin any
instant.

### Schedule

```yaml
on:
  schedule:
    - cron: "35 13-21 * * 1-5"   # every hour 13:35–21:35 UTC, Mon–Fri
  workflow_dispatch:
    inputs:
      dry_run: { type: boolean, default: false }
      force:   { type: boolean, default: false }
```

Why 13–21: 9:35 ET is 13:35 UTC in summer and 14:35 UTC in winter;
15:35 ET is 19:35 UTC in summer and 20:35 UTC in winter. Firing the whole
range year-round and letting the script decline the closed hours is
simpler than two cron lines and a DST flip. Expected posts per full
trading day: seven (9:35 through 15:35 ET). The `:35` minute dodges the
top-of-hour congestion.

The job sets `concurrency: { group: post, cancel-in-progress: false }`
so two delayed firings can't overlap, and `timeout-minutes: 10`.

The webhook URL is passed as an environment variable to the single run step only.

### Repo layout and tooling

- Python package `stonksteller` under `src/`, console script `stonks`.
- `pyproject.toml` with dependencies; `uv.lock` committed; GitHub Actions
  uses `astral-sh/setup-uv` with caching and `uv sync --frozen`. README
  also shows the plain `pip install -e .` route for people without uv.
- Dependencies: `yfinance`, `exchange_calendars`, `requests` (or
  `httpx`), `python-dotenv`, `tomli` only on Python < 3.11.
- Tests with `pytest`. A second workflow `test.yml` runs them on push and
  pull request.
- Modules, each with a single job: watchlist parsing, config loading,
  market check, quote fetching (the only yfinance import), rendering
  (quotes in, embeds out, pure), Discord posting (the only network call to
  Discord), CLI wiring.
- `.gitignore` for Python: `.env`, `.venv/`, `__pycache__/`,
  `.pytest_cache/`, `*.egg-info/`, `dist/`, `.ruff_cache/`, `.mypy_cache/`,
  and editor/OS droppings.
- `README.md`: what it does with the example above, Discord webhook setup
  step by step, local run, GitHub setup (which two secrets, how to
  trigger a manual run), config reference, how the schedule works and why
  it fires at closed hours, troubleshooting (scheduled workflows disabled
  after 60 days of inactivity, run delays, yfinance breakage).
- A sample `stonks.txt` with a handful of well-known symbols so the first
  run works out of the box.

## Left to the builder

- Exact yfinance calls, as long as it's one batched request for daily
  history and the module exposes a plain dataclass per symbol with
  `price`, `open`, `prev_close`, `week_open`, any of which may be `None`.
- Exact column widths and spacing in the table.
- Whether to use `requests` or `httpx`.
- Pinning action versions by tag or SHA.
- Test layout and fixtures. Network calls are not exercised in tests;
  `--dry-run` is the manual smoke test.

## Recon notes for the builder (verified 2026-10-17)

Facts checked against live libraries in a scratch environment, so the
plan doesn't rest on memory.

- Versions at time of writing: yfinance 1.7.0, exchange_calendars 4.13.2,
  pandas 2.3.3, python-dotenv 1.2.4, requests 2.34.2, pytest 9.1.1.
  Latest action majors: `actions/checkout@v7`, `astral-sh/setup-uv@v10`.
- `yf.download([...], period="10d", interval="1d", group_by="ticker",
  auto_adjust=False, progress=False)` returns one frame with a
  `(symbol, field)` column MultiIndex. The index is tz-naive calendar
  dates in exchange-local time, so they compare directly to the ET date.
  An unknown symbol does not raise; its sub-frame is all NaN and yfinance
  logs "No data found, symbol may be delisted" to its logger. Detect
  failure as "no non-NaN Close".
- During market hours Yahoo's daily series includes the in-progress
  session as the last row: its `Open` is today's open and its `Close` is
  the live price. This could not be observed on a Saturday; if the last
  row's date is not today (ET), fall back to `yf.Ticker(sym).fast_info`,
  which exposes `last_price`, `open`, and
  `regular_market_previous_close` (use that one, not `previous_close`,
  which is an adjusted figure and did not match the daily series).
- exchange_calendars: `cal = get_calendar("XNYS")`;
  `cal.is_session(date)`; `cal.session_open(date)` /
  `cal.session_close(date)` return UTC timestamps and raise
  `NotSessionError` on a non-session; `cal.previous_session(date)`;
  `cal.date_to_session(date, direction="next")` finds the first session
  of a week given its Monday (Labor Day 2026 resolves to Tue Sep 8).
  Early closes are modeled (2026-11-27 closes 13:00 ET).
- Today's ET date must be derived from `datetime.now(ZoneInfo("America/New_York"))`,
  never from the runner's local clock, which is UTC on GitHub.
