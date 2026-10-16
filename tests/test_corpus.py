from pathlib import Path

from lore.corpus import classify, parse_course
from lore.htmlclean import clean

SRC = Path(__file__).parent / "fixtures" / "sources" / "mini.md"


def entries():
    return {e.id: e for e in parse_course(SRC).entries}


def test_sections_and_numbers():
    ids = entries()
    assert "mini:1.1" in ids and "mini:1.2" in ids and "mini:2.1" in ids
    assert ids["mini:1.1"].title == "Resetting the Branch"
    assert ids["mini:1.1"].section == "Undoing Things"
    assert ids["mini:1.1"].section_no == 1
    assert ids["mini:2.2"].section == "Searching Text"


def test_section_opener_exercises_and_guides():
    ids = entries()
    assert ids["mini:1.0"].kind == "topic"
    assert ids["mini:s1-exercises"].kind == "exercise"
    assert ids["mini:s0-how-to-use-this-course"].kind == "guide"
    assert ids["mini:conclusion"].kind == "guide"


def test_snippets_get_output_and_caption():
    e = entries()["mini:1.1"]
    assert len(e.snippets) == 1
    s = e.snippets[0]
    assert s.id == "mini:1.1#1"
    assert s.lang == "bash"
    assert s.code.splitlines()[0] == "git reset --soft HEAD~1"
    assert s.output == "M  notes.txt"
    assert "keep its changes staged" in s.caption


def test_terms_are_definitions_with_articles_removed():
    terms = {t.name: t for e in entries().values() for t in e.terms}
    assert "soft reset" in terms
    assert "regular expression" in terms
    assert terms["soft reset"].definition.startswith("A **soft reset** is a reset")


def test_callout_grid_becomes_bullets_and_figure_becomes_a_note():
    body = entries()["mini:1.1"].body
    assert "- **--soft** — Move the branch only." in body
    assert "*Figure — The three trees a reset can move.*" in body
    assert "<div" not in body and "<svg" not in body


def test_details_becomes_a_marked_region():
    body = entries()["mini:s1-exercises"].body
    assert ":::details Solution" in body
    assert body.rstrip().endswith(":::")


def test_clean_leaves_code_fences_alone():
    md = "```html\n<div style=\"x\">keep me</div>\n```\n\n<div><b>go</b></div>"
    out = clean(md)
    assert '<div style="x">keep me</div>' in out
    assert "go" in out.split("```")[-1] and "<div>" not in out.split("```")[-1]


def test_classify_numbers_snippets_like_the_index():
    blocks = classify("intro\n\n```bash\nls -la /tmp\n```\n\n```text\nout\n```\n\n```text\nstandalone\n```\n\n```python\nprint(42)\n```")
    kinds = [(b.kind, b.index) for b in blocks]
    assert kinds == [("prose", 0), ("snippet", 1), ("output", 0), ("plain", 0), ("snippet", 2)]
