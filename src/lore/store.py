"""Read access to the index."""

from __future__ import annotations

import json
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path

from lore.paths import index_path


@dataclass
class Item:
    rowid: int
    id: str
    kind: str
    course: str
    parent: str | None
    section_no: int
    section: str
    number: str
    title: str
    slug: str
    seq: int
    lang: str
    sig: str
    caption: str
    body: str
    aux: str

    @property
    def is_snippet(self) -> bool:
        return self.kind == "snippet"

    @property
    def label(self) -> str:
        """`3.5` or `§3` style position, empty for guides."""
        return self.number if self.number and not self.number.endswith(".0") else (f"§{self.section_no}" if self.section_no else "")


COLUMNS = "rowid,id,kind,course,parent,section_no,section,number,title,slug,seq,lang,sig,caption,body,aux"


def _row(r: tuple) -> Item:
    z = lambda b: zlib.decompress(b).decode("utf-8") if b else ""  # noqa: E731
    return Item(r[0], r[1], r[2], r[3], r[4], r[5] or 0, r[6] or "", r[7] or "", r[8] or "", r[9] or "", r[10] or 0,
                r[11] or "", r[12] or "", r[13] or "", z(r[14]), z(r[15]))


class IndexMissing(Exception):
    pass


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or index_path()
        if not self.path.is_file():
            raise IndexMissing(str(self.path))
        self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self._meta: dict[str, str] | None = None
        self._courses: dict[str, tuple[str, str, int]] | None = None
        self._vocab: list[str] | None = None

    def close(self) -> None:
        self.db.close()

    @property
    def meta(self) -> dict[str, str]:
        if self._meta is None:
            self._meta = dict(self.db.execute("SELECT key,value FROM meta"))
        return self._meta

    @property
    def counts(self) -> dict[str, int]:
        return json.loads(self.meta.get("counts", "{}"))

    @property
    def courses(self) -> dict[str, tuple[str, str, int]]:
        """key -> (title, brand, order)"""
        if self._courses is None:
            self._courses = {k: (t, b, o) for k, t, b, o in self.db.execute("SELECT key,title,brand,ord FROM courses ORDER BY ord")}
        return self._courses

    def course_counts(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT course, COUNT(*) FROM items WHERE kind IN ('topic','guide','exercise','summary') GROUP BY course"))

    def resolve_course(self, text: str) -> str | None:
        """Accept a key, a brand or an unambiguous prefix: `git`, `Git`, `type` -> typescript."""
        t = text.lower().strip()
        if t in self.courses:
            return t
        for k, (title, brand, _o) in self.courses.items():
            if t in (brand.lower(), title.lower()):
                return k
        hits = [k for k, (title, brand, _o) in self.courses.items()
                if k.startswith(t) or brand.lower().startswith(t) or title.lower().startswith(t)]
        return hits[0] if len(hits) == 1 else None

    def get(self, id_: str) -> Item | None:
        r = self.db.execute(f"SELECT {COLUMNS} FROM items WHERE id=?", (id_,)).fetchone()
        return _row(r) if r else None

    def by_rowid(self, rowids: list[int]) -> dict[int, Item]:
        if not rowids:
            return {}
        q = ",".join("?" * len(rowids))
        return {r[0]: _row(r) for r in self.db.execute(f"SELECT {COLUMNS} FROM items WHERE rowid IN ({q})", rowids)}

    def find_moved(self, course: str, slug: str, sig: str = "", kind: str = "") -> Item | None:
        """Re-find an item after the index was rebuilt and numbering moved."""
        if sig:
            r = self.db.execute(f"SELECT {COLUMNS} FROM items WHERE sig=? AND course=? LIMIT 1", (sig, course)).fetchone()
            if r:
                return _row(r)
        if kind == "snippet":
            return None
        r = self.db.execute(f"SELECT {COLUMNS} FROM items WHERE course=? AND slug=? AND kind IN ('topic','guide','exercise','summary') ORDER BY seq LIMIT 1",
                            (course, slug)).fetchone()
        return _row(r) if r else None

    def topic_of(self, item: Item) -> Item | None:
        if item.kind in ("topic", "guide", "exercise", "summary"):
            return item
        return self.get(item.parent) if item.parent else None

    def snippets_of(self, topic_id: str) -> list[Item]:
        return [_row(r) for r in self.db.execute(f"SELECT {COLUMNS} FROM items WHERE parent=? AND kind='snippet' ORDER BY seq", (topic_id,))]

    def neighbours(self, topic: Item) -> tuple[Item | None, Item | None]:
        kinds = "('topic','guide','exercise','summary')"
        prev = self.db.execute(f"SELECT {COLUMNS} FROM items WHERE course=? AND kind IN {kinds} AND seq<? ORDER BY seq DESC LIMIT 1", (topic.course, topic.seq)).fetchone()
        nxt = self.db.execute(f"SELECT {COLUMNS} FROM items WHERE course=? AND kind IN {kinds} AND seq>? ORDER BY seq LIMIT 1", (topic.course, topic.seq)).fetchone()
        return (_row(prev) if prev else None, _row(nxt) if nxt else None)

    def outline(self, course: str, section_no: int) -> list[Item]:
        """The topics of one section, in reading order (bodies are not loaded)."""
        rows = self.db.execute(
            "SELECT rowid,id,kind,course,parent,section_no,section,number,title,slug,seq,lang,sig,caption,'' ,NULL FROM items "
            "WHERE course=? AND section_no=? AND kind IN ('topic','guide','exercise','summary') ORDER BY seq", (course, section_no))
        return [_row(r) for r in rows]

    def sections(self, course: str) -> list[tuple[int, str]]:
        return [(n, s) for n, s in self.db.execute(
            "SELECT DISTINCT section_no, section FROM items WHERE course=? AND kind IN ('topic','guide','exercise','summary') ORDER BY section_no", (course,))]

    def vocab(self) -> list[str]:
        if self._vocab is None:
            self._vocab = [w for (w,) in self.db.execute("SELECT word FROM vocab WHERE n>=1")]
        return self._vocab

    def stale(self) -> bool:
        """True when the course sources changed since the index was built."""
        src = Path(self.meta.get("source", ""))
        if not src.is_dir():
            return False
        try:
            then = json.loads(self.meta.get("signature", "{}"))
            now = {p.name: p.stat().st_mtime for p in src.glob("*.md")}
        except (OSError, ValueError):
            return False
        return any(now.get(k, 0) > v + 1 for k, v in then.items()) or set(now) - set(then) != set()
