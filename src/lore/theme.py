"""Color palettes shared by the prompt_toolkit UI, the rich renderer and pygments (the same three as ember)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.styles import merge_styles, style_from_pygments_cls
from pygments.style import Style as PygmentsStyle
from pygments.token import Comment, Error, Generic, Keyword, Name, Number, Operator, Punctuation, String, Text, Token
from rich.syntax import PygmentsSyntaxTheme
from rich.theme import Theme as RichTheme


@dataclass(frozen=True)
class Palette:
    name: str
    fg: str
    muted: str
    faint: str
    border: str
    surface: str
    selection: str
    bar: str  # filled input bar
    label: str  # key-bar labels and banner values
    accent: str
    accent2: str
    ok: str
    err: str
    warn: str
    info: str
    # syntax
    keyword: str
    builtin: str
    function: str
    klass: str
    string: str
    number: str
    comment: str
    operator: str
    decorator: str


PALETTES: dict[str, Palette] = {
    # Near-black monochrome with a single warm accent.
    "void": Palette(
        name="void",
        fg="#e7e7e7",
        muted="#8b8b8b",
        faint="#555555",
        border="#3b3b3b",
        surface="#161616",
        selection="#2b2b2b",
        bar="#24262b",
        label="#86c7c0",
        accent="#ff8a4c",
        accent2="#ffc46b",
        ok="#7ee2a8",
        err="#ff6b6b",
        warn="#f2c14e",
        info="#7cc4ff",
        keyword="#ff9e6b",
        builtin="#7cc4ff",
        function="#e7e7e7",
        klass="#ffd08a",
        string="#a8d8a0",
        number="#f5a97f",
        comment="#5f5f5f",
        operator="#9a9a9a",
        decorator="#c9a0ff",
    ),
    "nebula": Palette(
        name="nebula",
        fg="#e4e1f5",
        muted="#8c87a8",
        faint="#56516e",
        border="#3a3552",
        surface="#15131f",
        selection="#2a2640",
        bar="#262238",
        label="#6ee7f9",
        accent="#b18cff",
        accent2="#6ee7f9",
        ok="#6ee7b7",
        err="#fb7185",
        warn="#fcd34d",
        info="#6ee7f9",
        keyword="#c4a5ff",
        builtin="#6ee7f9",
        function="#f0ecff",
        klass="#f9a8d4",
        string="#86efac",
        number="#fda4af",
        comment="#5c5776",
        operator="#a39fc0",
        decorator="#f9a8d4",
    ),
    "matrix": Palette(
        name="matrix",
        fg="#d7f5dd",
        muted="#7a9a80",
        faint="#46604b",
        border="#2e4533",
        surface="#0f1a12",
        selection="#1f3324",
        bar="#18261c",
        label="#5eead4",
        accent="#4ade80",
        accent2="#a3e635",
        ok="#4ade80",
        err="#f87171",
        warn="#facc15",
        info="#5eead4",
        keyword="#4ade80",
        builtin="#5eead4",
        function="#ecfdf0",
        klass="#a3e635",
        string="#bef264",
        number="#fde68a",
        comment="#4b6b52",
        operator="#8fb396",
        decorator="#5eead4",
    ),
}

DEFAULT_THEME = "void"


def course_color(p: "Palette", index: int) -> str:
    """Each course gets a stable accent from the palette, so a result's origin is visible at a glance."""
    ring = [p.accent, p.info, p.ok, p.klass, p.decorator, p.string, p.number, p.label]
    return ring[index % len(ring)]


