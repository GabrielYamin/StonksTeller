import logging

import pytest

from stonksteller.commands import (Command, Outcome, WatchlistCommit, WatchlistPR, already_handled,
                                   decide, parse_command, run_commands)
from stonksteller.github import GitHubError

TEXT = "# list\nAAPL\nSPY  # etf\n"
ALLOWED = ("1",)


def known(symbol):
    return symbol != "NOPE"


def msg(id, content, author_id="1", name="gabe", bot=False, me_reacted=False):
    message = {"id": id, "content": content, "author": {"id": author_id, "username": name, "bot": bot}}
    if me_reacted:
        message["reactions"] = [{"emoji": {"name": "✅"}, "me": True, "count": 1}]
    return message


def test_parse_command_variants():
    assert parse_command(msg("5", "!stonks add qqq")) == Command("5", "1", "gabe", "add", "QQQ")
    assert parse_command(msg("5", "  !STONKS Remove spy ")) == Command("5", "1", "gabe", "remove", "SPY")
    assert parse_command(msg("5", "!stonks list")) == Command("5", "1", "gabe", "list", None)
    assert parse_command(msg("5", "!stonks add")) == Command("5", "1", "gabe", "add", None)


@pytest.mark.parametrize("content", [
    "hello", "!stonks", "!stonks buy AAPL", "!stonks add AAPL now", "stonks add AAPL", "/stonks add AAPL",
])
def test_parse_command_ignores_other_messages(content):
    assert parse_command(msg("5", content)) is None


def test_parse_command_ignores_bots():
    assert parse_command(msg("5", "!stonks list", bot=True)) is None


def test_already_handled_means_the_bot_reacted():
    assert already_handled(msg("1", "x", me_reacted=True))
    assert not already_handled(msg("1", "x"))
    assert not already_handled({"id": "1", "reactions": [{"emoji": {"name": "👍"}, "me": False}]})


def test_decide_rejects_unlisted_users_with_a_reaction_only():
    cmd = Command("5", "999", "rando", "add", "QQQ")
    assert decide(cmd, TEXT, ALLOWED, known) == Outcome(cmd, False, None)


def test_decide_add_produces_a_change():
    cmd = Command("5", "1", "gabe", "add", "QQQ")
    out = decide(cmd, TEXT, ALLOWED, known)
    assert (out.ok, out.reply) == (True, None)
    assert out.change == (TEXT + "QQQ\n", "Add QQQ (requested by gabe via Discord)")


@pytest.mark.parametrize("action, symbol, ok, reply", [
    ("add", "AAPL", True, "**AAPL** is already in the watchlist."),
    ("add", "NOPE", False, "Yahoo Finance doesn't know **NOPE**."),
    ("add", "QQ$", False, "`QQ$` doesn't look like a Yahoo Finance symbol."),
    ("add", None, False, "Usage: `!stonks add SYMBOL`"),
    ("remove", "QQQ", False, "**QQQ** isn't in the watchlist."),
    ("remove", None, False, "Usage: `!stonks remove SYMBOL`"),
    ("list", None, True, "Watchlist: AAPL, SPY"),
])
def test_decide_replies(action, symbol, ok, reply):
    out = decide(Command("5", "1", "gabe", action, symbol), TEXT, ALLOWED, known)
    assert (out.ok, out.reply, out.change) == (ok, reply, None)


def test_decide_remove_keeps_comments_and_other_lines():
    out = decide(Command("5", "1", "gabe", "remove", "SPY"), TEXT, ALLOWED, known)
    assert out.change == ("# list\nAAPL\n", "Remove SPY (requested by gabe via Discord)")


class FakeBot:
    def __init__(self, messages):
        self.messages, self.reactions, self.replies = messages, [], []

    def list_messages(self, channel_id, limit=50):
        return self.messages

    def add_reaction(self, channel_id, message_id, emoji):
        self.reactions.append((message_id, emoji))

    def reply(self, channel_id, message_id, content):
        self.replies.append((message_id, content))


class FakePR:
    def __init__(self, text):
        self.text, self.commits, self.opened = text, [], False

    def open(self):
        self.opened = True

    def commit(self, text, message):
        self.text = text
        self.commits.append(message)

    def finish(self):
        return "https://github.com/o/r/pull/7" if self.commits else None


def test_run_commands_processes_oldest_first_and_announces():
    bot = FakeBot([   # newest first, as Discord returns them
        msg("3", "!stonks add nope"),
        msg("2", "!stonks remove spy"),
        msg("1", "!stonks add qqq"),
        msg("0", "!stonks list", me_reacted=True),
    ])
    pr = FakePR(TEXT)
    outcomes = run_commands(bot, "c", pr, ALLOWED, known)
    assert [o.command.message_id for o in outcomes] == ["1", "2", "3"]
    assert pr.commits == ["Add QQQ (requested by gabe via Discord)", "Remove SPY (requested by gabe via Discord)"]
    assert pr.text == "# list\nAAPL\nQQQ\n"
    assert bot.reactions == [("1", "✅"), ("2", "✅"), ("3", "❌")]
    assert bot.replies == [
        ("1", "**QQQ** will be added in the next cycle. It's waiting in a pull request until someone merges it."),
        ("2", "**SPY** will be removed in the next cycle. It's waiting in a pull request until someone merges it."),
        ("3", "Yahoo Finance doesn't know **NOPE**."),
    ]
    assert not any("github.com" in reply for _, reply in bot.replies)


