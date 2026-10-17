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
SECTIONS = ("display", "commands")


class ConfigError(ValueError):
    """config.toml is malformed or holds an unknown or invalid value."""


@dataclass(frozen=True)
class CommandsConfig:
    allowed_users: tuple[str, ...] = ()   # Discord user IDs allowed to run !stonks commands


@dataclass(frozen=True)
class DisplayConfig:
    title: str = "Stonks"
    columns: tuple[str, ...] = COLUMNS
    sort: str = "file"
    emoji: bool = True
    color_by: str = "open"
    layout: str = "cards"


def load_config(path: Path) -> DisplayConfig:
    """Load the [display] section of config.toml; a missing file means all defaults."""
    path = Path(path)
    display = _read_toml(path).get("display", {})
    if not isinstance(display, dict):
        raise ConfigError(f"{path}: [display] must be a table")
    _reject_unknown_keys(display, DisplayConfig, "display", path)
    values = dict(display)
    if isinstance(values.get("columns"), list):
        values["columns"] = tuple(values["columns"])
    config = DisplayConfig(**values)
    _validate(config, path)
    return config


def load_commands_config(path: Path) -> CommandsConfig:
    """Load the [commands] section of config.toml; missing file or section means no one is allowed."""
    path = Path(path)
    commands = _read_toml(path).get("commands", {})
    if not isinstance(commands, dict):
        raise ConfigError(f"{path}: [commands] must be a table")
    _reject_unknown_keys(commands, CommandsConfig, "commands", path)
    users = commands.get("allowed_users", [])
    if not isinstance(users, list) or not all(isinstance(u, (str, int)) and str(u).isdigit() for u in users):
        raise ConfigError(f"{path}: allowed_users must be a list of Discord user IDs (digits)")
    return CommandsConfig(allowed_users=tuple(str(u) for u in users))


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    unknown_sections = sorted(set(data) - set(SECTIONS))
    if unknown_sections:
        raise ConfigError(f"{path}: unknown section(s): {', '.join(unknown_sections)}")
    return data


def _reject_unknown_keys(table: dict, cls, section: str, path: Path) -> None:
    known = {f.name for f in fields(cls)}
    unknown_keys = sorted(set(table) - known)
    if unknown_keys:
        raise ConfigError(f"{path}: unknown key(s) in [{section}]: {', '.join(unknown_keys)}")


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
