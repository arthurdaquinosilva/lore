"""Render course markdown to styled terminal lines, keeping track of where each code block sits."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Heading, Markdown
from rich.segment import Segment
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text

from lore.corpus import Block, classify
from lore.theme import Theme

LANG_MAP = {"jsx": "jsx", "tsx": "tsx", "django": "html+django", "jinja": "jinja", "po": "ini", "env": "ini", "sh": "bash",
            "shell": "bash", "zsh": "bash", "console": "bash", "js": "javascript", "ts": "typescript", "py": "python",
            "yml": "yaml", "text": "text", "txt": "text", "": "text"}

Line = list[Segment]


class _Heading(Heading):
    """Left-aligned headings with a marker instead of rich's centred, boxed ones."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"
        marks = {"h1": "█ ", "h2": "▌ ", "h3": "▎ ", "h4": "▏ "}
        mark = marks.get(self.tag, "")
        if self.tag in ("h1", "h2", "h3"):
            yield Text("")
        out = Text(mark, style=f"markdown.{self.tag}")
        out.append_text(text)
        yield out


class _Markdown(Markdown):
    elements = {**Markdown.elements, "heading_open": _Heading}


@dataclass
class Rendered:
    lines: list[Line] = field(default_factory=list)
    spans: dict[int, tuple[int, int]] = field(default_factory=dict)  # snippet index -> (first line, last line)
    width: int = 0
    _plain: list[str] | None = None

    @property
    def plain(self) -> list[str]:
        if self._plain is None:
            self._plain = ["".join(s.text for s in line) for line in self.lines]
        return self._plain


def _console(theme: Theme, width: int) -> Console:
    return Console(file=io.StringIO(), width=width, theme=theme.rich_theme, color_system="truecolor",
                   force_terminal=True, legacy_windows=False, highlight=False, emoji=False)


def _lines(console: Console, renderable, width: int) -> list[Line]:
    opts = console.options.update(width=width, no_wrap=False, highlight=False)
    return console.render_lines(renderable, opts, pad=False)


def _blank(lines: list[Line]) -> bool:
    return not lines or not "".join(s.text for s in lines[-1]).strip()


def _push(out: list[Line], new: list[Line]) -> None:
    """Append lines, collapsing runs of blank lines and trimming blank edges."""
    for ln in new:
        if not "".join(s.text for s in ln).strip():
            if _blank(out):
                continue
            out.append([])
        else:
            out.append(ln)


def _gap(out: list[Line]) -> None:
    if out and not _blank(out):
        out.append([])


def render(md: str, width: int, theme: Theme, selected: int | None = None, rail: bool = True) -> Rendered:
    width = max(30, width)
    console = _console(theme, width)
    result = Rendered(width=width)
    _render_blocks(classify(md), console, theme, result.lines, result.spans, width, selected)
    while result.lines and _blank(result.lines):
        result.lines.pop()
    return result


def _render_blocks(blocks: list[Block], console: Console, theme: Theme, out: list[Line], spans: dict, width: int,
                   selected: int | None) -> None:
    p = theme.p
    for blk in blocks:
        if blk.kind == "prose":
            _gap(out)
            _render_prose(blk.text, console, theme, out, spans, width, selected)
        elif blk.kind == "snippet":
            _gap(out)
            start = len(out)
            on = selected == blk.index
            out.extend(_code_block(console, theme, blk, width, on))
            spans[blk.index] = (start, len(out) - 1)
        elif blk.kind == "output":
            out.extend(_output_block(console, theme, blk, width))
        else:
            _gap(out)
            out.extend(_plain_block(console, theme, blk, width))


_MARK = re.compile(r"^:::(details\b.*)?$")


def _render_prose(text: str, console: Console, theme: Theme, out: list[Line], spans: dict, width: int, selected: int | None) -> None:
    """Prose may carry `:::details Title` … `:::` regions; everything else goes through rich's markdown."""
    p = theme.p
    buf: list[str] = []
    inside: list[str] | None = None
    title = ""

    def flush(lines: list[str], target: list[Line], w: int) -> None:
        chunk = "\n".join(lines).strip("\n")
        if chunk.strip():
            _push(target, _lines(console, _Markdown(chunk, code_theme=theme.syntax_theme, hyperlinks=False), w))

    for line in text.split("\n"):
        m = _MARK.match(line.strip())
        if m and m.group(1) and inside is None:
            flush(buf, out, width)
            buf, inside = [], []
            title = m.group(1)[len("details"):].strip() or "Details"
        elif m and not m.group(1) and inside is not None:
            _gap(out)
            head = Segment("▸ ", Style.parse(f"bold {p.accent2}")), Segment(title, Style.parse(f"bold {p.label}"))
            out.append(list(head))
            body: list[Line] = []
            flush(inside, body, width - 3)
            rail = Segment("┆ ", Style.parse(p.border))
            for ln in body:
                out.append([rail, *ln] if ln else [rail])
            inside = None
        elif inside is not None:
            inside.append(line)
        else:
            buf.append(line)
    flush(buf, out, width)
    if inside is not None:  # unterminated region: show it anyway
        flush(inside, out, width)


