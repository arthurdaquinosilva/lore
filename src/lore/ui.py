"""The full-screen interface: a search prompt with live suggestions and a preview, and a reader."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    ConditionalContainer,
    DynamicContainer,
    Float,
    FloatContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import DynamicStyle
from prompt_toolkit.utils import get_cwidth

from lore import __version__, clipboard
from lore.aliases import Alias, AliasError, Aliases, Recent, Resolved
from lore.banner import pixel_rows
from lore.config import Settings
from lore.render import Rendered, fragments, head, render
from lore.search import Hit, Result, Searcher
from lore.store import Item, Store
from lore.theme import Theme, course_color

KIND_ORDER = [None, "topic", "snippet", "term"]
KIND_NAMES = {None: "everything", "topic": "topics", "snippet": "snippets", "term": "terms"}
ICON = {"topic": "▤", "guide": "▤", "summary": "≡", "exercise": "✎", "snippet": "❯", "term": "◆"}
FLASH = 3.0


@dataclass
class Row:
    kind: str  # hit | alias | recent | query | header
    item: Item | None = None
    hit: Hit | None = None
    alias: Alias | None = None
    resolved: Resolved | None = None
    text: str = ""  # header or query text
    title: str = ""
    excerpt: str = ""

    @property
    def selectable(self) -> bool:
        return self.kind != "header"


@dataclass
class Reader:
    topic: Item
    origin: Item  # what was asked for: the topic, a snippet of it, or a term
    snippets: list[Item]
    rendered: Rendered
    offset: int = 0
    sel: int | None = None  # selected snippet index (1-based)
    find: str = ""
    matches: list[int] = field(default_factory=list)
    match_i: int = 0
    direct: bool = False  # opened from the command line: leaving quits
    alias: Alias | None = None
    text: str | None = None  # a text alias, shown instead of a topic


@dataclass
class Outcome:
    """What to print after the screen closes (`p` in the reader)."""

    text: str = ""
    markdown: bool = False
    lang: str = ""


def clip(text: str, width: int) -> str:
    if get_cwidth(text) <= width:
        return text
    out, w = "", 0
    for ch in text:
        cw = get_cwidth(ch)
        if w + cw > width - 1:
            break
        out, w = out + ch, w + cw
    return out + "…"


def pad(frags: StyleAndTextTuples, width: int, style: str = "") -> StyleAndTextTuples:
    used = sum(get_cwidth(t) for _s, t in frags)
    return frags + ([(style, " " * (width - used))] if used < width else [])


def marked(text: str, base: str, hi: str) -> StyleAndTextTuples:
    """Split text on the \\x01…\\x02 match markers produced by the search."""
    out: StyleAndTextTuples = []
    for i, chunk in enumerate(re.split(r"[\x01\x02]", text)):
        if not chunk:
            continue
        # chunks alternate plain, marked, plain, ... because each \x01 is followed by its \x02
        out.append((hi if i % 2 else base, chunk))
    return out


def unmd(text: str) -> str:
    return re.sub(r"[*`]", "", text)


def plain_title(text: str) -> str:
    return re.sub(r"`([^`]*)`", r"\1", text).strip()


class Placeholder(Processor):
    def __init__(self, text):
        self.text = text

    def apply_transformation(self, ti: TransformationInput) -> Transformation:
        if ti.lineno == 0 and not ti.document.text:
            return Transformation([("class:placeholder", self.text())])
        return Transformation(ti.fragments)


class LoreApp:
    def __init__(self, store: Store, aliases: Aliases, recent: Recent, settings: Settings, theme: Theme,
                 query: str = "", course: str | None = None, kind: str | None = None, output=None):
        self._output = output
        self.store, self.aliases, self.recent, self.settings, self.theme = store, aliases, recent, settings, theme
        self.searcher = Searcher(store)
        self.course, self.kind = course, kind
        self.mode = "search"  # search | reader
        self.overlay: str | None = None  # help | toc
        self.prompt: str | None = None  # alias | find
        self.rows: list[Row] = []
        self.sel = 0
        self.top = 0  # first visible row
        self.result: Result | None = None
        self.elapsed = 0.0
        self.reader: Reader | None = None
        self.flash: tuple[str, float] | None = None
        self.alias_target: Item | None = None
        self.alias_text: str | None = None
        self.confirm: str | None = None  # a pending "press again to confirm" key
        self.preview_scroll = 0
        self._preview_cache: dict[tuple, Rendered] = {}
        self._reader_cache: dict[tuple, Rendered] = {}
        self.toc_rows: list[Item | str] = []
        self.toc_sel = 0
        self.outcome: Outcome | None = None
        self.colors = {k: i for i, k in enumerate(store.courses)}
        self.stale = store.stale()

        self.query_buf = Buffer(on_text_changed=self._on_query, multiline=False)
        self.alias_buf = Buffer(multiline=False)
        self.find_buf = Buffer(multiline=False, on_text_changed=self._on_find)
        self.query_win = self._make_input(self.query_buf)
        self.alias_win = self._make_input(self.alias_buf)
        self.find_win = self._make_input(self.find_buf)
        self.list_window = Window(FormattedTextControl(self._list_fragments, focusable=False), wrap_lines=False)
        self.preview_window = Window(FormattedTextControl(self._preview_fragments, focusable=False), wrap_lines=False)
        self.reader_window = Window(FormattedTextControl(self._reader_fragments, focusable=True, show_cursor=False), wrap_lines=False)
        self.toc_window = Window(FormattedTextControl(self._toc_fragments, focusable=False), wrap_lines=False)
        self.app = self._build_app()
        if query:
            self.query_buf.text = query
        else:
            self._refresh()

    # ── small helpers ─────────────────────────────────────────────────────

    def _size(self):
        app = getattr(self, "app", None)
        if app is not None:
            return app.output.get_size()
        import shutil

        return shutil.get_terminal_size((100, 30))

    @property
    def cols(self) -> int:
        return self._size().columns

    @property
    def lines(self) -> int:
        s = self._size()
        return getattr(s, "rows", None) or s.lines

    def say(self, text: str) -> None:
        self.flash = (text, time.monotonic() + FLASH)
        try:
            self.app.loop.call_later(FLASH + 0.05, self.app.invalidate)  # type: ignore[union-attr]
        except Exception:
            pass
        self.app.invalidate()

    def brand(self, course: str) -> str:
        return self.store.courses[course][1] if course in self.store.courses else course

    def color(self, course: str) -> str:
        return course_color(self.theme.p, self.colors.get(course, 0))

    @property
    def show_preview(self) -> bool:
        pref = self.settings.preview
        return pref == "on" or (pref == "auto" and self.cols >= 100)

    @property
    def list_width(self) -> int:
        if not self.show_preview:
            return self.cols
        return max(44, min(66, int(self.cols * 0.44)))

    @property
    def banner_on(self) -> bool:
        return self.mode == "search" and not self.query_buf.text and self.lines >= 34

    @property
    def body_height(self) -> int:
        info = self.list_window.render_info
        if info is not None:
            return info.window_height
        return max(4, self.lines - (16 if self.banner_on else 8))

    # ── searching ─────────────────────────────────────────────────────────

    def _on_query(self, _buf: Buffer) -> None:
        self.preview_scroll = 0
        self._refresh()
        self.app.invalidate()

    def _refresh(self) -> None:
        text = self.query_buf.text.strip()
        rows: list[Row] = []
        if not text:
            self.result = None
            rows = self._empty_rows()
        else:
            t = time.perf_counter()
            self.result = self.searcher.search(text, self.course, self.kind, limit=80)
            self.elapsed = (time.perf_counter() - t) * 1000
            rows = [Row("hit", item=h.item, hit=h) for h in self.result.hits]
            # an alias whose name matches what is being typed comes first
            name = text.lstrip("@").lower()
            if name and not self.course:
                matches = [a for a in self.aliases.ordered() if a.name.lower().startswith(name)]
                rows = [Row("alias", alias=a, resolved=self.aliases.resolve(a, self.store)) for a in matches[:4]] + rows
        self.rows = rows
        self.sel = next((i for i, r in enumerate(rows) if r.selectable), 0)
        self.top = 0

    def _empty_rows(self) -> list[Row]:
        rows: list[Row] = []
        als = self.aliases.ordered()[:8]
        if als:
            rows.append(Row("header", text="ALIASES"))
            rows += [Row("alias", alias=a, resolved=self.aliases.resolve(a, self.store)) for a in als]
        if self.recent.opened:
            rows.append(Row("header", text="RECENTLY OPENED"))
            for o in self.recent.opened[:8]:
                it = self.store.get(o["id"]) or self.store.find_moved(o["course"], o["slug"], o.get("sig", ""), o["kind"])
                if it:
                    rows.append(Row("recent", item=it))
        if self.recent.queries:
            rows.append(Row("header", text="RECENT SEARCHES"))
            rows += [Row("query", text=q) for q in self.recent.queries[:5]]
        if not rows:
            rows.append(Row("header", text="TRY"))
            for q in ("git rebase --onto", "useeffect cleanup", "kind:term idempotent", "in:sql window functions", "lang:bash tar"):
                rows.append(Row("query", text=q))
        return rows

    def move(self, step: int) -> None:
        if not self.rows:
            return
        i = self.sel
        while True:
            i += step
            if i < 0 or i >= len(self.rows):
                return
            if self.rows[i].selectable:
                self.sel = i
                break
        self.preview_scroll = 0
        self._keep_visible()

    def _keep_visible(self) -> None:
        per = 2
        visible = max(1, self.body_height // per)
        if self.sel < self.top:
            self.top = self.sel
            if self.top > 0 and self.rows[self.top - 1].kind == "header":
                self.top -= 1
        elif self.sel >= self.top + visible:
            self.top = self.sel - visible + 1

    def current(self) -> Row | None:
        return self.rows[self.sel] if 0 <= self.sel < len(self.rows) and self.rows[self.sel].selectable else None

    def cycle_kind(self) -> None:
        i = KIND_ORDER.index(self.kind)
        self.kind = KIND_ORDER[(i + 1) % len(KIND_ORDER)]
        self._refresh()
        self.say(f"showing {KIND_NAMES[self.kind]}")

    def cycle_course(self) -> None:
        keys = [None, *self.store.courses]
        i = keys.index(self.course) if self.course in keys else 0
        self.course = keys[(i + 1) % len(keys)]
        self._refresh()
        self.say("all courses" if not self.course else self.store.courses[self.course][0])

    # ── list rendering ────────────────────────────────────────────────────

    def _row_lines(self, row: Row, selected: bool, width: int) -> list[StyleAndTextTuples]:
        sel = " class:row.selected" if selected else ""
        cursor = ("class:row.cursor" + sel, "▌ ") if selected else ("class:row" + sel, "  ")
        title_style = "class:row.title.selected" if selected else "class:row.title"
        mark_style = "class:row.mark" + sel
        if row.kind == "header":
            return [[("class:section.head", "  " + row.text)], [("", "")]]
        meta: StyleAndTextTuples = []
        icon, icon_style = "•", "class:kind.recent"
        title_frags: StyleAndTextTuples
        second: StyleAndTextTuples = []
        if row.kind == "query":
            icon, icon_style = "⌕", "class:kind.recent"
            title_frags = [(title_style + sel, row.text)]
        elif row.kind == "alias" and row.alias:
            a = row.alias
            icon, icon_style = "★", "class:kind.alias"
            title_frags = [("class:kind.alias" + (" bold" if selected else "") + sel, "@" + a.name)]
            res = row.resolved
            target = res.item.title if res and res.item else a.summary
            if res and res.missing:
                second = [("class:status.warn" + sel, "target no longer in the index — search for it again")]
            else:
                second = [("class:row.excerpt" + sel, clip(plain_title(a.note or target), width - 6))]
            course = (res.item.course if res and res.item else a.course) if a.kind == "ref" else ""
            if course:
                meta = [(f"fg:{self.color(course)}" + sel, self.brand(course))]
            else:
                meta = [("class:row.meta" + sel, "note")]
        else:
            it = row.item
            assert it is not None
            icon = ICON.get(it.kind, "•")
            icon_style = f"class:kind.{it.kind if it.kind in ('topic', 'snippet', 'term', 'guide') else 'topic'}"
            raw = row.hit.item.title if row.hit else it.title
            raw = plain_title(raw)
            marks = row.hit.marks if row.hit else []
            title_frags = self._mark_title(raw, marks, title_style + sel, mark_style)
            if row.kind == "recent":
                icon, icon_style = "↺", "class:kind.recent"
            where = f"{self.brand(it.course)} {it.label}".strip()
            meta = [(f"fg:{self.color(it.course)}" + sel, where)]
            if it.kind == "snippet" and it.lang:
                meta = [("class:row.meta" + sel, it.lang + "  "), *meta]
            if row.hit and row.hit.excerpt:
                second = marked(row.hit.excerpt, "class:row.excerpt" + sel, mark_style)
            elif it.kind == "snippet":
                second = [("class:row.excerpt" + sel, it.caption)]
            else:
                second = [("class:row.excerpt" + sel, f"{it.section}" if it.kind != "term" else unmd(it.body))]
        meta_w = sum(get_cwidth(t) for _s, t in meta)
        avail = max(8, width - 6 - meta_w - 1)
        line1 = [cursor, (icon_style + sel, icon + " ")] + self._fit(title_frags, avail)
        gap = width - sum(get_cwidth(t) for _s, t in line1) - meta_w - 1
        line1 += [("class:row" + sel, " " * max(1, gap))] + meta + [("class:row" + sel, " ")]
        line1 = pad(line1, width, "class:row" + sel)
        line2 = [("class:row" + sel, "    ")] + self._fit(second, width - 6)
        line2 = pad(line2, width, "class:row" + sel)
        return [line1, line2]

    def _mark_title(self, text: str, words: list[str], base: str, hi: str) -> StyleAndTextTuples:
        if not words:
            return [(base, text)]
        pat = re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)) + r")", re.I)
        out: StyleAndTextTuples = []
        pos = 0
        for m in pat.finditer(text):
            if m.start() > pos:
                out.append((base, text[pos:m.start()]))
            out.append((hi, m.group(0)))
            pos = m.end()
        if pos < len(text):
            out.append((base, text[pos:]))
        return out

    @staticmethod
    def _fit(frags: StyleAndTextTuples, width: int) -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        used = 0
        for style, text in frags:
            text = text.replace("\n", " ")
            w = get_cwidth(text)
            if used + w <= width:
                out.append((style, text))
                used += w
            else:
                out.append((style, clip(text, width - used + 0)))
                break
        return out

    def _list_fragments(self) -> StyleAndTextTuples:
        width = self.list_width - (1 if self.show_preview else 0)
        height = self.body_height
        out: StyleAndTextTuples = []
        if not self.rows or (self.result is not None and not self.result.hits and not any(r.kind == "alias" for r in self.rows)):
            return self._nothing_found(width)
        used = 0
        i = self.top
        while i < len(self.rows) and used < height:
            row = self.rows[i]
            lines = self._row_lines(row, i == self.sel, width)
            if row.kind == "header" and i != self.top and used + 2 <= height:
                out.append(("", "\n"))
                used += 1
            for ln in lines:
                if used >= height:
                    break
                out += ln
                out.append(("", "\n"))
                used += 1
            i += 1
        return out

    def _nothing_found(self, width: int) -> StyleAndTextTuples:
        q = self.query_buf.text.strip()
        lines = [
            ("class:empty.head", f"  Nothing matches “{q}”\n"),
            ("class:empty", "\n  Try fewer or shorter words, or a different spelling.\n"),
        ]
        if self.course or self.kind:
            bits = []
            if self.course:
                bits.append(self.store.courses[self.course][0])
            if self.kind:
                bits.append(KIND_NAMES[self.kind])
            lines.append(("class:empty", f"  The search is limited to {' · '.join(bits)}: Ctrl+S / Ctrl+T widen it.\n"))
        return lines

    # ── preview ───────────────────────────────────────────────────────────

    def _preview_for(self, row: Row, width: int) -> Rendered | None:
        theme = self.theme
        if row.kind == "query":
            return None
        item = row.item
        text = ""
        key: tuple
        if row.kind == "alias" and row.alias:
            res = row.resolved
            if row.alias.kind == "text":
                text = f"```\n{row.alias.text}\n```"
                key = ("alias-text", row.alias.name, row.alias.text, width)
            elif res and res.item:
                item = res.item
            else:
                return None
        if item is not None:
            key = ("item", item.id, width)
            if key in self._preview_cache:
                return self._preview_cache[key]
            if item.kind == "snippet":
                text = (f"{item.caption}\n\n" if item.caption else "") + f"```{item.lang}\n{item.body}\n```\n"
                if item.aux:
                    text += f"\n```text\n{item.aux}\n```\n"
            elif item.kind == "term":
                text = item.body.replace("**", "**")
                parent = self.store.get(item.parent) if item.parent else None
                if parent:
                    text += f"\n\n*Defined in {parent.number} {plain_title(parent.title)}.*"
            else:
                text = head(item.body, 3200)
        else:
            key = ("alias-text", row.alias.name if row.alias else "", row.alias.text if row.alias else "", width)  # type: ignore[union-attr]
            if key in self._preview_cache:
                return self._preview_cache[key]
        r = render(text, width, theme, selected=1 if item is not None and item.kind == "snippet" else None)
        if len(self._preview_cache) > 80:
            self._preview_cache.clear()
        self._preview_cache[key] = r
        return r

    def _preview_fragments(self) -> StyleAndTextTuples:
        width = max(20, self.cols - self.list_width - 3)
        height = self.body_height
        row = self.current()
        if row is None:
            return []
        out: StyleAndTextTuples = []
        item = row.item
        if row.kind == "alias" and row.resolved and row.resolved.item:
            item = row.resolved.item
        if row.kind == "query":
            return [("class:empty", f"  Press Enter to search for “{row.text}”.")]
        if row.kind == "alias" and row.alias and row.alias.kind == "text":
            crumb = [("class:crumb.here", f"@{row.alias.name}"), ("class:crumb", "  ·  your note")]
        elif item is not None:
            crumb = self._crumb(item)
        else:
            return [("class:status.warn", "  This alias points at something the current index no longer has.\n"),
                    ("class:empty", "  Search for it again and re-create the alias with Ctrl+A.")]
        out += [("", " ")] + crumb + [("", "\n")]
        title = plain_title(item.title if item and item.kind != "snippet" else (row.alias.name if row.alias and not item else (item.title if item else "")))
        if item is not None and item.kind in ("topic", "guide", "summary", "exercise", "term"):
            out += [("class:overlay.title", " " + title + "\n")]
        else:
            out += [("", "\n")]
        r = self._preview_for(row, width)
        if r is None:
            return out
        room = max(1, height - 3)
        start = min(self.preview_scroll, max(0, len(r.lines) - room))
        self.preview_scroll = start
        for ln in r.lines[start:start + room]:
            out += [("", "  ")] + fragments(ln) + [("", "\n")]
        if start + room < len(r.lines):
            more = len(r.lines) - start - room
            out += [("class:empty", f"  … {more} more lines  ·  Enter to read  ·  PgDn to scroll")]
        return out

    def _crumb(self, item: Item) -> StyleAndTextTuples:
        course = self.store.courses.get(item.course, (item.course, item.course, 0))
        out: StyleAndTextTuples = [(f"fg:{self.color(item.course)} bold", course[1])]
        if item.section:
            sec = f"§{item.section_no} {item.section}" if item.section_no else item.section
            out += [("class:crumb", "  ›  "), ("class:crumb", clip(sec, 40))]
        if item.kind in ("snippet", "term") and item.parent:
            parent = self.store.get(item.parent)
            if parent:
                out += [("class:crumb", "  ›  "), ("class:crumb.here", clip(f"{parent.number} {plain_title(parent.title)}".strip(), 40))]
        elif item.number and not item.number.endswith(".0"):
            out += [("class:crumb", "  ›  "), ("class:crumb.here", item.number)]
        return out

    # ── opening things ────────────────────────────────────────────────────

    def activate(self) -> None:
        row = self.current()
        if row is None:
            return
        if row.kind == "query":
            self.query_buf.text = row.text
            self.query_buf.cursor_position = len(row.text)
            return
        if row.kind == "alias" and row.alias:
            self.open_alias(row.alias)
            return
        if row.item is not None:
            if self.query_buf.text.strip():
                self.recent.searched(self.query_buf.text)
            self.open_item(row.item)

    def open_alias(self, alias: Alias, direct: bool = False) -> bool:
        res = self.aliases.resolve(alias, self.store)
        self.aliases.touch(alias.name)
        if alias.kind == "text":
            self._open_text(alias, direct)
            return True
        if res.item is None:
            self.say(f"@{alias.name}: the target is no longer in the index")
            return False
        self.open_item(res.item, alias=alias, direct=direct)
        if res.moved:
            self.say(f"@{alias.name} was re-found after the courses changed")
        return True

    def _open_text(self, alias: Alias, direct: bool) -> None:
        md = f"```\n{alias.text}\n```"
        rd = Reader(topic=Item(0, f"alias:{alias.name}", "topic", "", None, 0, "", "", f"@{alias.name}", "", 0, "", "", "", md, ""),
                    origin=None, snippets=[], rendered=Rendered(), direct=direct, alias=alias, text=alias.text)  # type: ignore[arg-type]
        self.reader = rd
        self.mode = "reader"
        self._render_reader()
        self.app.layout.focus(self.reader_window)

    def open_item(self, item: Item, alias: Alias | None = None, direct: bool = False) -> None:
        topic = self.store.topic_of(item)
        if topic is None:
            self.say("that entry has no topic to open")
            return
        self.recent.opened_item(item)
        snippets = self.store.snippets_of(topic.id)
        rd = Reader(topic=topic, origin=item, snippets=snippets, rendered=Rendered(), direct=direct, alias=alias)
        self.reader = rd
        self.mode = "reader"
        self.overlay = self.prompt = None
        sel = None
        if item.kind == "snippet" and "#" in item.id:
            sel = int(item.id.rsplit("#", 1)[1])
        rd.sel = sel
        self._render_reader()
        if sel and sel in rd.rendered.spans:
            rd.offset = max(0, rd.rendered.spans[sel][0] - 2)
        elif item.kind == "term":
            self._find(rd, item.title)
        self.app.layout.focus(self.reader_window)
        self.app.invalidate()

    def back(self) -> None:
        rd = self.reader
        if rd and rd.direct:
            self.app.exit()
            return
        self.mode = "search"
        self.overlay = self.prompt = None
        self.reader = None
        self.app.layout.focus(self.query_buf)
        if not self.query_buf.text:
            self._refresh()
        self.app.invalidate()

    # ── reader ────────────────────────────────────────────────────────────

    @property
    def reader_width(self) -> int:
        return max(40, min(self.cols - 6, 108))

    def _render_reader(self) -> None:
        rd = self.reader
        if rd is None:
            return
        key = (rd.topic.id, self.reader_width, rd.sel, rd.text)
        r = self._reader_cache.get(key)
        if r is None:
            r = render(rd.topic.body, self.reader_width, self.theme, selected=rd.sel)
            if len(self._reader_cache) > 12:
                self._reader_cache.clear()
            self._reader_cache[key] = r
        rd.rendered = r
        if rd.find:
            self._find(rd, rd.find, keep=True)

    def _reader_fragments(self) -> StyleAndTextTuples:
        rd = self.reader
        if rd is None:
            return []
        if rd.rendered.width != self.reader_width:
            self._render_reader()
        height = self.reader_window.render_info.window_height if self.reader_window.render_info else max(5, self.lines - 6)
        r = rd.rendered
        rd.offset = max(0, min(rd.offset, max(0, len(r.lines) - height)))
        cur_line = rd.matches[rd.match_i] if rd.matches else -1
        out: StyleAndTextTuples = []
        left = max(2, (self.cols - self.reader_width) // 2)
        for i in range(rd.offset, min(len(r.lines), rd.offset + height)):
            out.append(("", " " * left))
            out += fragments(r.lines[i], rd.find, current=(i == cur_line))
            out.append(("", "\n"))
        return out

    def _find(self, rd: Reader, text: str, keep: bool = False) -> None:
        rd.find = text
        rd.matches = [i for i, ln in enumerate(rd.rendered.plain) if text and text.lower() in ln.lower()]
        if not keep:
            rd.match_i = 0
            start = rd.offset
            for n, line in enumerate(rd.matches):
                if line >= start:
                    rd.match_i = n
                    break
            if rd.matches:
                self._show_line(rd, rd.matches[rd.match_i])
        else:
            rd.match_i = min(rd.match_i, max(0, len(rd.matches) - 1))

    def _show_line(self, rd: Reader, line: int) -> None:
        height = self.reader_window.render_info.window_height if self.reader_window.render_info else 20
        if line < rd.offset or line >= rd.offset + height:
            rd.offset = max(0, line - height // 3)

    def _on_find(self, buf: Buffer) -> None:
        if self.reader and self.prompt == "find":
            self._find(self.reader, buf.text)
            self.app.invalidate()

    def scroll(self, delta: int) -> None:
        rd = self.reader
        if rd:
            rd.offset = max(0, rd.offset + delta)

    def page(self, direction: int, fraction: float = 1.0) -> None:
        h = self.reader_window.render_info.window_height if self.reader_window.render_info else 20
        self.scroll(direction * max(1, int(h * fraction) - 1))

    def goto_snippet(self, step: int) -> None:
        rd = self.reader
        if not rd or not rd.rendered.spans:
            self.say("no code blocks in this topic")
            return
        order = sorted(rd.rendered.spans)
        if rd.sel is None:
            nxt = order[0] if step > 0 else order[-1]
            # start from the first block below the top of the screen
            below = [i for i in order if rd.rendered.spans[i][0] >= rd.offset]
            if step > 0 and below:
                nxt = below[0]
        else:
            pos = order.index(rd.sel) if rd.sel in order else 0
            nxt = order[(pos + step) % len(order)]
        rd.sel = nxt
        self._render_reader()
        start, end = rd.rendered.spans[nxt]
        height = self.reader_window.render_info.window_height if self.reader_window.render_info else 20
        if start < rd.offset or end >= rd.offset + height:
            rd.offset = max(0, start - 2)

    def neighbour(self, step: int) -> None:
        rd = self.reader
        if not rd or rd.text is not None:
            return
        prev, nxt = self.store.neighbours(rd.topic)
        target = nxt if step > 0 else prev
        if target is None:
            self.say("that is the " + ("last" if step > 0 else "first") + " topic of the course")
            return
        direct = rd.direct
        self.open_item(target, direct=direct)

    def toc(self) -> None:
        rd = self.reader
        if not rd or rd.text is not None:
            return
        rows: list[Item | str] = []
        sel = 0
        for no, title in self.store.sections(rd.topic.course):
            rows.append(f"{'§' + str(no) + ' ' if no else ''}{title}")
            for it in self.store.outline(rd.topic.course, no):
                if it.id == rd.topic.id:
                    sel = len(rows)
                rows.append(it)
        self.toc_rows, self.toc_sel, self.overlay = rows, sel, "toc"
        self._toc_top = max(0, sel - 6)

    _toc_top = 0

    def toc_move(self, step: int) -> None:
        i = self.toc_sel
        while 0 <= i + step < len(self.toc_rows):
            i += step
            if isinstance(self.toc_rows[i], Item):
                self.toc_sel = i
                break

    def toc_open(self) -> None:
        row = self.toc_rows[self.toc_sel] if self.toc_rows else None
        self.overlay = None
        if isinstance(row, Item):
            direct = self.reader.direct if self.reader else False
            self.open_item(row, direct=direct)

    def _toc_fragments(self) -> StyleAndTextTuples:
        height = max(6, self.lines - 8)
        if self.toc_sel < self._toc_top + 2:
            self._toc_top = max(0, self.toc_sel - 2)
        elif self.toc_sel >= self._toc_top + height - 2:
            self._toc_top = self.toc_sel - height + 3
        out: StyleAndTextTuples = [("class:overlay.title", f"  Contents · {self.store.courses[self.reader.topic.course][0] if self.reader else ''}\n"), ("", "\n")]
        width = min(80, self.cols - 8)
        for i in range(self._toc_top, min(len(self.toc_rows), self._toc_top + height - 2)):
            row = self.toc_rows[i]
            if isinstance(row, str):
                out.append(("class:section.head", "  " + clip(row, width) + "\n"))
                continue
            sel = i == self.toc_sel
            here = self.reader and row.id == self.reader.topic.id
            style = "class:row.selected" if sel else ""
            label = f"{row.number:<7} {plain_title(row.title)}" if row.number else plain_title(row.title)
            mark = "▌ " if sel else ("● " if here else "  ")
            out.append((("class:row.cursor " if sel else "class:kind.alias " if here else "") + style, "  " + mark))
            out.append((("class:row.title.selected " if sel else "") + style, clip(label, width - 6).ljust(width - 6)))
            out.append(("", "\n"))
        return out

    # ── actions: copy, alias, print ───────────────────────────────────────

    def _copy_text(self) -> tuple[str, str] | None:
        """(text, what) for the thing under the cursor in the current mode."""
        if self.mode == "reader" and self.reader:
            rd = self.reader
            if rd.text is not None:
                return rd.text, "the note"
            if rd.sel and rd.sel <= len(rd.snippets):
                sn = rd.snippets[rd.sel - 1]
                return sn.body, f"snippet {rd.sel}"
            return rd.topic.body, "the topic (markdown)"
        row = self.current()
        if row is None:
            return None
        if row.kind == "alias" and row.alias:
            if row.alias.kind == "text":
                return row.alias.text, "the note"
            row_item = row.resolved.item if row.resolved else None
        else:
            row_item = row.item
        if row_item is None:
            return None
        if row_item.kind == "snippet":
            return row_item.body, "the snippet"
        if row_item.kind == "term":
            return row_item.body.replace("**", ""), "the definition"
        return row_item.body, "the topic (markdown)"

    def copy(self) -> None:
        got = self._copy_text()
        if not got:
            self.say("nothing to copy here")
            return
        text, what = got
        how = clipboard.copy(text)
        n = text.count("\n") + 1
        self.say(f"copied {what} · {n} line{'s' if n != 1 else ''} · {how}" if how else "no clipboard tool found (install pbcopy, wl-copy or xclip)")

    def print_and_quit(self) -> None:
        got = self._copy_text()
        if not got:
            return
        text, what = got
        lang = ""
        rd = self.reader
        if self.mode == "reader" and rd and rd.sel and rd.sel <= len(rd.snippets):
            lang = rd.snippets[rd.sel - 1].lang
        elif self.mode == "search" and (row := self.current()) and row.item and row.item.kind == "snippet":
            lang = row.item.lang
        is_md = what.startswith("the topic") or what == "the definition"
        self.outcome = Outcome(text, markdown=is_md, lang=lang)
        self.app.exit()

    def start_alias(self) -> None:
        target: Item | None = None
        text: str | None = None
        label = ""
        if self.mode == "reader" and self.reader:
            rd = self.reader
            if rd.text is not None:
                self.say("this is already an alias")
                return
            if rd.sel and rd.sel <= len(rd.snippets):
                target = rd.snippets[rd.sel - 1]
                label = f"snippet {rd.sel} of {plain_title(rd.topic.title)}"
            else:
                target = rd.topic
                label = plain_title(rd.topic.title)
        else:
            row = self.current()
            if row is None or row.kind == "query":
                return
            if row.kind == "alias":
                self.say("it is already an alias — Ctrl+X removes it")
                return
            target = row.item
            label = plain_title(target.title) if target else ""
        if target is None:
            return
        self.alias_target, self.alias_text, self.alias_label = target, text, label
        self.alias_buf.reset(Document(self._suggest_name(target)))
        self.alias_buf.cursor_position = len(self.alias_buf.text)
        self.prompt, self.confirm = "alias", None
        self.app.layout.focus(self.alias_buf)

    alias_label = ""

    def _suggest_name(self, item: Item) -> str:
        base = item.title if item.kind != "snippet" else (item.title.split()[0:2] and " ".join(item.title.split()[:2]))
        words = re.findall(r"[A-Za-z0-9]+", plain_title(base or item.title).lower())
        name = "-".join(words[:2])[:24].strip("-")
        if name in self.aliases.items or not name:
            return ""
        return name

    def submit_alias(self) -> None:
        name = self.alias_buf.text.strip().lstrip("@")
        item = self.alias_target
        if not name or item is None:
            return
        try:
            name = self.aliases.check_name(name, self.store)
        except AliasError as e:
            self.say(str(e))
            return
        if name in self.aliases.items and self.confirm != name:
            old = self.aliases.items[name].summary
            self.confirm = name
            self.say(f"@{name} already points at “{clip(old, 40)}” — Enter again to replace it")
            return
        a, replaced = self.aliases.add_ref(name, item, store=self.store)
        self.cancel_prompt()
        self.say(f"@{name} {'updated' if replaced else 'saved'}  ·  recall it with: lore @{name}")
        if self.mode == "search" and not self.query_buf.text:
            self._refresh()

    def delete_alias(self) -> None:
        row = self.current()
        if row is None or row.kind != "alias" or not row.alias:
            return
        name = row.alias.name
        if self.confirm != f"del:{name}":
            self.confirm = f"del:{name}"
            self.say(f"Ctrl+X again to delete @{name}")
            return
        self.aliases.remove(name)
        self.confirm = None
        self._refresh()
        self.say(f"@{name} deleted")

    def start_find(self) -> None:
        if not self.reader:
            return
        self.find_buf.reset(Document(self.reader.find))
        self.find_buf.cursor_position = len(self.find_buf.text)
        self.prompt = "find"
        self.app.layout.focus(self.find_buf)

    def cancel_prompt(self) -> None:
        self.prompt = None
        self.confirm = None
        target = self.reader_window if self.mode == "reader" else self.query_buf
        self.app.layout.focus(target)

    def end_find(self, keep: bool) -> None:
        if self.reader and not keep:
            self.reader.find, self.reader.matches = "", []
        self.cancel_prompt()

    def find_step(self, step: int) -> None:
        rd = self.reader
        if not rd or not rd.matches:
            self.say("no matches" if rd and rd.find else "press / to search this page")
            return
        rd.match_i = (rd.match_i + step) % len(rd.matches)
        self._show_line(rd, rd.matches[rd.match_i])

    # ── chrome ────────────────────────────────────────────────────────────

    def _header(self) -> StyleAndTextTuples:
        c = self.store.counts
        if self.banner_on:
            return []
        out: StyleAndTextTuples = [("class:brand", "  ✦ lore"), ("class:brand.dim", f"  v{__version__}")]
        if self.mode == "search" and self.cols >= 100:
            out += [("class:brand.dim", f"  ·  {c.get('topics', 0):,} topics  ·  {c.get('snippets', 0):,} snippets  ·  offline")]
        return out

    def _banner(self) -> StyleAndTextTuples:
        c = self.store.counts
        out: StyleAndTextTuples = [("", "\n")]
        for row in pixel_rows("LORE:"):
            out += [("class:wordmark", "  " + row + "\n")]
        out += [("", "\n"), ("class:brand.dim", f"  v{__version__}  ·  offline docs from {len(self.store.courses)} courses\n")]
        n = len(self.aliases.items)
        facts = f"  {c.get('topics', 0):,} topics  ·  {c.get('snippets', 0):,} snippets  ·  {c.get('terms', 0):,} terms  ·  {n} alias{'es' if n != 1 else ''}"
        out += [("class:keybar.label", facts + "\n"), ("", "\n")]
        return out

    def _scope(self) -> StyleAndTextTuples:
        q = self.result.query if self.result else None
        course = (q.course if q and q.course else self.course)
        kind = (q.kind if q and q.kind else self.kind)
        out: StyleAndTextTuples = []
        out.append(("class:chip.on" if course else "class:chip", f" {self.store.courses[course][1] if course else 'all courses'} "))
        out.append(("", " "))
        out.append(("class:chip.on" if kind else "class:chip", f" {KIND_NAMES[kind]} "))
        return out

    def _counter(self) -> StyleAndTextTuples:
        if self.mode != "search" or not self.query_buf.text.strip() or self.result is None:
            return [("", "")]
        n = len(self.result.hits)
        extra = ""
        if self.result.corrected:
            extra = f"  showing “{self.result.corrected}”"
        elif self.result.loose:
            extra = "  partial matches"
        return [("class:counter", f"{extra}  {n} result{'s' if n != 1 else ''} · {self.elapsed:.0f} ms ")]

    def _prompt_prefix(self, line_number: int, wrap_count: int) -> StyleAndTextTuples:
        if self.prompt == "alias":
            return [("class:prompt.alias", "@ ")]
        if self.prompt == "find":
            return [("class:prompt.find", "/ ")]
        return [("class:prompt", "❯ ")]

    def _keybar_items(self) -> list[tuple[str, str]]:
        if self.overlay == "toc":
            return [("MOVE", "↑↓"), ("OPEN", "Enter"), ("CLOSE", "Esc")]
        if self.overlay == "help":
            return [("CLOSE", "Esc")]
        if self.prompt == "alias":
            return [("SAVE", "Enter"), ("CANCEL", "Esc")]
        if self.prompt == "find":
            return [("FIND", "Enter"), ("CANCEL", "Esc")]
        if self.mode == "reader":
            rd = self.reader
            items = [("SCROLL", "j/k"), ("NEXT", "n"), ("PREV", "p"), ("CODE", "Tab"), ("COPY", "y"), ("ALIAS", "a"),
                     ("FIND", "/"), ("CONTENTS", "t"), ("PRINT", "P"), ("BACK", "q")]
            if rd and rd.text is not None:
                items = [("COPY", "y"), ("PRINT", "P"), ("BACK", "q")]
            if rd and rd.matches:
                items.insert(0, ("MATCH", "] ["))
            return items
        row = self.current()
        if row is not None and row.kind == "alias":
            return [("OPEN", "Enter"), ("COPY", "Ctrl+Y"), ("DELETE", "Ctrl+X"), ("SEARCH", "type"), ("EXIT", "Esc")]
        if not self.query_buf.text:
            return [("OPEN", "Enter"), ("SEARCH", "type"), ("HELP", "?"), ("EXIT", "Esc")]
        return [("OPEN", "Enter"), ("NEXT", "Tab"), ("ALIAS", "Ctrl+A"), ("COPY", "Ctrl+Y"), ("KIND", "Ctrl+T"),
                ("COURSE", "Ctrl+S"), ("HELP", "F1"), ("EXIT", "Esc")]

    def _keybar(self) -> StyleAndTextTuples:
        width = self.cols - 4
        items = self._keybar_items()

        def render_items(entries) -> StyleAndTextTuples:
            out: StyleAndTextTuples = [("", "  ")]
            for i, (label, key) in enumerate(entries):
                if i:
                    out.append(("class:keybar.sep", "  |  "))
                out += [("class:keybar.label", label), ("class:keybar.key", f": {key}")]
            return out

        def w(f):
            return sum(get_cwidth(t) for _s, t in f)

        while len(items) > 2 and w(render_items(items)) > width + 2:
            items.pop(-2)  # keep the last one (EXIT / BACK) and drop the least important before it
        return render_items(items)

    def _modeline(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = [("", "  ")]
        if self.flash and time.monotonic() < self.flash[1]:
            return out + [("class:flash", self.flash[0])]
        sep = ("class:status.sep", "  ·  ")
        if self.mode == "reader" and self.reader:
            rd = self.reader
            r = rd.rendered
            h = self.reader_window.render_info.window_height if self.reader_window.render_info else 20
            pct = 100 if len(r.lines) <= h else min(100, int((rd.offset + h) * 100 / max(1, len(r.lines))))
            out += [("class:status", f"{pct}%"), sep]
            if rd.text is None:
                prev, nxt = self.store.neighbours(rd.topic)
                outline = self.store.outline(rd.topic.course, rd.topic.section_no)
                ids = [o.id for o in outline]
                if rd.topic.id in ids:
                    out += [("class:status", f"{ids.index(rd.topic.id) + 1}/{len(ids)} in the section"), sep]
                nsn = len(rd.snippets)
                if nsn:
                    out += [("class:status", f"{nsn} code block{'s' if nsn != 1 else ''}")]
                    if rd.sel:
                        out += [("class:status.accent", f" (#{rd.sel} selected)")]
                    out += [sep]
            if rd.find:
                out += [("class:status.accent", f"/{rd.find}"), ("class:status", f" {rd.match_i + 1 if rd.matches else 0}/{len(rd.matches)}"), sep]
        else:
            out += [("class:status", f"{self.settings.theme}")]
            out += [sep, ("class:status", "scope " + (self.store.courses[self.course][0] if self.course else "all courses"))]
        if self.stale:
            out += [sep, ("class:status.warn", "courses changed — run: lore index")]
        while out and out[-1] is sep:
            out.pop()
        return out

    # ── layout ────────────────────────────────────────────────────────────

    def _rule(self) -> Window:
        return Window(char="─", height=1, style="class:rule")

    def _make_input(self, buf: Buffer) -> Window:
        return Window(
            BufferControl(buffer=buf, input_processors=[Placeholder(self._placeholder)]),
            height=1, get_line_prefix=self._prompt_prefix, dont_extend_height=True,
        )

    def _input(self) -> Window:
        return {"alias": self.alias_win, "find": self.find_win}.get(self.prompt or "", self.query_win)

    def _placeholder(self) -> str:
        if self.prompt == "alias":
            return f"name for “{clip(self.alias_label, 50)}”   (letters, digits, - _ .)"
        if self.prompt == "find":
            return "find in this page"
        return "Search the courses…  try: git rebase --onto · kind:term closure · in:sql window functions · @alias"

    def _search_body(self) -> VSplit | Window:
        if not self.show_preview:
            return self.list_window
        return VSplit([self.list_window, Window(char="│", width=1, style="class:divider"), self.preview_window])

    def _body(self):
        if self.overlay == "toc":
            return self.toc_window
        if self.mode == "reader":
            return HSplit([self._reader_header(), self.reader_window])
        return self._search_body()

    def _reader_header(self) -> Window:
        return Window(FormattedTextControl(self._reader_crumb), height=2, dont_extend_height=True)

    def _reader_crumb(self) -> StyleAndTextTuples:
        rd = self.reader
        if rd is None:
            return []
        if rd.text is not None:
            return [("class:crumb.here", f"  @{rd.alias.name if rd.alias else ''}"), ("class:crumb", "  ·  your note\n"), ("", "\n")]
        out = [("", " ")] + self._crumb(rd.topic)
        if rd.alias:
            out += [("class:kind.alias", f"   ★ @{rd.alias.name}")]
        out += [("", "\n"), ("class:overlay.title", "  " + plain_title(rd.topic.title) + "\n")]
        return out

    def _help(self) -> StyleAndTextTuples:
        def sect(title: str, rows: list[tuple[str, str]]) -> StyleAndTextTuples:
            out: StyleAndTextTuples = [("class:overlay.title", f"  {title}\n")]
            for key, desc in rows:
                out += [("class:overlay.key", f"    {key:<16}"), ("class:overlay.desc", desc + "\n")]
            return out + [("", "\n")]

        out: StyleAndTextTuples = [("", "\n")]
        out += sect("Searching", [
            ("type", "words, a command, an identifier — results update as you type"),
            ("↑ ↓  Tab", "move through the suggestions  (Shift+Tab goes back)"),
            ("Enter", "open the selected result in the reader"),
            ("in:git  @git", "limit to a course (also: Ctrl+S cycles them)"),
            ("kind:term", "topic · snippet · term  (also: Ctrl+T cycles)"),
            ("lang:bash", "only code snippets in one language"),
            ("PgUp PgDn", "scroll the preview"),
            ("Ctrl+O", "print the selection to the terminal and quit (works in a pipe: lore | pbcopy)"),
        ])
        out += sect("Aliases", [
            ("Ctrl+A", "save the selected result under a name you choose"),
            ("@name", "type an alias name to find it; from the shell: lore @name"),
            ("Ctrl+X", "delete the selected alias (press twice)"),
            ("Ctrl+Y", "copy the selected snippet, definition or topic"),
        ])
        out += sect("Reading", [
            ("j k  ↑ ↓", "scroll a line      Space  b   a page      g G   top, bottom"),
            ("n  p", "next / previous topic in the course"),
            ("Tab", "select the next code block   y copies it, a aliases it"),
            ("/  ] [", "find in the page, next / previous match"),
            ("t", "contents of the whole course"),
            ("P", "print the selection to the terminal and quit"),
            ("q  Esc", "back to the search"),
        ])
        out += [("class:overlay.desc", "  Esc closes this panel.\n")]
        return out

    def _build_app(self) -> Application:
        banner_on = Condition(lambda: self.banner_on)
        banner = ConditionalContainer(Window(FormattedTextControl(self._banner), height=10, dont_extend_height=True), filter=banner_on)
        header = Window(FormattedTextControl(self._header), height=1)
        scope = Window(FormattedTextControl(self._scope_or_blank), height=1, dont_extend_width=True)
        top = ConditionalContainer(VSplit([header, scope, Window(width=2)], height=1), filter=~banner_on)
        input_visible = Condition(lambda: (self.mode == "search" and self.overlay is None) or self.prompt is not None)
        input_row = ConditionalContainer(
            VSplit([DynamicContainer(self._input), Window(FormattedTextControl(self._counter), dont_extend_width=True)], height=1),
            filter=input_visible,
        )
        keybar = Window(FormattedTextControl(self._keybar), height=1)
        modeline = Window(FormattedTextControl(self._modeline), height=1)
        main = HSplit([
            banner,
            top,
            self._rule(),
            input_row,
            ConditionalContainer(self._rule(), filter=input_visible),
            DynamicContainer(self._body),
            Window(height=1),
            keybar,
            modeline,
        ])
        help_box = ConditionalContainer(
            Window(FormattedTextControl(self._help), style="class:overlay", width=82, height=Dimension(min=10)),
            filter=Condition(lambda: self.overlay == "help"),
        )
        root = FloatContainer(content=main, floats=[Float(content=help_box)])
        app = Application(
            layout=Layout(root, focused_element=self.query_buf),
            key_bindings=self._bindings(),
            style=DynamicStyle(lambda: self.theme.pt_style),
            include_default_pygments_style=False,
            full_screen=True,
            mouse_support=True,
            output=self._output,
            editing_mode=EditingMode.VI if self.settings.editing_mode == "vi" else EditingMode.EMACS,
        )
        app.ttimeoutlen = 0.05
        app.timeoutlen = 0.4
        self.list_window.content.mouse_handler = self._list_mouse  # type: ignore[assignment]
        self.preview_window.content.mouse_handler = self._preview_mouse  # type: ignore[assignment]
        self.reader_window.content.mouse_handler = self._reader_mouse  # type: ignore[assignment]
        return app

    def _scope_or_blank(self) -> StyleAndTextTuples:
        return self._scope() if self.mode == "search" and not self.overlay else []

    # ── mouse ─────────────────────────────────────────────────────────────

    def _list_mouse(self, ev: MouseEvent):
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            self.move(1)
        elif ev.event_type == MouseEventType.SCROLL_UP:
            self.move(-1)
        elif ev.event_type == MouseEventType.MOUSE_UP:
            # rows are two lines tall; headers also take two (a blank line precedes all but the first)
            y, i, used = ev.position.y, self.top, 0
            while i < len(self.rows):
                size = 2 + (1 if self.rows[i].kind == "header" and i != self.top else 0)
                if y < used + size:
                    if self.rows[i].selectable:
                        if i == self.sel:
                            self.activate()
                        else:
                            self.sel = i
                            self.preview_scroll = 0
                    break
                used += size
                i += 1
        else:
            return NotImplemented
        return None

    def _preview_mouse(self, ev: MouseEvent):
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            self.preview_scroll += 3
        elif ev.event_type == MouseEventType.SCROLL_UP:
            self.preview_scroll = max(0, self.preview_scroll - 3)
        else:
            return NotImplemented
        return None

    def _reader_mouse(self, ev: MouseEvent):
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            self.scroll(3)
        elif ev.event_type == MouseEventType.SCROLL_UP:
            self.scroll(-3)
        else:
            return NotImplemented
        return None

    # ── key bindings ──────────────────────────────────────────────────────

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()
        search = Condition(lambda: self.mode == "search" and self.overlay is None and self.prompt is None)
        reading = Condition(lambda: self.mode == "reader" and self.overlay is None and self.prompt is None)
        toc = Condition(lambda: self.overlay == "toc")
        helping = Condition(lambda: self.overlay == "help")
        alias_p = Condition(lambda: self.prompt == "alias")
        find_p = Condition(lambda: self.prompt == "find")
        empty_q = Condition(lambda: not self.query_buf.text)

        @kb.add("c-c")
        @kb.add("c-d", filter=search | reading)
        def _quit(event: KeyPressEvent) -> None:
            event.app.exit()

        # help overlay
        @kb.add("f1", filter=~helping)
        @kb.add("?", filter=(search & empty_q) | reading)
        def _help_on(event: KeyPressEvent) -> None:
            self.overlay = "help"

        @kb.add("escape", filter=helping, eager=True)
        @kb.add("q", filter=helping)
        @kb.add("enter", filter=helping)
        def _help_off(event: KeyPressEvent) -> None:
            self.overlay = None

        # search mode
        @kb.add("enter", filter=search)
        def _open(event: KeyPressEvent) -> None:
            self.activate()

        @kb.add("down", filter=search)
        @kb.add("c-n", filter=search)
        @kb.add("tab", filter=search)
        def _down(event: KeyPressEvent) -> None:
            self.move(1)

        @kb.add("up", filter=search)
        @kb.add("c-p", filter=search)
        @kb.add("s-tab", filter=search)
        def _up(event: KeyPressEvent) -> None:
            self.move(-1)

        @kb.add("pagedown", filter=search)
        def _pdown(event: KeyPressEvent) -> None:
            self.preview_scroll += max(3, self.body_height - 4)

        @kb.add("pageup", filter=search)
        def _pup(event: KeyPressEvent) -> None:
            self.preview_scroll = max(0, self.preview_scroll - max(3, self.body_height - 4))

        @kb.add("c-a", filter=search)
        def _alias(event: KeyPressEvent) -> None:
            self.start_alias()

        @kb.add("c-y", filter=search)
        def _copy(event: KeyPressEvent) -> None:
            self.copy()

        @kb.add("c-t", filter=search)
        def _kind(event: KeyPressEvent) -> None:
            self.cycle_kind()

        @kb.add("c-s", filter=search)
        def _course(event: KeyPressEvent) -> None:
            self.cycle_course()

        @kb.add("c-x", filter=search)
        def _delete(event: KeyPressEvent) -> None:
            self.delete_alias()

        @kb.add("c-o", filter=search)
        def _print(event: KeyPressEvent) -> None:
            self.print_and_quit()

        @kb.add("escape", filter=search, eager=True)
        def _esc(event: KeyPressEvent) -> None:
            if self.query_buf.text:
                self.query_buf.text = ""
            elif self.course or self.kind:
                self.course = self.kind = None
                self._refresh()
            else:
                event.app.exit()

        @kb.add("c-u", filter=search)
        def _clear(event: KeyPressEvent) -> None:
            self.query_buf.text = ""

        # alias / find prompts
        @kb.add("enter", filter=alias_p)
        def _alias_ok(event: KeyPressEvent) -> None:
            self.submit_alias()

        @kb.add("escape", filter=alias_p, eager=True)
        def _alias_cancel(event: KeyPressEvent) -> None:
            self.cancel_prompt()

        @kb.add("enter", filter=find_p)
        def _find_ok(event: KeyPressEvent) -> None:
            self.end_find(keep=bool(self.find_buf.text))

        @kb.add("escape", filter=find_p, eager=True)
        def _find_cancel(event: KeyPressEvent) -> None:
            self.end_find(keep=False)

        # reader
        @kb.add("j", filter=reading)
        @kb.add("down", filter=reading)
        @kb.add("c-n", filter=reading)
        @kb.add("enter", filter=reading)
        def _line_down(event: KeyPressEvent) -> None:
            self.scroll(1)

        @kb.add("k", filter=reading)
        @kb.add("up", filter=reading)
        @kb.add("c-p", filter=reading)
        def _line_up(event: KeyPressEvent) -> None:
            self.scroll(-1)

        @kb.add("space", filter=reading)
        @kb.add("pagedown", filter=reading)
        @kb.add("c-f", filter=reading)
        def _page_down(event: KeyPressEvent) -> None:
            self.page(1)

        @kb.add("b", filter=reading)
        @kb.add("pageup", filter=reading)
        @kb.add("c-b", filter=reading)
        def _page_up(event: KeyPressEvent) -> None:
            self.page(-1)

        @kb.add("d", filter=reading)
        def _half_down(event: KeyPressEvent) -> None:
            self.page(1, 0.5)

        @kb.add("u", filter=reading)
        def _half_up(event: KeyPressEvent) -> None:
            self.page(-1, 0.5)

        @kb.add("g", filter=reading)
        @kb.add("home", filter=reading)
        def _top(event: KeyPressEvent) -> None:
            if self.reader:
                self.reader.offset = 0

        @kb.add("G", filter=reading)
        @kb.add("end", filter=reading)
        def _bottom(event: KeyPressEvent) -> None:
            if self.reader:
                self.reader.offset = 10**9

        @kb.add("n", filter=reading)
        def _next_topic(event: KeyPressEvent) -> None:
            self.neighbour(1)

        @kb.add("p", filter=reading)
        def _prev_topic(event: KeyPressEvent) -> None:
            self.neighbour(-1)

        @kb.add("tab", filter=reading)
        def _next_block(event: KeyPressEvent) -> None:
            self.goto_snippet(1)

        @kb.add("s-tab", filter=reading)
        def _prev_block(event: KeyPressEvent) -> None:
            self.goto_snippet(-1)

        @kb.add("y", filter=reading)
        @kb.add("c-y", filter=reading)
        def _r_copy(event: KeyPressEvent) -> None:
            self.copy()

        @kb.add("a", filter=reading)
        @kb.add("c-a", filter=reading)
        def _r_alias(event: KeyPressEvent) -> None:
            self.start_alias()

        @kb.add("P", filter=reading)
        def _r_print(event: KeyPressEvent) -> None:
            self.print_and_quit()

        @kb.add("/", filter=reading)
        def _r_find(event: KeyPressEvent) -> None:
            self.start_find()

        @kb.add("]", filter=reading)
        def _r_next_match(event: KeyPressEvent) -> None:
            self.find_step(1)

        @kb.add("[", filter=reading)
        def _r_prev_match(event: KeyPressEvent) -> None:
            self.find_step(-1)

        @kb.add("t", filter=reading)
        def _r_toc(event: KeyPressEvent) -> None:
            self.toc()

        @kb.add("escape", filter=reading, eager=True)
        @kb.add("q", filter=reading)
        @kb.add("backspace", filter=reading)
        @kb.add("h", filter=reading)
        def _r_back(event: KeyPressEvent) -> None:
            rd = self.reader
            if rd and rd.find and event.key_sequence[0].key == "escape":
                rd.find, rd.matches = "", []
                return
            self.back()

        # contents overlay
        @kb.add("down", filter=toc)
        @kb.add("j", filter=toc)
        @kb.add("c-n", filter=toc)
        def _toc_down(event: KeyPressEvent) -> None:
            self.toc_move(1)

        @kb.add("up", filter=toc)
        @kb.add("k", filter=toc)
        @kb.add("c-p", filter=toc)
        def _toc_up(event: KeyPressEvent) -> None:
            self.toc_move(-1)

        @kb.add("pagedown", filter=toc)
        def _toc_pd(event: KeyPressEvent) -> None:
            for _ in range(10):
                self.toc_move(1)

        @kb.add("pageup", filter=toc)
        def _toc_pu(event: KeyPressEvent) -> None:
            for _ in range(10):
                self.toc_move(-1)

        @kb.add("enter", filter=toc)
        def _toc_go(event: KeyPressEvent) -> None:
            self.toc_open()

        @kb.add("escape", filter=toc, eager=True)
        @kb.add("q", filter=toc)
        @kb.add("t", filter=toc)
        def _toc_close(event: KeyPressEvent) -> None:
            self.overlay = None

        return kb

    # ── run ───────────────────────────────────────────────────────────────

    def run(self, open_alias: str | None = None, open_item: Item | None = None) -> Outcome | None:
        def pre_run() -> None:
            if open_alias:
                a = self.aliases.get(open_alias)
                if a:
                    self.open_alias(a, direct=True)
            elif open_item is not None:
                self.open_item(open_item, direct=True)
            elif self.mode == "search":
                self.app.layout.focus(self.query_buf)
                if self.query_buf.text:
                    self.query_buf.cursor_position = len(self.query_buf.text)

        self.app.run(pre_run=pre_run)
        if self.query_buf.text.strip() and self.result and self.result.hits:
            self.recent.searched(self.query_buf.text)
        return self.outcome
