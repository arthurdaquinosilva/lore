"""Drive the real interface in a pseudo-terminal."""

import os
import sys

import pytest

pexpect = pytest.importorskip("pexpect")
pytest.importorskip("pyte")

sys.path.insert(0, os.path.dirname(__file__))
from tui import Term  # noqa: E402


@pytest.fixture()
def term(indexed):
    made = []

    def make(*args, cols=120, rows=36):
        t = Term(list(args), str(indexed), cols, rows)
        made.append(t)
        t.pump(1.0)
        return t

    yield make
    for t in made:
        t.close()


def test_empty_state_shows_the_banner(term):
    t = term()
    assert "topics" in t.text() and "snippets" in t.text()
    assert "Search the courses" in t.text()


def test_typing_lists_suggestions_with_a_preview(term):
    t = term()
    t.send("revert", 0.6)
    screen = t.text()
    assert "Reverting a Commit" in screen
    assert "results" in screen
    assert "git revert" in screen  # in the preview


def test_enter_opens_the_reader_and_q_goes_back(term):
    t = term()
    t.send("reverting a commit", 0.6)
    t.send("\r", 0.8)
    assert "Mini" in t.text() and "BACK: q" in t.text()
    t.send("q", 0.5)
    assert "Search the courses" in t.text() or "❯ reverting a commit" in t.text()


def test_alias_is_saved_from_the_reader_and_listed_on_the_empty_screen(term):
    t = term()
    t.send("reverting a commit", 0.6)
    t.send("\r", 0.8)
    t.send("\t", 0.4)   # select the code block
    t.send("a", 0.4)
    assert "SAVE: Enter" in t.text()
    t.send("\x15revert-it\r", 0.6)
    assert "@revert-it saved" in t.text()
    t.send("q", 0.4)
    t.send("\x15", 0.3)
    assert "@revert-it" in t.text()


def test_help_and_escape(term):
    t = term()
    t.send("?", 0.4)
    assert "Esc closes this panel" in t.text()
    t.send("\x1b", 0.5)
    assert "Esc closes this panel" not in t.text()
    t.send("\x1b", 0.5)  # from an empty prompt, Esc leaves
    t.child.expect(pexpect.EOF, timeout=3)


def test_escape_clears_the_query_before_leaving(term):
    t = term()
    t.send("revert", 0.5)
    t.send("\x1b", 0.5)
    assert t.alive()
    assert "Search the courses" in t.text()


def test_kind_and_course_filters_cycle(term):
    t = term()
    t.send("git", 0.5)
    t.send("\x14", 0.5)  # Ctrl+T
    assert "topics" in t.text().split("\n")[0]
    t.send("\x13", 0.5)  # Ctrl+S
    assert "Mini" in t.text().split("\n")[0]


def test_pick_mode_prints_the_selection_into_a_pipe(indexed):
    import shutil

    lore = os.path.join(os.path.dirname(sys.executable), "lore")
    child = pexpect.spawn("/bin/sh", ["-c", f"{lore} --pick git reset | cat"], dimensions=(30, 100), timeout=5,
                          env={**os.environ, "LORE_HOME": str(indexed), "TERM": "xterm-256color"})
    import time
    time.sleep(1.2)
    child.send("\x0f")  # Ctrl+O prints and quits
    child.expect(pexpect.EOF, timeout=5)
    out = child.before.decode()
    assert "git reset --soft HEAD~1" in out


def test_narrow_terminal_hides_the_preview(term):
    t = term(cols=70, rows=24)
    t.send("revert", 0.6)
    assert "│" not in t.text().split("\n")[5]
    assert "Reverting a Commit" in t.text()


def test_open_alias_directly(term, indexed):
    from lore.aliases import Aliases
    from lore.store import Store

    Aliases().add_ref("rv", Store().get("mini:1.2"))
    t = term("@rv", rows=30)
    # `lore @rv` prints inline instead of opening the interface
    assert "Reverting a Commit" in t.text()
