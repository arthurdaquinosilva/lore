from lore.render import fragments, head, render
from lore.theme import get_theme

THEME = get_theme("pitch")


def test_code_blocks_are_tracked_by_snippet_number():
    md = "Intro text.\n\n```bash\nls -la /tmp\n```\n\nBetween.\n\n```python\nprint('hello world')\n```\n"
    r = render(md, 80, THEME)
    assert sorted(r.spans) == [1, 2]
    first, second = r.spans[1], r.spans[2]
    assert first[1] < second[0]
    assert "ls -la /tmp" in r.plain[first[0] + 1]


def test_output_follows_its_snippet_and_rail_marks_solutions():
    md = "```bash\necho hi there\n```\n\n```text\nhi there\n```\n\n:::details Solution\n\nAnswer here.\n\n:::\n"
    r = render(md, 60, THEME)
    text = "\n".join(r.plain)
    assert "output" in text and "hi there" in text
    assert "▸ Solution" in text and "┆ Answer here." in text


def test_lines_fit_the_width():
    md = "word " * 200
    r = render(md, 50, THEME)
    assert max(len(line) for line in r.plain) <= 50


def test_find_highlight_splits_fragments():
    r = render("The quick brown fox", 40, THEME)
    frags = fragments(r.lines[0], "quick")
    assert any("find" in style and text == "quick" for style, text in frags)


def test_head_never_cuts_inside_a_fence():
    md = "para\n\n```\n" + "x\n" * 400 + "```\n\nafter\n"
    cut = head(md, 100)
    assert cut.count("```") % 2 == 0
