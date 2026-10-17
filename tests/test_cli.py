import pytest

from stonksteller import cli
from stonksteller.discord import DiscordError
from stonksteller.market import get_calendar
from stonksteller.quotes import Quote

CAL = get_calendar()
AAPL = Quote("AAPL", 343.46, 346.09, 342.00, 338.22)
WEBHOOK = "https://discord.com/api/webhooks/123/tok"


def boom(*args, **kwargs):
    raise AssertionError("must not be called")


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    (tmp_path / "stonks.txt").write_text("AAPL\nFAKE\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setattr(cli, "get_calendar", lambda: CAL)
    monkeypatch.setattr(cli, "is_market_open", lambda now, cal: True)
    monkeypatch.setattr(cli, "fetch_quotes",
                        lambda symbols, today, week_start, prev_session: [AAPL, Quote("FAKE")])
    return tmp_path


@pytest.fixture
def posted(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "post_message",
                        lambda webhook_url, embeds: calls.append((webhook_url, embeds)))
    return calls


def test_posts_when_market_open(workdir, posted):
    assert cli.main([]) == 0
    webhook_url, embeds = posted[0]
    assert (webhook_url, len(embeds)) == (WEBHOOK, 1)


def test_market_closed_exits_zero_without_fetching(workdir, posted, monkeypatch):
    monkeypatch.setattr(cli, "is_market_open", lambda now, cal: False)
    monkeypatch.setattr(cli, "fetch_quotes", boom)
    assert cli.main([]) == 0 and posted == []


def test_force_skips_market_check(workdir, posted, monkeypatch):
    monkeypatch.setattr(cli, "is_market_open", lambda now, cal: False)
    assert cli.main(["--force"]) == 0 and len(posted) == 1


def test_dry_run_prints_table_and_needs_no_secrets(workdir, monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")
    monkeypatch.setattr(cli, "post_message", boom)
    assert cli.main(["--dry-run"]) == 0
    assert "AAPL  343.46  🔴 -0.76% open" in capsys.readouterr().out


def test_missing_webhook_exit_2_before_fetching(workdir, posted, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")
    monkeypatch.setattr(cli, "fetch_quotes", boom)
    assert cli.main([]) == 2 and posted == []


def test_malformed_webhook_exit_2_before_fetching(workdir, posted, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "MTIz.not-a-url")
    monkeypatch.setattr(cli, "fetch_quotes", boom)
    assert cli.main([]) == 2 and posted == []


def test_dotenv_in_cwd_is_loaded(workdir, posted, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")
    (workdir / ".env").write_text("DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/9/filetok\n")
    assert cli.main([]) == 0 and posted[0][0] == "https://discord.com/api/webhooks/9/filetok"


def test_missing_watchlist_exit_2(workdir, posted):
    (workdir / "stonks.txt").unlink()
    assert cli.main([]) == 2 and posted == []


def test_bad_config_exit_2(workdir, posted):
    (workdir / "config.toml").write_text('[display]\nsort = "price"\n')
    assert cli.main([]) == 2 and posted == []


def test_more_than_half_failed_exit_1_without_posting(workdir, posted, monkeypatch):
    (workdir / "stonks.txt").write_text("A\nB\nC\n")
    monkeypatch.setattr(cli, "fetch_quotes",
                        lambda *a: [Quote("A", 1.0, 1.0, 1.0, 1.0), Quote("B"), Quote("C")])
    assert cli.main([]) == 1 and posted == []


def test_exactly_half_failed_still_posts(workdir, posted):
    assert cli.main([]) == 0 and len(posted) == 1


def test_fetch_exception_exit_1(workdir, posted, monkeypatch):
    def raise_(*a):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(cli, "fetch_quotes", raise_)
    assert cli.main([]) == 1 and posted == []


def test_discord_error_exit_1(workdir, monkeypatch):
    def raise_(*a, **k):
        raise DiscordError("Discord returned 404: Unknown Webhook")
    monkeypatch.setattr(cli, "post_message", raise_)
    assert cli.main([]) == 1


def test_oversized_watchlist_exit_2(workdir, posted, monkeypatch):
    symbols = [f"S{i:03d}" for i in range(200)]
    (workdir / "stonks.txt").write_text("\n".join(symbols) + "\n")
    monkeypatch.setattr(cli, "fetch_quotes",
                        lambda syms, *a: [Quote(s, 10.0, 10.0, 10.0, 10.0) for s in syms])
    assert cli.main([]) == 2 and posted == []
