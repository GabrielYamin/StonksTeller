"""Command-line entry point: `stonks-commands`."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from .commands import NO, OK, WatchlistCommit, WatchlistPR, run_commands
from .config import ConfigError, load_commands_config
from .discord import BotClient, DiscordError
from .github import GitHubError, GitHubRepo
from .quotes import symbol_known

EXIT_OK, EXIT_FAILURE, EXIT_USAGE = 0, 1, 2
log = logging.getLogger("stonksteller")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stonks-commands",
        description="Turn !stonks commands in a Discord channel into a watchlist pull request.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen; no reactions, replies or pull request")
    parser.add_argument("--watchlist", type=Path, default=Path("stonks.txt"),
                        help="local watchlist used as the baseline in a dry run (default: stonks.txt)")
    parser.add_argument("--config", type=Path, default=Path("config.toml"),
                        help="config with the [commands] allowlist (default: config.toml)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args(argv)

    try:
        config = load_commands_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_USAGE
    if not config.allowed_users:
        log.error("no allowed_users under [commands] in %s; refusing to act on Discord messages", args.config)
        return EXIT_USAGE

    required = ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"]
    if not args.dry_run:
        required += ["GITHUB_TOKEN", "GITHUB_REPOSITORY"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        log.error("missing environment variable(s): %s", ", ".join(missing))
        return EXIT_USAGE

    bot = BotClient(os.environ["DISCORD_BOT_TOKEN"])
    channel_id = os.environ["DISCORD_CHANNEL_ID"]
    target = None
    if not args.dry_run:
        repo = GitHubRepo(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
        target = WatchlistCommit(repo) if config.auto_apply else WatchlistPR(repo)
    local_text = args.watchlist.read_text(encoding="utf-8") if args.watchlist.is_file() else ""

    try:
        outcomes = run_commands(bot, channel_id, target, config.allowed_users, symbol_known,
                                dry_run=args.dry_run, local_text=local_text)
    except (DiscordError, GitHubError) as exc:
        log.error("%s", exc)
        return EXIT_FAILURE

    if not outcomes:
        log.info("no new commands")
    for outcome in outcomes:
        command = outcome.command
        detail = outcome.reply or ("watchlist change" if outcome.change else "author not allowed")
        log.info("%s %s %s by %s: %s", OK if outcome.ok else NO, command.action, command.symbol or "",
                 command.author_name, detail)
    return EXIT_OK
