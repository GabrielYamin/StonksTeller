import pytest

from stonksteller.config import ConfigError, DisplayConfig, load_config


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "config.toml")
    assert cfg == DisplayConfig()
    assert (cfg.title, cfg.columns, cfg.sort, cfg.emoji, cfg.color_by, cfg.layout) == (
        "Stonks", ("price", "open", "day", "week"), "file", True, "open", "cards")


def test_reads_values(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[display]\ntitle = "Watch"\ncolumns = ["price", "week"]\n'
        'sort = "week"\nemoji = false\ncolor_by = "day"\nlayout = "table"\n')
    assert load_config(tmp_path / "config.toml") == DisplayConfig(
        title="Watch", columns=("price", "week"), sort="week", emoji=False, color_by="day",
        layout="table")


def test_repo_config_file_matches_defaults():
    from pathlib import Path
    assert load_config(Path(__file__).resolve().parents[1] / "config.toml") == DisplayConfig()


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
    '[display]\nlayout = "lines"\n',                 # unknown layout
    '[display\n',                                    # malformed TOML
])
def test_invalid_config_raises(tmp_path, body):
    (tmp_path / "config.toml").write_text(body)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "config.toml")
