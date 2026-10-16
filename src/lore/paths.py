"""Where lore keeps its index, aliases and settings. `LORE_HOME` moves all of it (used by the tests)."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    if home := os.environ.get("LORE_HOME"):
        return Path(home) / "data"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "lore"


def config_dir() -> Path:
    if home := os.environ.get("LORE_HOME"):
        return Path(home) / "config"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "lore"


def index_path() -> Path:
    return data_dir() / "index.db"


def aliases_path() -> Path:
    return data_dir() / "aliases.json"


def recent_path() -> Path:
    return data_dir() / "recent.json"


def config_path() -> Path:
    return config_dir() / "config.toml"


def default_source() -> Path:
    """Where the course sources are looked for when nothing is configured."""
    if env := os.environ.get("LORE_SOURCE"):
        return Path(env).expanduser()
    return Path.home() / "programming-material" / "_build" / "sources"
