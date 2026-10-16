"""Aliases: short names for the pieces of knowledge you come back to.

An alias points at an index entry (a topic, a snippet or a term) or holds text of its own. Aliases live in
`aliases.json` next to the index and survive `lore index`: a pointer remembers the course, the title slug
and, for a snippet, a fingerprint of its code, so it can be found again after the courses are renumbered.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from lore.paths import aliases_path
from lore.store import Item, Store

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")


class AliasError(ValueError):
    pass


@dataclass
class Alias:
    name: str
    kind: str  # "ref" | "text"
    target: str = ""
    course: str = ""
    slug: str = ""
    sig: str = ""
    target_kind: str = ""
    title: str = ""
    text: str = ""
    note: str = ""
    created: int = 0
    used: int = 0
    last_used: int = 0

    @property
    def summary(self) -> str:
        return self.title or (self.text.strip().split("\n")[0][:80] if self.text else self.target)


@dataclass
class Resolved:
    alias: Alias
    item: Item | None  # None for text aliases or when the target vanished
    moved: bool = False  # found again by slug/fingerprint rather than by id
    missing: bool = False


def clean_name(name: str) -> str:
    return name.strip().lstrip("@")


def valid(name: str) -> bool:
    return bool(NAME.match(name))


class Aliases:
    def __init__(self, path: Path | None = None):
        self.path = path or aliases_path()
        self.items: dict[str, Alias] = {}
        self.load()

    def load(self) -> None:
        self.items = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, raw in data.get("aliases", {}).items():
            fields = {k: v for k, v in raw.items() if k in Alias.__dataclass_fields__ and k != "name"}
            self.items[name] = Alias(name=name, **fields)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "aliases": {n: {k: v for k, v in a.__dict__.items() if k != "name" and v not in ("", 0)} | {"kind": a.kind}
                                             for n, a in sorted(self.items.items())}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # ── editing ───────────────────────────────────────────────────────────

    def check_name(self, name: str, store: Store | None = None) -> str:
        name = clean_name(name)
        if not valid(name):
            raise AliasError("a name is 1–32 letters, digits, '.', '_' or '-', starting with a letter or digit")
        if store and store.resolve_course(name) == name.lower():
            raise AliasError(f"'{name}' is a course; pick another name")
        return name

    def add_ref(self, name: str, item: Item, note: str = "", store: Store | None = None) -> tuple[Alias, bool]:
        """Create or replace. Returns (alias, replaced_existing)."""
        name = self.check_name(name, store)
        replaced = name in self.items
        a = Alias(name, "ref", target=item.id, course=item.course, slug=item.slug, sig=item.sig, target_kind=item.kind,
                  title=item.title, note=note, created=int(time.time()))
        if replaced:
            a.used, a.last_used = self.items[name].used, self.items[name].last_used
        self.items[name] = a
        self.save()
        return a, replaced

    def add_text(self, name: str, text: str, note: str = "", store: Store | None = None) -> tuple[Alias, bool]:
        name = self.check_name(name, store)
        if not text.strip():
            raise AliasError("nothing to save: the text is empty")
        replaced = name in self.items
        a = Alias(name, "text", text=text.rstrip("\n"), note=note, created=int(time.time()))
        if replaced:
            a.used, a.last_used = self.items[name].used, self.items[name].last_used
        self.items[name] = a
        self.save()
        return a, replaced

    def remove(self, name: str) -> bool:
        name = clean_name(name)
        if name in self.items:
            del self.items[name]
            self.save()
            return True
        return False

    def rename(self, old: str, new: str, store: Store | None = None) -> None:
        old = clean_name(old)
        if old not in self.items:
            raise AliasError(f"no alias named '{old}'")
        new = self.check_name(new, store)
        if new in self.items:
            raise AliasError(f"'{new}' already exists")
        a = self.items.pop(old)
        a.name = new
        self.items[new] = a
        self.save()

    def set_note(self, name: str, note: str) -> None:
        self.items[clean_name(name)].note = note
        self.save()

    def touch(self, name: str) -> None:
        a = self.items.get(clean_name(name))
        if a:
            a.used += 1
            a.last_used = int(time.time())
            self.save()

    # ── lookup ────────────────────────────────────────────────────────────

    def get(self, name: str) -> Alias | None:
        return self.items.get(clean_name(name))

    def ordered(self) -> list[Alias]:
        """Most recently used first, then by name."""
        return sorted(self.items.values(), key=lambda a: (-a.last_used, a.name))

    def match(self, prefix: str) -> list[Alias]:
        p = clean_name(prefix).lower()
        return [a for a in self.ordered() if a.name.lower().startswith(p) or p in a.name.lower() or p in a.summary.lower()]

    def resolve(self, alias: Alias, store: Store) -> Resolved:
        if alias.kind == "text":
            return Resolved(alias, None)
        item = store.get(alias.target)
        if item and (item.slug == alias.slug or not alias.slug) and (not alias.sig or item.sig == alias.sig or item.kind != "snippet"):
            return Resolved(alias, item)
        moved = store.find_moved(alias.course, alias.slug, alias.sig, alias.target_kind)
        if moved:
            return Resolved(alias, moved, moved=True)
        if item:  # same id, content changed: better than nothing
            return Resolved(alias, item, moved=True)
        return Resolved(alias, None, missing=True)


@dataclass
class Recent:
    """The last things you opened, and the last things you searched for."""

    path: Path
    opened: list[dict] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Recent":
        r = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            r.opened = list(data.get("opened", []))[:50]
            r.queries = list(data.get("queries", []))[:200]
        except (OSError, ValueError):
            pass
        return r

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"opened": self.opened[:50], "queries": self.queries[:200]}, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def opened_item(self, item: Item) -> None:
        self.opened = [o for o in self.opened if o["id"] != item.id]
        self.opened.insert(0, {"id": item.id, "title": item.title, "course": item.course, "kind": item.kind, "slug": item.slug, "sig": item.sig})
        self.save()

    def searched(self, query: str) -> None:
        q = query.strip()
        if len(q) < 2:
            return
        self.queries = [x for x in self.queries if x != q]
        self.queries.insert(0, q)
        self.save()
