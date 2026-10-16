from lore.search import Searcher, parse


def top(store, q, **kw):
    return Searcher(store).search(q, **kw)


def test_finds_a_topic_by_words(store):
    r = top(store, "reset branch")
    assert r.hits and r.hits[0].item.id in ("mini:1.1", "mini:1.1#1", "mini:term:soft-reset")


def test_title_match_beats_body_match(store):
    r = top(store, "reverting a commit")
    assert r.hits[0].item.id == "mini:1.2"


def test_prefix_matches_the_last_word(store):
    r = top(store, "regul")
    assert any(h.item.id == "mini:2.1" for h in r.hits)


def test_typos_are_repaired(store):
    r = top(store, "reverting a comit")
    assert r.corrected and "commit" in r.corrected
    assert any(h.item.id == "mini:1.2" for h in r.hits)


def test_code_is_searchable(store):
    r = top(store, "git reset --soft")
    assert r.hits[0].item.kind in ("snippet", "topic", "term")
    assert any(h.item.kind == "snippet" and "reset --soft" in h.item.body for h in r.hits)


def test_filters(store):
    assert all(h.item.kind == "snippet" for h in top(store, "kind:snippet git").hits)
    assert all(h.item.kind == "term" for h in top(store, "kind:term reset").hits)
    assert all(h.item.course == "mini" for h in top(store, "in:mini git").hits)
    assert all(h.item.lang == "python" for h in top(store, "lang:python window").hits)


def test_parse_ignores_unknown_filters(store):
    q = parse(store, "in:nonsense kind:wat hello")
    assert q.course is None and q.kind is None
    assert "hello" in q.tokens


def test_excerpt_marks_matched_words(store):
    r = top(store, "undo")
    assert any("\x01" in h.excerpt for h in r.hits)


def test_no_results(store):
    assert top(store, "zzzqqqxxx").hits == []
    assert top(store, "").hits == []
