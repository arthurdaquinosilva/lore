"""Turn the courses' markdown-with-HTML into plain markdown that a terminal can show.

The course sources mix markdown with raw HTML: coloured callout grids, flex strips, inline SVG figures
and `<details>` solutions. None of that survives in a terminal, so each construct is mapped to the
nearest markdown shape and nothing is lost except the pictures:

* a callout grid becomes a bullet list (`- **label** — description`);
* a figure becomes a one-line `Figure:` note built from its caption;
* a `<details>` block becomes a `:::details <summary>` … `:::` region the renderer draws as a rail.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+#.-]*)")
BLOCK_START = re.compile(r"^\s*<(div|figure|table|svg|ul|ol|p|form|section|script|style|blockquote|iframe|dl|aside)\b", re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
DETAILS_OPEN = re.compile(r"^\s*<details\b[^>]*>\s*(?:<summary>(.*?)</summary>)?\s*$", re.I)
SUMMARY_LINE = re.compile(r"^\s*<summary>(.*?)</summary>\s*$", re.I)
DETAILS_CLOSE = re.compile(r"^\s*</details>\s*$", re.I)
ATTR_LIST = re.compile(r"\s*\{[#.:][^}]*\}\s*$")

BLOCK_TAGS = {"div", "p", "ul", "ol", "li", "table", "figure", "form", "section", "blockquote", "dl", "pre",
              "h1", "h2", "h3", "h4", "h5", "h6", "details", "aside", "svg"}
DROP_TAGS = {"script", "style", "svg", "button", "input", "select", "textarea", "iframe", "form", "canvas", "noscript"}
VOID = {"br", "img", "hr", "input", "meta", "link", "col", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.kids: list[Node | str] = []
        self.parent = parent

    @property
    def style(self) -> str:
        return self.attrs.get("style", "").replace(" ", "").lower()


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v or "" for k, v in attrs}, self.cur)
        self.cur.kids.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, {k: v or "" for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent  # type: ignore[assignment]
        if node is not self.root:
            self.cur = node.parent  # type: ignore[assignment]

    def handle_data(self, data):
        self.cur.kids.append(data)


def parse(html: str) -> Node:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.root


# ── inline conversion ───────────────────────────────────────────────────────

def _text(node: Node | str) -> str:
    """Inline markdown for a node and its descendants."""
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node)
    tag = node.tag
    if tag in DROP_TAGS or tag == "title" or tag == "desc":
        return ""
    inner = "".join(_text(k) for k in node.kids)
    if tag in ("code", "kbd", "tt", "samp"):
        s = inner.strip()
        return f"`{s}`" if s else ""
    if tag in ("strong", "b"):
        s = inner.strip()
        return f"**{s}**" if s else ""
    if tag in ("em", "i", "cite"):
        s = inner.strip()
        return f"*{s}*" if s else ""
    if tag == "sup":
        return f"^{inner.strip()}"
    if tag == "sub":
        return f"_{inner.strip()}"
    if tag == "br":
        return "\n"
    if tag == "img":
        alt = node.attrs.get("alt", "").strip()
        return f"*[image: {alt}]*" if alt else ""
    if tag == "a":
        return inner
    if tag in ("li",):
        return inner
    return inner


def _is_block(node: Node | str) -> bool:
    return isinstance(node, Node) and node.tag in BLOCK_TAGS


def _inline_lines(node: Node) -> list[str]:
    """Lines of inline text of a node whose children are not blocks."""
    text = "".join(_text(k) for k in node.kids)
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def _cells(node: Node) -> list[Node]:
    return [k for k in node.kids if isinstance(k, Node) and k.tag not in DROP_TAGS]


def _has_block_child(node: Node) -> bool:
    return any(_is_block(k) for k in node.kids)


def _columns(node: Node) -> list[str]:
    m = re.search(r"grid-template-columns:\s*([^;]+)", node.attrs.get("style", "").lower())
    return re.sub(r"\s*,\s*", ",", m.group(1)).split() if m else []


def _flat(node: Node) -> str:
    """One line of text for a node, block children joined by spaces."""
    parts: list[str] = []
    for k in node.kids:
        if isinstance(k, str):
            parts.append(_text(k))
        elif k.tag in DROP_TAGS:
            continue
        elif _is_block(k):
            parts.append(" " + _flat(k) + " ")
        else:
            parts.append(_text(k))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _render(node: Node, out: list[str], list_prefix: str = "") -> None:
    tag = node.tag
    if tag in DROP_TAGS:
        return
    if tag == "figure":
        cap = next((k for k in node.kids if isinstance(k, Node) and k.tag == "figcaption"), None)
        caption = _flat(cap) if cap else ""
        if not caption:
            title = _find(node, "title")
            caption = _flat(title) if title else ""
        if caption:
            out += ["", f"> *Figure — {caption}*", ""]
        return
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        out += ["", "#" * int(tag[1]) + " " + _flat(node), ""]
        return
    if tag == "table":
        _render_table(node, out)
        return
    if tag in ("ul", "ol"):
        n = 0
        for li in _cells(node):
            if li.tag != "li":
                continue
            n += 1
            mark = f"{n}." if tag == "ol" else "-"
            out.append(f"{list_prefix}{mark} {_flat(li)}")
        out.append("")
        return
    if tag == "p" or (tag == "blockquote" and not _has_block_child(node)):
        lines = _inline_lines(node)
        if lines:
            quote = "> " if tag == "blockquote" else ""
            out += [quote + " ".join(lines), ""]
        return
    if tag in ("div", "section", "aside", "dl", "blockquote", "root", "li", "details"):
        _render_container(node, out)
        return
    # inline element at block level
    line = _flat(node)
    if line:
        out += [line, ""]


def _find(node: Node, tag: str) -> Node | None:
    for k in node.kids:
        if isinstance(k, Node):
            if k.tag == tag:
                return k
            hit = _find(k, tag)
            if hit:
                return hit
    return None


def _bold_first(node: Node) -> bool:
    st = node.style
    if "font-weight:6" in st or "font-weight:7" in st or "font-weight:bold" in st:
        return True
    return any(isinstance(k, Node) and k.tag in ("strong", "b") for k in node.kids[:1])


def _card(node: Node) -> tuple[str, str] | None:
    """A title line over one or two description lines: `<div bold>Title</div><div>text</div>`."""
    kids = [k for k in node.kids if isinstance(k, Node) and k.tag not in DROP_TAGS]
    if not 2 <= len(kids) <= 3 or any(_has_block_child(k) or k.tag not in ("div", "p", "span") for k in kids):
        return None
    if not _bold_first(kids[0]):
        return None
    title = _flat(kids[0]).strip(" *")
    desc = " ".join(_flat(k) for k in kids[1:]).strip()
    return (title, desc) if title and desc else None


def _render_container(node: Node, out: list[str]) -> None:
    style = node.style
    kids = [k for k in node.kids if not (isinstance(k, str) and not k.strip())]
    if not any(_is_block(k) for k in kids):
        lines = _inline_lines(node)
        if lines:
            out += [" ".join(lines), ""]
        return
    cols = _columns(node)
    cells = [k for k in kids if isinstance(k, Node) and k.tag not in DROP_TAGS]
    card = _card(node)
    if card:
        out.append(f"- **{card[0]}** — {card[1]}")
        return
    if "display:grid" in style and cols and len(cells) >= 2:
        first = cols[0]
        pairs = len(cols) == 2 and not first.endswith("fr") and not first.startswith(("repeat", "minmax", "auto"))
        if pairs:
            for i in range(0, len(cells), 2):
                label = _flat(cells[i])
                desc = _flat(cells[i + 1]) if i + 1 < len(cells) else ""
                bold = label if label.startswith("**") else f"**{label}**"
                out.append(f"- {bold} — {desc}" if desc else f"- {bold}")
            out.append("")
            return
        for c in cells:
            cd = _card(c)
            text = f"**{cd[0]}** — {cd[1]}" if cd else _flat(c)
            if text:
                out.append(f"- {text}")
        out.append("")
        return
    if "display:flex" in style and "flex-direction:column" not in style:
        items = [_flat(c) for c in cells]
        items = [i for i in items if i]
        if len(items) > 1 and all(len(i) < 60 for i in items) and not any(_card(c) for c in cells):
            out += [" | ".join(items), ""]
            return
    for c in cells:
        _render(c, out)
    if out and out[-1] != "":
        out.append("")


def _render_table(node: Node, out: list[str]) -> None:
    rows: list[list[str]] = []
    header = False

    def walk(n: Node) -> None:
        nonlocal header
        for k in n.kids:
            if not isinstance(k, Node):
                continue
            if k.tag == "tr":
                cells = [c for c in k.kids if isinstance(c, Node) and c.tag in ("td", "th")]
                if any(c.tag == "th" for c in cells) and not rows:
                    header = True
                rows.append([_flat(c).replace("|", "\\|") for c in cells])
            else:
                walk(k)

    walk(node)
    rows = [r for r in rows if r]
    if not rows:
        return
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, body = (rows[0], rows[1:]) if header or len(rows) > 1 else ([""] * width, rows)
    out.append("| " + " | ".join(head) + " |")
    out.append("|" + "|".join(" --- " for _ in head) + "|")
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    out.append("")


def html_block_to_md(html: str) -> str:
    root = parse(html)
    out: list[str] = []
    _render(root, out)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


# ── inline HTML inside prose lines ──────────────────────────────────────────

_SPAN = re.compile(r"(`+)(.+?)\1")
_INLINE_TAGS = re.compile(r"</?(?:code|kbd|tt|samp|b|strong|i|em|sup|sub|span|br|a|small|mark|u|abbr|cite|var)\b[^>]*>", re.I)


def inline_html(line: str) -> str:
    """Rewrite the handful of inline tags used in prose, leaving backtick code spans untouched."""
    if "<" not in line:
        return line
    pieces: list[str] = []
    pos = 0
    for m in _SPAN.finditer(line):
        pieces.append(_inline_chunk(line[pos:m.start()]))
        pieces.append(m.group(0))
        pos = m.end()
    pieces.append(_inline_chunk(line[pos:]))
    return "".join(pieces)


def _inline_chunk(chunk: str) -> str:
    if "<" not in chunk:
        return chunk
    if not _INLINE_TAGS.search(chunk):
        return chunk
    root = parse(chunk)
    return "".join(_text(k) for k in root.kids).replace("\n", " ").strip() if chunk.strip() else chunk


# ── whole documents ─────────────────────────────────────────────────────────

def clean(md: str) -> str:
    """Clean a block of course markdown. Code fences are copied through untouched."""
    md = _strip_comments(md)
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    fence: tuple[str, int] | None = None
    while i < len(lines):
        line = lines[i]
        fm = FENCE.match(line)
        if fence:
            out.append(line)
            if fm and fm.group(2)[0] == fence[0] and len(fm.group(2)) >= fence[1] and not fm.group(3):
                fence = None
            i += 1
            continue
        if fm:
            fence = (fm.group(2)[0], len(fm.group(2)))
            out.append(line)
            i += 1
            continue
        m = DETAILS_OPEN.match(line)
        if m:
            summary = m.group(1)
            if summary is None and i + 1 < len(lines):
                sm = SUMMARY_LINE.match(lines[i + 1])
                if sm:
                    summary = sm.group(1)
                    i += 1
            out += ["", f":::details {inline_html(summary or 'Details').strip()}", ""]
            i += 1
            continue
        if DETAILS_CLOSE.match(line):
            out += ["", ":::", ""]
            i += 1
            continue
        if BLOCK_START.match(line):
            tag = BLOCK_START.match(line).group(1).lower()  # type: ignore[union-attr]
            end = _block_end(lines, i, tag)
            chunk = "\n".join(lines[i:end])
            md_chunk = html_block_to_md(chunk)
            if md_chunk:
                out += ["", md_chunk, ""]
            i = end
            continue
        if line.startswith("#"):
            line = ATTR_LIST.sub("", line)
        out.append(inline_html(line))
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")


def _strip_comments(md: str) -> str:
    """Remove HTML comments outside code fences."""
    if "<!--" not in md:
        return md
    out: list[str] = []
    fence: tuple[str, int] | None = None
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(COMMENT.sub("", "\n".join(buf)))
            buf.clear()

    for line in md.split("\n"):
        fm = FENCE.match(line)
        if fence:
            out.append(line)
            if fm and fm.group(2)[0] == fence[0] and len(fm.group(2)) >= fence[1] and not fm.group(3):
                fence = None
        elif fm:
            flush()
            fence = (fm.group(2)[0], len(fm.group(2)))
            out.append(line)
        else:
            buf.append(line)
    flush()
    return "\n".join(out)


def _block_end(lines: list[str], start: int, tag: str) -> int:
    opens = re.compile(rf"<{tag}\b", re.I)
    closes = re.compile(rf"</{tag}\s*>", re.I)
    depth = 0
    for j in range(start, min(len(lines), start + 600)):
        depth += len(opens.findall(lines[j])) - len(closes.findall(lines[j]))
        if depth <= 0:
            return j + 1
    return start + 1


def plain(md: str) -> str:
    """Prose-only text for indexing: markdown punctuation and fenced code removed."""
    out: list[str] = []
    fence = False
    for line in md.split("\n"):
        if FENCE.match(line):
            fence = not fence
            continue
        if fence or line.startswith(":::"):
            continue
        line = re.sub(r"^\s*(#{1,6}|>|[-*+]|\d+\.)\s+", "", line)
        line = re.sub(r"[*_`|]", "", line)
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
        out.append(line)
    return "\n".join(out)
