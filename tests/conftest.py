from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """An empty LORE_HOME so nothing touches the real aliases or index."""
    monkeypatch.setenv("LORE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LORE_SOURCE", str(FIXTURES))
    return tmp_path / "home"


@pytest.fixture()
def indexed(home):
    from lore.indexer import build

    build(FIXTURES)
    return home


@pytest.fixture()
def store(indexed):
    from lore.store import Store

    s = Store()
    yield s
    s.close()
