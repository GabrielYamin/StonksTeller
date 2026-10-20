# StonksTeller

Posts an hourly snapshot of your stock watchlist to a Discord channel while the US market is open. No server, no database: a GitHub Actions job reads `stonks.txt`, fetches prices from Yahoo Finance, and makes one API call to Discord. The same command runs on your machine.

What a post looks like. Discord shows a small card per symbol, three across on desktop and on phones:

```
Stonks · Fri Oct 17 · 11:35 ET

AAPL                NVDA                TSLA
248.12              182.40              431.05
🟢 +0.82% open      🔴 -1.31% open      🔴 -2.20% open
🟢 +1.30% day       🔴 -0.44% day       🔴 -2.90% day
🟢 +2.14% week      🟢 +4.70% week      🔴 -3.91% week

Yahoo Finance · Today at 11:35
```

Each percentage carries its own light and label: **open** is the change since today's open, **day** since the previous close, **week** since the open of the week's first session. The embed is green when more symbols are up than down on the `color_by` column, red when the reverse, grey on a tie.

Prefer a monospace grid? Set `layout = "table"` in `config.toml`. It aligns nicely on desktop but Discord mobile wraps code blocks at about 35 characters, which breaks the rows.

## Quick start (local)

Needs [uv](https://docs.astral.sh/uv/). Python 3.10+ is used if present, otherwise uv downloads one.

```bash
git clone https://github.com/GabrielYamin/StonksTeller.git
cd StonksTeller
uv sync
cp .env.example .env      # then paste your webhook URL into .env
uv run stonks --dry-run   # prints the table, posts nothing, needs no secrets
uv run stonks --force     # posts right now, even if the market is closed
```

Without uv:

```bash
python -m venv .venv && source .venv/bin/activate    # .venv\Scripts\activate on Windows
pip install -e .
stonks --dry-run
```

Flags: `--dry-run`, `--force`, `--watchlist PATH` (default `stonks.txt`), `--config PATH` (default `config.toml`).

## Creating the webhook

1. In Discord, open the channel's settings (the gear next to its name), then **Integrations**, **Webhooks**, **New Webhook**.
2. Give it a name and, if you like, an avatar. That's how the posts will appear.
3. Click **Copy Webhook URL**. That URL is `DISCORD_WEBHOOK_URL`.

The URL is the only credential, and anyone holding it can post to that channel, so it lives only in `.env` (gitignored) and in GitHub secrets. No bot application is needed. If you ever want buttons or menus on the message, that requires a bot plus a small interaction endpoint; the webhook can be swapped for a bot token at that point.

## Running on GitHub Actions

1. Push this repo to GitHub.
2. **Settings, Secrets and variables, Actions, New repository secret**: name `DISCORD_WEBHOOK_URL`, value the webhook URL.
3. That's it. The **Post stonks** workflow runs on its own schedule.

**Schedule.** The workflows deliberately have no cron of their own. GitHub's scheduler proved unusable for this repo (it granted a few firings a day, then none at all), so a small Cloudflare Worker starts the workflows instead through GitHub's `workflow_dispatch` API, every hour during market time for posts and every few minutes for commands. The script still checks the NYSE calendar itself and does nothing when the market is closed, so a dispatch outside trading hours is harmless. Setting up that Worker is described in its own section below once it exists.

**Manual run.** Actions tab, **Post stonks**, **Run workflow**. Tick `dry_run` to see the message in the job log instead of posting, or `force` to post outside market hours.

## Watchlist: `stonks.txt`

One symbol per line. Blank lines and anything after `#` are ignored. Case doesn't matter and duplicates are collapsed. File order is the display order unless you sort (below). Symbols are whatever Yahoo Finance uses: `AAPL`, `BRK-B`, `^GSPC`, `BTC-USD` and so on. The market-hours check is NYSE only, so non-US symbols will show whatever Yahoo last reported.

## Display config: `config.toml`

| Key | Values | Default | Meaning |
|---|---|---|---|
| `title` | text | `"Stonks"` | Embed title prefix |
| `columns` | list of `price`, `open`, `day`, `week` | all four | Which columns, in that order |
| `sort` | `file`, `open`, `day`, `week` | `file` | File order, or by that column with the biggest gain first (`n/a` last) |
| `emoji` | `true` / `false` | `true` | 🟢 / 🔴 / ⚪ next to every percentage |
| `color_by` | `open`, `day`, `week` | `open` | Column that decides the embed colour |
| `layout` | `cards`, `table` | `cards` | `cards` is one small card per symbol, three across (works on phones); `table` is a monospace grid (desktop) |

A missing file means the defaults. Unknown keys are errors, so a typo can't silently do nothing.

## Discord commands (optional)

People on an allowlist can edit the watchlist from Discord. A second workflow polls the channel every 30 minutes and acts on these messages:

```
!stonks add QQQ
!stonks remove SAIL
!stonks list
```

The bot reacts ✅ or ❌ to each command and replies with the result. By default a change is committed straight to `main`, so the next hourly post already uses the new list. Set `auto_apply = false` under `[commands]` if you'd rather have requests collected in a pull request, "Watchlist changes from Discord", that you merge yourself. A symbol is checked against Yahoo Finance before it's added, and anyone not on the allowlist just gets a ❌.

Setup:

1. **Create a bot.** [Developer Portal](https://discord.com/developers/applications), **New Application**, **Bot** tab, **Reset Token**: that's `DISCORD_BOT_TOKEN`. On the same page, under Privileged Gateway Intents, enable **Message Content Intent**, or the bot will see empty messages.
2. **Invite it.** **OAuth2**, **URL Generator**: scope `bot`, permissions View Channel, Read Message History, Send Messages, Add Reactions (integer `68672`). Open the URL and add it to your server.
3. **Channel ID.** With Developer Mode on, right-click the channel, **Copy Channel ID**: that's `DISCORD_CHANNEL_ID`.
4. **Allowlist.** Right-click your own name, **Copy User ID**, and put it in `config.toml`:
   ```toml
   [commands]
   allowed_users = ["123456789012345678"]
   auto_apply = true
   ```
   The workflow refuses to run while this list is empty.
5. **Secrets.** Add `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` as repository secrets, next to the webhook.
6. **Only if `auto_apply = false`:** repo **Settings**, **Actions**, **General**, under Workflow permissions tick **Allow GitHub Actions to create and approve pull requests**. Without it the bot replies with a 403 from GitHub.

Good to know:

- Commands are picked up on the next run of the workflow, not instantly. How often that is depends on the Cloudflare Worker's schedule.
- It's `!stonks`, not `/stonks`. A leading slash makes Discord try to run a real slash command, which would need a hosted endpoint.
- Commits made by the workflow land on `main` from GitHub's side, so run `git pull` before your next push or git will refuse it as out of date.
- Pushes and pull requests made with the built-in Actions token don't trigger the Tests workflow. For a one-line watchlist change that's fine.
- Locally, `uv run stonks-commands --dry-run` reads the channel and prints what it would do, with no reactions, replies or pull request. It needs the bot token and channel ID in `.env`.

## Behaviour and limits

- Exit codes (both commands): `0` done or nothing to do; `1` data, Discord or GitHub failure; `2` bad input (missing file, bad config, missing or malformed secrets, empty allowlist, too many symbols).
- A symbol Yahoo can't find shows as an `n/a` row. If more than half the symbols have no price, the run treats it as an outage, posts nothing and fails, so it shows red in Actions.
- One message per run. Around 100 symbols fit in Discord's 6000-character embed budget; past that the run fails with a clear message rather than truncating.
- Prices come from Yahoo Finance through the unofficial `yfinance` library and may lag a few minutes. This is a glanceable pulse, not a trading feed.

## Troubleshooting

- **Scheduled runs stopped.** GitHub disables scheduled workflows in repos with no commits for 60 days. Push any commit, or run the workflow manually once, to re-enable.
- **`Discord returned 404: {"message": "Unknown Webhook"}`**: the webhook was deleted or the URL is incomplete. Create a new one and update the secret.
- **`Discord returned 401: {"message": "Invalid Webhook Token"}`**: the URL was pasted with its last part mangled. Copy it again.
- **`DISCORD_WEBHOOK_URL does not look like a Discord webhook URL`**: the value isn't of the form `https://discord.com/api/webhooks/<id>/<token>`. Check for stray quotes or spaces.
- **`request to Discord failed: ConnectionError`**: network trouble. The URL is deliberately left out of the log because it is the secret.
- **Every symbol is `n/a` or "fetching quotes failed"**: Yahoo changed something and `yfinance` needs updating. Run `uv lock --upgrade-package yfinance`, then `uv run pytest`, and commit `uv.lock`.
- **No posts at all.** Nothing starts the workflows unless something dispatches them. Check the Cloudflare Worker's cron and its logs, or run the workflow manually from the Actions tab to confirm the workflow itself is fine.

## Development

```bash
uv sync
uv run pytest
```

The design notes are in `docs/design.md` and the build plan in `docs/implementation-plan.md`.
