"""Turn `!stonks ...` messages in a Discord channel into a watchlist pull request."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .discord import BotClient, DiscordError
from .github import GitHubError, GitHubRepo
from .watchlist import add_symbol, is_valid_symbol, parse_symbols, remove_symbol

COMMAND_RE = re.compile(r"^\s*!stonks\s+(add|remove|list)\b(?:\s+(\S+))?\s*$", re.IGNORECASE)
BRANCH = "stonks/discord"
PR_TITLE = "Watchlist changes from Discord"
OK, NO = "✅", "❌"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Command:
    message_id: str
    author_id: str
    author_name: str
    action: str                 # "add", "remove" or "list"
    symbol: str | None


@dataclass(frozen=True)
class Outcome:
    command: Command
    ok: bool
    reply: str | None                       # None means react only
    change: tuple[str, str] | None = None   # (new watchlist text, commit message) when the file changes


def parse_command(message: dict) -> Command | None:
    """A Command for a `!stonks ...` message written by a human, else None."""
    author = message.get("author") or {}
    if author.get("bot"):
        return None
    match = COMMAND_RE.match(message.get("content") or "")
    if not match:
        return None
    action, symbol = match.group(1).lower(), match.group(2)
    name = author.get("global_name") or author.get("username") or "unknown"
    return Command(str(message["id"]), str(author.get("id", "")), name, action,
                   symbol.upper() if symbol else None)


def already_handled(message: dict) -> bool:
    """True once the bot has reacted to the message; that reaction is the only memory needed."""
    return any(reaction.get("me") for reaction in message.get("reactions") or [])


def decide(command: Command, text: str, allowed_users: Iterable[str],
           symbol_known: Callable[[str], bool]) -> Outcome:
    """What to do about one command given the current watchlist text. Pure."""
    if command.author_id not in set(allowed_users):
        return Outcome(command, False, None)
    symbols = parse_symbols(text)
    if command.action == "list":
        listing = ("Watchlist: " + ", ".join(symbols)) if symbols else "The watchlist is empty."
        return Outcome(command, True, listing)
    if not command.symbol:
        return Outcome(command, False, f"Usage: `!stonks {command.action} SYMBOL`")
    symbol = command.symbol
    if not is_valid_symbol(symbol):
        return Outcome(command, False, f"`{symbol.replace('`', '')}` doesn't look like a Yahoo Finance symbol.")
    if command.action == "add":
        if symbol in symbols:
            return Outcome(command, True, f"**{symbol}** is already in the watchlist.")
        if not symbol_known(symbol):
            return Outcome(command, False, f"Yahoo Finance doesn't know **{symbol}**.")
        return Outcome(command, True, None,
                       (add_symbol(text, symbol), f"Add {symbol} (requested by {command.author_name} via Discord)"))
    if symbol not in symbols:
        return Outcome(command, False, f"**{symbol}** isn't in the watchlist.")
    return Outcome(command, True, None,
                   (remove_symbol(text, symbol), f"Remove {symbol} (requested by {command.author_name} via Discord)"))


class WatchlistPR:
    """The single open pull request on `stonks/discord` that accumulates requested changes."""

    def __init__(self, repo: GitHubRepo, path: str = "stonks.txt"):
        self.repo = repo
        self.path = path
        self.base = "main"
        self.pull: dict | None = None
        self.text = ""
        self._sha = ""
        self._commits: list[str] = []

    def open(self) -> None:
        """Reuse the open PR's branch, or start a fresh branch from the default branch."""
        self.base = self.repo.default_branch()
        self.pull = self.repo.open_pull(BRANCH)
        if self.pull is None:
            if self.repo.branch_sha(BRANCH) is not None:
                self.repo.delete_branch(BRANCH)        # left over from a merged or closed PR
            self.repo.create_branch(BRANCH, self.repo.branch_sha(self.base))
        self.text, self._sha = self.repo.read_file(self.path, BRANCH)

    def commit(self, new_text: str, message: str) -> None:
        self._sha = self.repo.write_file(self.path, BRANCH, new_text, self._sha, message)
        self.text = new_text
        self._commits.append(message)

    def finish(self) -> str | None:
        """Create or update the PR; returns its URL, or None when nothing was committed."""
        if not self._commits:
            return self.pull["html_url"] if self.pull else None
        lines = "\n".join(f"- {message}" for message in self._commits)
        if self.pull is None:
            body = f"Requested in Discord with `!stonks` commands.\n\n{lines}\n"
            self.pull = self.repo.create_pull(BRANCH, self.base, PR_TITLE, body)
        else:
            body = (self.pull.get("body") or "").rstrip("\n") + "\n" + lines + "\n"
            self.repo.update_pull_body(self.pull["number"], body)
        return self.pull["html_url"]


class WatchlistCommit:
    """Applies requested changes straight to the default branch, one commit per command."""

    def __init__(self, repo: GitHubRepo, path: str = "stonks.txt"):
        self.repo = repo
        self.path = path
        self.base = "main"
        self.text = ""
        self._sha = ""

    def open(self) -> None:
        self.base = self.repo.default_branch()
        self.text, self._sha = self.repo.read_file(self.path, self.base)

    def commit(self, new_text: str, message: str) -> None:
        self._sha = self.repo.write_file(self.path, self.base, new_text, self._sha, message)
        self.text = new_text

    def finish(self) -> None:
        return None


def run_commands(bot: BotClient, channel_id: str, pr: WatchlistPR | WatchlistCommit | None, allowed_users: Iterable[str],
                 symbol_known: Callable[[str], bool], *, dry_run: bool = False,
                 local_text: str = "") -> list[Outcome]:
    """Read the channel, act on new commands oldest first, then react and reply to each."""
    messages = bot.list_messages(channel_id)
    pending = [command for message in reversed(messages)
               if not already_handled(message) and (command := parse_command(message)) is not None]
    if not pending:
        return []

    if dry_run:
        text = local_text
    else:
        pr.open()
        text = pr.text

    outcomes = []
    for command in pending:
        outcome = decide(command, text, allowed_users, symbol_known)
        if outcome.change is not None and not dry_run:
            try:
                pr.commit(*outcome.change)
            except GitHubError as exc:
                outcome = Outcome(command, False, f"Couldn't update the watchlist on GitHub: {exc}")
        if outcome.change is not None:
            text = outcome.change[0]
        outcomes.append(outcome)

    if dry_run:
        return outcomes
    try:
        url = pr.finish()
    except GitHubError as exc:
        url = None
        outcomes = [Outcome(o.command, False, f"Couldn't finish the change on GitHub: {exc}") if o.change else o
                    for o in outcomes]
    for outcome in outcomes:
        _announce(bot, channel_id, outcome, url)
    return outcomes


def _announce(bot: BotClient, channel_id: str, outcome: Outcome, url: str | None) -> None:
    reply = outcome.reply
    if outcome.ok and outcome.change is not None:
        symbol, adding = outcome.command.symbol, outcome.command.action == "add"
        if url:
            reply = f"**{symbol}** will be {'added' if adding else 'removed'} when this pull request is merged: {url}"
        elif adding:
            reply = f"**{symbol}** added to the watchlist. The next hourly post will include it."
        else:
            reply = f"**{symbol}** removed from the watchlist."
    try:
        bot.add_reaction(channel_id, outcome.command.message_id, OK if outcome.ok else NO)
        if reply:
            bot.reply(channel_id, outcome.command.message_id, reply)
    except DiscordError as exc:
        log.warning("could not announce the result for message %s: %s", outcome.command.message_id, exc)
