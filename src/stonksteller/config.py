"""Display configuration from config.toml."""
from __future__ import annotations

import sys
from dataclasses import dataclass, fields
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

COLUMNS = ("price", "open", "day", "week")
PCT_COLUMNS = ("open", "day", "week")
LAYOUTS = ("cards", "table")


class ConfigError(ValueError):
    """config.toml is malformed or holds an unknown or invalid value."""


@dataclass(frozen=True)
class DisplayConfig:
    title: str = "Stonks"
    columns: tuple[str, ...] = COLUMNS
    sort: str = "file"
    emoji: bool = True
    color_by: str = "open"
    layout: str = "cards"


def load_config(path: Path) -> DisplayConfig:
    """Load config.toml; a missing file means all defaults."""
    path = Path(path)
    if not path.is_file():
        return DisplayConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc

    unknown_sections = sorted(set(data) - {"display"})
    if unknown_sections:
        raise ConfigError(f"{path}: unknown section(s): {', '.join(unknown_sections)}")
    display = data.get("display", {})
    if not isinstance(display, dict):
        raise ConfigError(f"{path}: [display] must be a table")
    known = {f.name for f in fields(DisplayConfig)}
    unknown_keys = sorted(set(display) - known)
    if unknown_keys:
        raise ConfigError(f"{path}: unknown key(s) in [display]: {', '.join(unknown_keys)}")

    values = dict(display)
    if isinstance(values.get("columns"), list):
        values["columns"] = tuple(values["columns"])
    config = DisplayConfig(**values)
    _validate(config, path)
    return config


def _validate(config: DisplayConfig, path: Path) -> None:
    def fail(message: str) -> ConfigError:
        return ConfigError(f"{path}: {message}")

    if not isinstance(config.title, str) or not config.title.strip():
        raise fail("title must be a non-empty string")
    if not isinstance(config.columns, tuple) or not config.columns:
        raise fail("columns must be a non-empty list")
    for column in config.columns:
        if column not in COLUMNS:
            raise fail(f"columns: unknown column {column!r}; choose from {', '.join(COLUMNS)}")
    if len(set(config.columns)) != len(config.columns):
        raise fail("columns: duplicate column")
    if config.sort != "file" and config.sort not in PCT_COLUMNS:
        raise fail(f"sort must be 'file' or one of {', '.join(PCT_COLUMNS)}")
    if not isinstance(config.emoji, bool):
        raise fail("emoji must be true or false")
    if config.color_by not in PCT_COLUMNS:
        raise fail(f"color_by must be one of {', '.join(PCT_COLUMNS)}")
    if config.layout not in LAYOUTS:
        raise fail(f"layout must be one of {', '.join(LAYOUTS)}")
