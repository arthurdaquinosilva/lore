"""Build the offline search index from the course sources."""

from __future__ import annotations

import json
import re
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Callable

from lore import __version__
from lore.corpus import Course, load_all, parse_course
from lore.htmlclean import plain
from lore.paths import index_path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE courses (key TEXT PRIMARY KEY, title TEXT, brand TEXT, ord INTEGER);
CREATE TABLE items (
    rowid INTEGER PRIMARY KEY,
    id TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,          -- topic | guide | exercise | summary | snippet | term
    course TEXT NOT NULL,
    parent TEXT,                 -- the topic a snippet or term was found in
    section_no INTEGER,
    section TEXT,
    number TEXT,
    title TEXT,
    slug TEXT,
    seq INTEGER,                 -- reading order inside the course
    lang TEXT,
    sig TEXT,
    caption TEXT,
    body BLOB,                   -- zlib: markdown for topics, code for snippets, definition for terms
    aux BLOB                     -- zlib: a snippet's printed output
);
CREATE INDEX items_course ON items(course, seq);
CREATE INDEX items_parent ON items(parent);
CREATE INDEX items_slug ON items(course, slug);
CREATE INDEX items_sig ON items(sig);
CREATE VIRTUAL TABLE fts USING fts5(title, head, body, code, tokenize='porter unicode61 remove_diacritics 2', content='');
CREATE VIRTUAL TABLE tri USING fts5(name, tokenize='trigram', content='');
CREATE TABLE vocab (word TEXT PRIMARY KEY, n INTEGER);
"""

WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")


TRIVIAL = re.compile(r"^\s*(#|//|/\*|\*|import\b|from\b.*\bimport\b|using\b|package\b|use strict|<\?php|\$ ?$|-- )")


def snippet_title(code: str) -> str:
    """The line that names a snippet: the first one that is not an import, a comment or a shebang."""
    lines = [ln.strip() for ln in code.split("\n") if ln.strip()]
    for ln in lines:
        if not TRIVIAL.match(ln) and len(ln) > 2:
            return ln[:120]
    return (lines[0] if lines else code)[:120]


def _z(text: str) -> bytes:
    return zlib.compress(text.encode("utf-8"), 6)


def source_signature(source: Path) -> dict[str, float]:
    return {p.name: p.stat().st_mtime for p in sorted(source.glob("*.md"))}


def build(source: Path, out: Path | None = None, progress: Callable[[str], None] | None = None) -> dict[str, int]:
    out = out or index_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    files = sorted(p for p in source.glob("*.md") if "===META===" in p.read_text(encoding="utf-8")[:200])
    if not files:
        raise FileNotFoundError(f"no course sources (*.md with a ===META=== header) in {source}")
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    counts = {"courses": 0, "topics": 0, "snippets": 0, "terms": 0}
    vocab: dict[str, int] = {}
    rowid = 0

    def put(**f) -> int:
        nonlocal rowid
        rowid += 1
        db.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rowid, f["id"], f["kind"], f["course"], f.get("parent"), f.get("section_no"), f.get("section"),
             f.get("number", ""), f.get("title", ""), f.get("slug", ""), f.get("seq", 0), f.get("lang", ""),
             f.get("sig", ""), f.get("caption", ""), _z(f.get("body", "")), _z(f["aux"]) if f.get("aux") else None),
        )
        return rowid

    def words(text: str) -> None:
        for w in WORD.findall(text):
            w = w.lower()
            vocab[w] = vocab.get(w, 0) + 1

    for order, path in enumerate(files):
        if progress:
            progress(path.stem)
        course = parse_course(path)
        db.execute("INSERT INTO courses VALUES (?,?,?,?)", (course.key, course.title, course.brand, order))
        counts["courses"] += 1
        for e in course.entries:
            head = f"{e.section} {course.brand}"
            rid = put(id=e.id, kind=e.kind, course=e.course, section_no=e.section_no, section=e.section,
                      number=e.number, title=e.title, slug=e.slug, seq=e.seq * 100, body=e.body)
            code = "\n".join(s.code for s in e.snippets)
            db.execute("INSERT INTO fts(rowid,title,head,body,code) VALUES (?,?,?,?,?)",
                       (rid, e.title, head, plain(e.body), code))
            db.execute("INSERT INTO tri(rowid,name) VALUES (?,?)", (rid, e.title))
            words(e.title)
            counts["topics"] += 1
            for s in e.snippets:
                first = snippet_title(s.code)
                rid = put(id=s.id, kind="snippet", course=s.course, parent=e.id, section_no=e.section_no,
                          section=e.section, number=e.number, title=first[:120], slug=e.slug,
                          seq=e.seq * 100 + s.index, lang=s.lang, sig=s.sig, caption=s.caption, body=s.code, aux=s.output)
                db.execute("INSERT INTO fts(rowid,title,head,body,code) VALUES (?,?,?,?,?)",
                           (rid, s.caption, f"{e.title} {e.section}", s.caption + "\n" + s.output, s.code))
                db.execute("INSERT INTO tri(rowid,name) VALUES (?,?)", (rid, first[:120]))
                counts["snippets"] += 1
            for t in e.terms:
                if db.execute("SELECT 1 FROM items WHERE id=?", (t.id,)).fetchone():
                    continue
                rid = put(id=t.id, kind="term", course=t.course, parent=e.id, section_no=e.section_no,
                          section=e.section, number=e.number, title=t.name, slug=e.slug, seq=e.seq * 100 + 99,
                          body=t.definition)
                db.execute("INSERT INTO fts(rowid,title,head,body,code) VALUES (?,?,?,?,?)",
                           (rid, t.name, f"{e.title} {e.section}", t.definition, ""))
                db.execute("INSERT INTO tri(rowid,name) VALUES (?,?)", (rid, t.name))
                words(t.name)
                counts["terms"] += 1
    db.executemany("INSERT INTO vocab VALUES (?,?)", vocab.items())
    meta = {
        "schema": str(SCHEMA_VERSION),
        "lore": __version__,
        "source": str(source.resolve()),
        "built_at": str(int(time.time())),
        "signature": json.dumps(source_signature(source)),
        "counts": json.dumps(counts),
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.execute("INSERT INTO fts(fts) VALUES('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(out)
    return counts
