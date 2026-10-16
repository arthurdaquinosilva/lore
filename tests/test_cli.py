import subprocess
import sys


def lore(*args, home, input=None):
    import os

    env = {**os.environ, "LORE_HOME": str(home.parent / "home"), "LORE_SOURCE": str(home.parent.parent / "x")}
    return subprocess.run([sys.executable, "-m", "lore", *args], capture_output=True, text=True, env=env, input=input)


def test_search_lists_matches(indexed):
    r = lore("search", "revert", "commit", home=indexed)
    assert r.returncode == 0 and "mini:1.2" in r.stdout


def test_search_json(indexed):
    import json

    r = lore("search", "reset", "--json", home=indexed)
    data = json.loads(r.stdout)
    assert data and {"id", "kind", "course", "title"} <= set(data[0])


def test_get_prints_code_of_a_snippet_when_piped(indexed):
    r = lore("get", "mini:1.1#1", home=indexed)
    assert r.stdout.splitlines()[0] == "git reset --soft HEAD~1"


def test_alias_round_trip(indexed):
    assert lore("alias", "add", "undo", "mini:1.1#1", home=indexed).returncode == 0
    assert "@undo" in lore("alias", "ls", home=indexed).stdout
    assert lore("@undo", home=indexed).stdout.startswith("git reset --soft")
    assert lore("alias", "mv", "undo", "soft", home=indexed).returncode == 0
    assert lore("@soft", home=indexed).returncode == 0
    assert lore("alias", "rm", "soft", home=indexed).returncode == 0
    assert lore("@soft", home=indexed).returncode == 1


def test_text_alias_from_stdin(indexed):
    assert lore("alias", "add", "snip", "--text", "-", home=indexed, input="echo 1\necho 2\n").returncode == 0
    assert lore("@snip", home=indexed).stdout == "echo 1\necho 2\n"


def test_unknown_course_is_an_error(indexed):
    r = lore("-c", "nope", "x", home=indexed)
    assert r.returncode == 2 and "unknown course" in r.stderr


def test_courses_and_info(indexed):
    assert "Mini Mastery" in lore("courses", home=indexed).stdout
    assert "1 courses" in lore("info", home=indexed).stdout or "1 course" in lore("info", home=indexed).stdout


def test_missing_index_and_source(tmp_path):
    import os

    env = {**os.environ, "LORE_HOME": str(tmp_path / "h"), "LORE_SOURCE": str(tmp_path / "none")}
    r = subprocess.run([sys.executable, "-m", "lore", "search", "x"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "lore index --source" in r.stderr