def _lexer(lang: str) -> str:
    return LANG_MAP.get(lang, lang or "text")


def _code_block(console: Console, theme: Theme, blk: Block, width: int, selected: bool) -> list[Line]:
    p = theme.p
    gutter_style = Style.parse(f"bold {p.accent}" if selected else p.border)
    label_style = Style.parse(f"bold {p.accent}" if selected else f"italic {p.faint}")
    label = blk.lang or "text"
    if selected:
        label += "   ·   y copy   a alias"
    syntax = Syntax(blk.text, _lexer(blk.lang), theme=theme.syntax_theme, word_wrap=True, padding=(0, 1),
                    background_color=p.surface, tab_size=4)
    body = _lines(console, syntax, width - 2)
    gutter = Segment("▎ ", gutter_style)
    out: list[Line] = [[Segment("▎ ", gutter_style), Segment(label, label_style)]]
    for ln in body:
        out.append([gutter, *ln])
    return out


def _output_block(console: Console, theme: Theme, blk: Block, width: int) -> list[Line]:
    p = theme.p
    gutter = Segment("┊ ", Style.parse(p.faint))
    out: list[Line] = [[gutter, Segment("output", Style.parse(f"italic {p.faint}"))]]
    if blk.lang:
        syntax = Syntax(blk.text, _lexer(blk.lang), theme=theme.syntax_theme, word_wrap=True, padding=(0, 1), background_color=None)
        body = _lines(console, syntax, width - 2)
    else:
        body = _lines(console, Text(blk.text, style=p.muted, no_wrap=False, overflow="fold"), width - 4)
        body = [[Segment("  ", Style()), *ln] for ln in body]
    for ln in body:
        out.append([gutter, *ln])
    return out


def _plain_block(console: Console, theme: Theme, blk: Block, width: int) -> list[Line]:
    p = theme.p
    gutter = Segment("┊ ", Style.parse(p.border))
    body = _lines(console, Text(blk.text, style=p.muted, no_wrap=False, overflow="fold"), width - 4)
    return [[gutter, Segment("  ", Style()), *ln] for ln in body]


# ── terminal-agnostic conversions ───────────────────────────────────────────

_style_cache: dict[Style, str] = {}


def pt_style(style: Style | None) -> str:
    if style is None:
        return ""
    cached = _style_cache.get(style)
    if cached is not None:
        return cached
    parts: list[str] = []
    for color, prefix in ((style.color, "fg:"), (style.bgcolor, "bg:")):
        if color is not None and not color.is_default:
            t = color.get_truecolor()
            parts.append(f"{prefix}#{t.red:02x}{t.green:02x}{t.blue:02x}")
    if style.bold:
        parts.append("bold")
    if style.italic:
        parts.append("italic")
    if style.underline:
        parts.append("underline")
    if style.strike:
        parts.append("strike")
    if style.dim:
        parts.append("dim")
    out = " ".join(parts)
    _style_cache[style] = out
    return out


def fragments(line: Line, find: str = "", current: bool = False) -> list[tuple[str, str]]:
    """prompt_toolkit fragments for a rendered line; `find` is highlighted case-insensitively."""
    frags = [(pt_style(s.style), s.text) for s in line if s.text and not s.control]
    if not find:
        return frags
    text = "".join(t for _s, t in frags)
    hits = [(m.start(), m.end()) for m in re.finditer(re.escape(find), text, re.I)]
    if not hits:
        return frags
    out: list[tuple[str, str]] = []
    pos = 0
    hi = "class:find.current" if current else "class:find"
    for style, chunk in frags:
        start, end = pos, pos + len(chunk)
        cur = start
        for a, b in hits:
            if b <= start or a >= end:
                continue
            a, b = max(a, start), min(b, end)
            if a > cur:
                out.append((style, chunk[cur - start: a - start]))
            out.append((f"{style} {hi}".strip(), chunk[a - start: b - start]))
            cur = b
        if cur < end:
            out.append((style, chunk[cur - start:]))
        pos = end
    return out


def ansi_lines(rendered: Rendered, theme: Theme) -> list[str]:
    """The rendered lines as ANSI strings, for printing outside the full-screen app."""
    console = _console(theme, rendered.width)
    parts: list[str] = []
    for line in rendered.lines:
        with console.capture() as cap:
            console.print(Text.assemble(*[(s.text, s.style) for s in line]), end="", overflow="ignore", no_wrap=True, soft_wrap=True)
        parts.append(cap.get())
    return parts


def head(md: str, limit: int) -> str:
    """The start of a body for a preview: up to `limit` characters, cut at a paragraph and never inside a fence."""
    if len(md) <= limit:
        return md
    cut, fence, size = [], False, 0
    for line in md.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            fence = not fence
        cut.append(line)
        size += len(line) + 1
        if size >= limit and not fence and not line.strip():
            break
    return "\n".join(cut)