def test_run_commands_direct_mode_wording():
    class DirectTarget(FakePR):
        def finish(self):
            return None

    bot = FakeBot([msg("2", "!stonks remove spy"), msg("1", "!stonks add qqq")])
    outcomes = run_commands(bot, "c", DirectTarget(TEXT), ALLOWED, known)
    assert all(o.ok for o in outcomes)
    assert bot.replies == [
        ("1", "**QQQ** will be added in the next cycle."),
        ("2", "**SPY** will be removed in the next cycle."),
    ]


def test_run_commands_warns_when_discord_hides_message_content(caplog):
    caplog.set_level(logging.INFO)
    bot = FakeBot([msg("2", ""), msg("1", ""), {"id": "0", "content": "", "webhook_id": "w", "author": {"id": "9"}}])
    assert run_commands(bot, "c", FakePR(TEXT), ALLOWED, known) == []
    assert "Message Content Intent" in caplog.text
    assert "fetched 3 messages, 2 from people" in caplog.text


def test_run_commands_does_not_warn_when_content_is_visible(caplog):
    bot = FakeBot([msg("1", "hello")])
    assert run_commands(bot, "c", FakePR(TEXT), ALLOWED, known) == []
    assert "Message Content Intent" not in caplog.text


def test_run_commands_dry_run_touches_nothing():
    bot = FakeBot([msg("1", "!stonks add qqq")])
    outcomes = run_commands(bot, "c", None, ALLOWED, known, dry_run=True, local_text=TEXT)
    assert outcomes[0].change[0] == TEXT + "QQQ\n"
    assert bot.reactions == [] and bot.replies == []


def test_run_commands_with_nothing_pending_does_not_open_a_pr():
    bot = FakeBot([msg("1", "hello"), msg("0", "!stonks list", me_reacted=True)])
    pr = FakePR(TEXT)
    assert run_commands(bot, "c", pr, ALLOWED, known) == []
    assert not pr.opened


def test_run_commands_reports_a_failed_pull_request():
    class FailingPR(FakePR):
        def finish(self):
            raise GitHubError("GitHub returned 403: GitHub Actions is not permitted to create or approve pull requests")

    bot = FakeBot([msg("1", "!stonks add qqq")])
    [outcome] = run_commands(bot, "c", FailingPR(TEXT), ALLOWED, known)
    assert not outcome.ok
    assert bot.reactions == [("1", "❌")]
    assert "not permitted" in bot.replies[0][1]


class FakeRepo:
    def __init__(self, pull=None, branch_exists=False):
        self.pull, self.branch, self.calls, self.text, self.body = pull, branch_exists, [], "AAPL\n", None

    def default_branch(self):
        return "main"

    def open_pull(self, head):
        self.calls.append(("open_pull", head))
        return self.pull

    def branch_sha(self, branch):
        return "abc" if branch == "main" or self.branch else None

    def create_branch(self, branch, sha):
        self.calls.append(("create_branch", branch, sha))
        self.branch = True

    def delete_branch(self, branch):
        self.calls.append(("delete_branch", branch))
        self.branch = False

    def read_file(self, path, ref):
        return self.text, "sha1"

    def write_file(self, path, branch, text, sha, message):
        self.calls.append(("write_file", branch, sha, message))
        self.text = text
        return "sha2"

    def create_pull(self, head, base, title, body):
        self.calls.append(("create_pull", head, base, title))
        self.body = body
        return {"number": 7, "html_url": "u", "body": body}

    def update_pull_body(self, number, body):
        self.calls.append(("update_pull_body", number))
        self.body = body


def test_watchlist_pr_recreates_a_stale_branch_and_opens_a_pull():
    repo = FakeRepo(branch_exists=True)   # left over from a merged PR
    pr = WatchlistPR(repo)
    pr.open()
    assert ("delete_branch", "stonks/discord") in repo.calls
    assert ("create_branch", "stonks/discord", "abc") in repo.calls
    pr.commit("AAPL\nQQQ\n", "Add QQQ")
    pr.commit("AAPL\nQQQ\nV\n", "Add V")
    assert pr.finish() == "u"
    assert ("write_file", "stonks/discord", "sha1", "Add QQQ") in repo.calls
    assert ("write_file", "stonks/discord", "sha2", "Add V") in repo.calls
    assert ("create_pull", "stonks/discord", "main", "Watchlist changes from Discord") in repo.calls
    assert repo.body.endswith("- Add QQQ\n- Add V\n")


def test_watchlist_pr_reuses_an_open_pull():
    repo = FakeRepo(pull={"number": 7, "html_url": "u", "body": "Requested.\n\n- Add QQQ\n"}, branch_exists=True)
    pr = WatchlistPR(repo)
    pr.open()
    assert not any(call[0] in ("delete_branch", "create_branch") for call in repo.calls)
    pr.commit("AAPL\nQQQ\nV\n", "Add V")
    assert pr.finish() == "u"
    assert ("update_pull_body", 7) in repo.calls
    assert repo.body == "Requested.\n\n- Add QQQ\n- Add V\n"


def test_watchlist_pr_without_commits_creates_nothing():
    repo = FakeRepo()
    pr = WatchlistPR(repo)
    pr.open()
    assert pr.finish() is None
    assert not any(call[0] == "create_pull" for call in repo.calls)


def test_watchlist_commit_writes_straight_to_the_default_branch():
    repo = FakeRepo()
    target = WatchlistCommit(repo)
    target.open()
    assert target.text == "AAPL\n"
    target.commit("AAPL\nQQQ\n", "Add QQQ")
    target.commit("QQQ\n", "Remove AAPL")
    assert target.finish() is None
    assert repo.calls == [("write_file", "main", "sha1", "Add QQQ"), ("write_file", "main", "sha2", "Remove AAPL")]
    assert repo.text == "QQQ\n"
