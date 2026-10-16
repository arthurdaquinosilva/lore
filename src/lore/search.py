"""Search: full-text ranking over topics, snippets and terms, with filters, prefixes and typo repair."""

from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import dataclass, field

from lore.store import Item, Store

KINDS = {"topic": ("topic", "guide", "exercise", "summary"), "snippet": ("snippet",), "term": ("term",)}
KIND_ALIASES = {"topics": "topic", "t": "topic", "snippets": "snippet", "code": "snippet", "s": "snippet", "c": "snippet",
                "terms": "term", "def": "term", "defs": "term", "d": "term"}
KIND_PRIOR = {"topic": 1.0, "term": 1.25, "snippet": 0.92, "guide": 0.75, "summary": 0.55, "exercise": 0.45}
TOKEN = re.compile(r"[\w][\w.+#-]*|[-]{1,2}[\w][\w-]*", re.U)
FILTER = re.compile(r"(?:^|\s)(?:(in|course|kind|lang|is):|(@))([\w.+#-]+)(?=\s|$)", re.I)
STOP = {"vs", "versus", "between", "difference", "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "how", "do", "i", "what", "does", "with", "my"}


@dataclass
class Query:
    text: str  # what is left after filters
    course: str | None = None
    kind: str | None = None  # topic | snippet | term
    lang: str | None = None
    tokens: list[str] = field(default_factory=list)


@dataclass
class Hit:
    item: Item
    score: float
    excerpt: str = ""  # plain text with \x01 … \x02 around matched words
    marks: list[str] = field(default_factory=list)
    topic_title: str = ""


@dataclass
class Result:
    hits: list[Hit]
    query: Query
    corrected: str | None = None  # the query as repaired, when a typo was fixed
    loose: bool = False  # True when results match only some of the words


def parse(store: Store, raw: str, course: str | None = None, kind: str | None = None) -> Query:
    q = Query(raw, course, kind)
    for m in list(FILTER.finditer(raw)):
        key, val = (m.group(1) or "@").lower(), m.group(3)
        if key in ("in", "course", "@"):
            found = store.resolve_course(val)
            if found:
                q.course = found
            else:
                continue
        elif key in ("kind", "is"):
            k = KIND_ALIASES.get(val.lower(), val.lower())
            if k not in KINDS:
                continue
            q.kind = k
        elif key == "lang":
            q.lang = val.lower()
        q.text = q.text.replace(m.group(0), " ", 1)
    q.text = " ".join(q.text.split())
    q.tokens = [t.lower() for t in TOKEN.findall(q.text)]
    return q


def _fts_tokens(tokens: list[str]) -> list[str]:
    """Words as the FTS tokenizer would see them, one entry per typed token (`promise.all` -> `promise all`)."""
    out: list[str] = []
    for t in tokens:
        parts = [p for p in re.split(r"[^\w]+", t, flags=re.U) if p]
        if parts:
            out.append(" ".join(parts))
    return out


def _match(groups: list[str], prefix: bool, joiner: str = " AND ") -> str:
    parts = []
    for i, g in enumerate(groups):
        g = g.replace('"', "")
        star = " *" if prefix and i == len(groups) - 1 and len(g.split()[-1]) >= 2 else ""
        parts.append(f'"{g}"{star}')
    return joiner.join(parts)


class Searcher:
    def __init__(self, store: Store):
        self.store = store

    # ── public ────────────────────────────────────────────────────────────

    def search(self, raw: str, course: str | None = None, kind: str | None = None, limit: int = 60) -> Result:
        q = parse(self.store, raw, course, kind)
        words = _fts_tokens(q.tokens)
        if not words:
            return Result([], q)
        significant = [w for w in words if w not in STOP] or words
        flat = [x for g in significant for x in g.split()]
        hits = self._run(q, significant, prefix=True, joiner=" AND ", limit=limit)
        loose = False
        corrected = None
        if len(hits) < 3:
            fixed = self._repair(significant)
            if fixed and fixed != significant:
                more = self._run(q, fixed, prefix=True, joiner=" AND ", limit=limit)
                if more:
                    hits, corrected = more, " ".join(fixed)
                    significant = fixed
        if len(hits) < 3 and len(significant) > 1:
            more = self._run(q, significant, prefix=True, joiner=" OR ", limit=limit)
            seen = {h.item.id for h in hits}
            hits += [h for h in more if h.item.id not in seen]
            loose = len(hits) > 0
        if len(hits) < 3 and len(q.text) >= 3:
            hits += self._substring(q, hits, limit)
        flat = [x for g in significant for x in g.split()]
        hits = self._rank(hits, flat, q)[:limit]
        self._excerpts(hits, flat)
        return Result(hits, q, corrected, loose)

    # ── candidate generation ──────────────────────────────────────────────

    def _filters(self, q: Query) -> tuple[str, list]:
        sql, args = "", []
        if q.course:
            sql += " AND i.course=?"
            args.append(q.course)
        if q.kind:
            kinds = KINDS[q.kind]
            sql += f" AND i.kind IN ({','.join('?' * len(kinds))})"
            args += list(kinds)
        if q.lang:
            sql += " AND i.lang=?"
            args.append(q.lang)
        return sql, args

    def _run(self, q: Query, words: list[str], prefix: bool, joiner: str, limit: int) -> list[Hit]:
        if not words:
            return []
        where, args = self._filters(q)
        sql = (
            "SELECT i.rowid, bm25(fts, 14.0, 5.0, 1.0, 2.2) AS r FROM fts JOIN items i ON i.rowid = fts.rowid "
            f"WHERE fts MATCH ? {where} ORDER BY r LIMIT ?"
        )
        try:
            rows = self.store.db.execute(sql, [_match(words, prefix, joiner), *args, limit * 4]).fetchall()
        except sqlite3.OperationalError:
            return []
        items = self.store.by_rowid([r[0] for r in rows])
        return [Hit(items[rid], -score) for rid, score in rows if rid in items]

    def _substring(self, q: Query, have: list[Hit], limit: int) -> list[Hit]:
        """Names containing the typed text anywhere: `usest` finds useState."""
        where, args = self._filters(q)
        text = q.text.replace('"', "")
        if len(text) < 3:
            return []
        sql = f'SELECT i.rowid FROM tri JOIN items i ON i.rowid = tri.rowid WHERE tri MATCH ? {where} LIMIT ?'
        try:
            rows = self.store.db.execute(sql, [f'"{text}"', *args, limit]).fetchall()
        except sqlite3.OperationalError:
            return []
        seen = {h.item.id for h in have}
        items = self.store.by_rowid([r[0] for r in rows])
        return [Hit(it, 0.5) for it in items.values() if it.id not in seen]

    def _repair(self, groups: list[str]) -> list[str] | None:
        """Fix words the index has never seen (`rebsae` -> `rebase`) using the vocabulary of titles."""
        vocab = self.store.vocab()
        known = set(vocab)
        out, changed = [], False
        for g in groups:
            fixed = []
            for w in g.split():
                if w in known or len(w) < 4 or w.isdigit():
                    fixed.append(w)
                    continue
                if self.store.db.execute('SELECT 1 FROM fts WHERE fts MATCH ? LIMIT 1', (f'"{w}" *',)).fetchone():
                    fixed.append(w)
                    continue
                close = difflib.get_close_matches(w, vocab, n=1, cutoff=0.72)
                fixed.append(close[0] if close else w)
                changed = changed or bool(close)
            out.append(" ".join(fixed))
        return out if changed else None

    # ── ranking ───────────────────────────────────────────────────────────

    def _rank(self, hits: list[Hit], words: list[str], q: Query) -> list[Hit]:
        joined = " ".join(words)
        per_parent: dict[str, int] = {}
        for h in hits:
            it = h.item
            title = it.title.lower()
            caption = it.caption.lower()
            score = max(h.score, 0.01)
            tl = re.sub(r"[^\w]+", " ", title).split()
            if re.sub(r"[^\w]+", " ", title).strip() == joined:
                score *= 3.0
            elif all(any(t.startswith(w) for t in tl) for w in words):
                score *= 1.7
            elif all(w in title for w in words):
                score *= 1.35
            if it.kind == "snippet":
                first = re.sub(r"[^\w]+", " ", title).strip()
                if first.startswith(joined):
                    score *= 1.5
                elif all(w in first for w in words):
                    score *= 1.2
                elif all(w in caption for w in words):
                    score *= 1.1
            if it.kind == "term" and any(w == title for w in words):
                score *= 1.5
            if it.number and it.number.endswith(".0"):
                score *= 0.85
            if it.parent and "-exercises" in it.parent:
                score *= 0.4
            h.score = score * KIND_PRIOR.get(it.kind, 1.0)
        hits.sort(key=lambda h: -h.score)
        # keep the list varied: at most three results from the same topic
        kept: list[Hit] = []
        for h in hits:
            key = h.item.parent or h.item.id
            if per_parent.get(key, 0) >= 3:
                continue
            per_parent[key] = per_parent.get(key, 0) + 1
            kept.append(h)
        topics = {h.item.id: h.item.title for h in kept if h.item.kind not in ("snippet", "term")}
        need = {h.item.parent for h in kept if h.item.parent and h.item.parent not in topics}
        for pid in need:
            p = self.store.get(pid)  # type: ignore[arg-type]
            if p:
                topics[p.id] = p.title
        for h in kept:
            h.topic_title = topics.get(h.item.parent or h.item.id, "")
            h.marks = words
        return kept

    def _excerpts(self, hits: list[Hit], words: list[str]) -> None:
        for h in hits[:40]:
            it = h.item
            text = it.caption if it.kind == "snippet" else it.body
            if it.kind in ("topic", "guide", "exercise", "summary"):
                from lore.htmlclean import plain

                text = plain(text)
            elif it.kind == "term":
                text = re.sub(r"[*`]", "", text)
            h.excerpt = excerpt(text, words, 150) if text else ""


def excerpt(text: str, words: list[str], width: int = 150) -> str:
    """A window of `text` around the best match, matched words wrapped in \\x01…\\x02."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    best, at = -1, 0
    for w in words:
        m = re.search(r"(?<![\w])" + re.escape(w), flat, re.I)
        if m and (best < 0 or m.start() < best):
            best, at = m.start(), m.start()
    if best < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, at - width // 3)
    if start:
        sp = flat.find(" ", start)
        start = sp + 1 if 0 <= sp < at else start
    chunk = flat[start: start + width]
    out = ("…" if start else "") + chunk + ("…" if start + width < len(flat) else "")
    return mark(out, words)


def mark(text: str, words: list[str]) -> str:
    if not words:
        return text
    pat = re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)) + r")\w*", re.I)
    return pat.sub(lambda m: "\x01" + m.group(0) + "\x02", text)
