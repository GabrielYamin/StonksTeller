"""Command-line entry point: `stonks`."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from .config import ConfigError, load_config
from .discord import DiscordError, is_webhook_url, post_message
from .market import (ET, get_calendar, is_market_open, previous_session, reference_session,
                     week_start_session)
from .quotes import fetch_quotes
from .render import WatchlistTooLarge, build_embeds, render_text
from .watchlist import WatchlistError, read_watchlist

EXIT_OK, EXIT_FAILURE, EXIT_USAGE = 0, 1, 2
log = logging.getLogger("stonksteller")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stonks", description="Post a watchlist snapshot to Discord during market hours."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="print the message instead of posting; no webhook needed")
    parser.add_argument("--force", action="store_true", help="skip the market-hours check")
    parser.add_argument("--watchlist", type=Path, default=Path("stonks.txt"),
                        help="symbol list, one per line (default: stonks.txt)")
    parser.add_argument("--config", type=Path, default=Path("config.toml"),
                        help="display settings (default: config.toml)")
    parser.add_argument("--stamp-dir", type=Path, default=None,
                        help="directory of per-hour markers: skip if this hour's marker exists, "
                             "write one after posting (the scheduled workflow caches it)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    load_dotenv(Path.cwd() / ".env")  # never overrides variables already set (e.g. by CI)
    args = build_parser().parse_args(argv)

    try:
        symbols = read_watchlist(args.watchlist)
        config = load_config(args.config)
    except (WatchlistError, ConfigError) as exc:
        log.error("%s", exc)
        return EXIT_USAGE

    webhook_url = None
    if not args.dry_run:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            log.error("missing environment variable DISCORD_WEBHOOK_URL")
            return EXIT_USAGE
        if not is_webhook_url(webhook_url):
            log.error("DISCORD_WEBHOOK_URL does not look like a Discord webhook URL "
                      "(expected https://discord.com/api/webhooks/<id>/<token>)")
            return EXIT_USAGE

    cal = get_calendar()
    now = datetime.now(ET)
    if not args.force and not is_market_open(now, cal):
        log.info("market closed at %s; nothing to do", now.strftime("%Y-%m-%d %H:%M %Z"))
        return EXIT_OK

    stamp = args.stamp_dir / now.strftime("%Y-%m-%d-%H") if args.stamp_dir else None
    if stamp is not None and stamp.exists() and not args.force:
        log.info("already posted during hour %s; nothing to do", stamp.name)
        return EXIT_OK

    today = reference_session(now.date(), cal)
    week_start = week_start_session(today, cal)
    prev = previous_session(today, cal)
    try:
        quotes = fetch_quotes(symbols, today, week_start, prev)
    except Exception as exc:  # noqa: BLE001 - any data failure is exit 1
        log.error("fetching quotes failed: %s", exc)
        return EXIT_FAILURE

    failed = [q.symbol for q in quotes if q.price is None]
    if failed and len(failed) * 2 > len(quotes):
        log.error("%d of %d symbols have no price (%s); treating as a data outage, not posting",
                  len(failed), len(quotes), ", ".join(failed))
        return EXIT_FAILURE

    try:
        embeds = build_embeds(quotes, config, now)
    except WatchlistTooLarge as exc:
        log.error("%s", exc)
        return EXIT_USAGE

    if args.dry_run:
        print(render_text(quotes, config, now))
        return EXIT_OK

    try:
        post_message(webhook_url, embeds)
    except DiscordError as exc:
        log.error("%s", exc)
        return EXIT_FAILURE
    log.info("posted %d symbols", len(quotes))
    if stamp is not None:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(now.isoformat(), encoding="utf-8")
    return EXIT_OK