class Theme:
    def __init__(self, palette: Palette):
        self.p = palette

    @property
    def name(self) -> str:
        return self.p.name

    @cached_property
    def pygments_style(self) -> type[PygmentsStyle]:
        p = self.p
        return type(
            f"Lore{p.name.title()}Style",
            (PygmentsStyle,),
            {
                "background_color": None,
                "highlight_color": p.selection,
                "styles": {
                    Token: p.fg,
                    Text: p.fg,
                    Comment: f"italic {p.comment}",
                    Keyword: p.keyword,
                    Keyword.Constant: p.number,
                    Keyword.Namespace: p.keyword,
                    Operator: p.operator,
                    Operator.Word: p.keyword,
                    Punctuation: p.operator,
                    Name: p.fg,
                    Name.Builtin: p.builtin,
                    Name.Builtin.Pseudo: f"italic {p.builtin}",
                    Name.Function: p.function,
                    Name.Class: f"bold {p.klass}",
                    Name.Decorator: p.decorator,
                    Name.Exception: p.klass,
                    Name.Namespace: p.klass,
                    Name.Tag: p.keyword,
                    Name.Attribute: p.builtin,
                    String: p.string,
                    String.Doc: f"italic {p.comment}",
                    String.Escape: p.number,
                    String.Interpol: p.accent2,
                    Number: p.number,
                    Generic.Deleted: p.err,
                    Generic.Inserted: p.ok,
                    Generic.Heading: f"bold {p.fg}",
                    Generic.Subheading: p.muted,
                    Generic.Prompt: p.muted,
                    Generic.Error: p.err,
                    Error: p.err,
                },
            },
        )

    @cached_property
    def syntax_theme(self) -> PygmentsSyntaxTheme:
        return PygmentsSyntaxTheme(self.pygments_style)

    @cached_property
    def pt_style(self) -> PTStyle:
        p = self.p
        ui = PTStyle.from_dict(
            {
                "": p.fg,
                "rule": p.border,
                "wordmark": "bold #34d399",  # emerald, whatever the theme
                "brand": f"bold {p.accent}",
                "brand.dim": p.faint,
                "prompt": f"bold {p.accent}",
                "prompt.alias": f"bold {p.accent2}",
                "prompt.find": f"bold {p.info}",
                "placeholder": p.faint,
                "counter": p.faint,
                "chip": f"bg:{p.bar} {p.muted}",
                "chip.on": f"bg:{p.bar} bold {p.label}",
                "row": "",
                "row.selected": f"bg:{p.selection}",
                "row.title": p.fg,
                "row.title.selected": f"bold {p.fg}",
                "row.meta": p.faint,
                "row.excerpt": p.muted,
                "row.mark": f"bold {p.accent2}",
                "row.cursor": f"bold {p.accent}",
                "kind.topic": p.info,
                "kind.snippet": p.ok,
                "kind.term": p.klass,
                "kind.alias": p.accent2,
                "kind.recent": p.faint,
                "kind.guide": p.decorator,
                "section.head": f"bold {p.label}",
                "divider": p.border,
                "keybar.label": f"bold {p.label}",
                "keybar.key": p.fg,
                "keybar.sep": p.faint,
                "status": p.muted,
                "status.dim": p.faint,
                "status.accent": p.accent,
                "status.ok": p.ok,
                "status.err": p.err,
                "status.warn": p.warn,
                "status.sep": p.faint,
                "flash": f"bold {p.accent2}",
                "find": f"bg:{p.accent2} #000000",
                "find.current": f"bg:{p.accent} #000000",
                "crumb": p.muted,
                "crumb.here": f"bold {p.fg}",
                "scrollbar": p.border,
                "scrollbar.thumb": p.faint,
                "overlay": f"bg:{p.surface}",
                "overlay.title": f"bold {p.accent}",
                "overlay.key": f"bold {p.label}",
                "overlay.desc": p.muted,
                "empty": p.faint,
                "empty.head": f"bold {p.muted}",
            }
        )
        return merge_styles([style_from_pygments_cls(self.pygments_style), ui])

    @cached_property
    def rich_theme(self) -> RichTheme:
        p = self.p
        return RichTheme(
            {
                "lore.fg": p.fg,
                "lore.muted": p.muted,
                "lore.faint": p.faint,
                "lore.border": p.border,
                "lore.accent": p.accent,
                "lore.accent2": p.accent2,
                "lore.ok": p.ok,
                "lore.err": p.err,
                "lore.label": f"bold {p.label}",
                "markdown.h1": f"bold {p.accent}",
                "markdown.h2": f"bold {p.accent}",
                "markdown.h3": f"bold {p.accent2}",
                "markdown.h4": f"bold {p.label}",
                "markdown.h5": f"bold {p.muted}",
                "markdown.h6": f"italic {p.muted}",
                "markdown.code": f"{p.accent2}",
                "markdown.code_block": p.fg,
                "markdown.strong": f"bold {p.fg}",
                "markdown.em": f"italic {p.fg}",
                "markdown.emph": f"italic {p.fg}",
                "markdown.block_quote": p.muted,
                "markdown.item.bullet": p.accent,
                "markdown.item.number": p.accent,
                "markdown.hr": p.border,
                "markdown.link": f"underline {p.info}",
                "markdown.link_url": f"underline {p.info}",
                "markdown.s": "strike",
                "table.header": f"bold {p.accent}",
                "table.border": p.border,
                "rule.line": p.border,
                "repr.number": p.number,
            }
        )


def get_theme(name: str | None) -> Theme:
    return Theme(PALETTES.get(name or DEFAULT_THEME, PALETTES[DEFAULT_THEME]))
