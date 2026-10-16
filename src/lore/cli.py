"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lore import __version__
from lore.aliases import Alias, AliasError, Aliases, Recent
from lore.config import Settings, load as load_settings
from lore.paths import aliases_path, config_path, data_dir, index_path, recent_path
from lore.store import IndexMissing, Item, Store
from lore.theme import PALETTES, get_theme

SUBCOMMANDS = {"search", "get", "alias", "aliases", "index", "courses", "info", "config", "open"}

HELP = """\
usage: lore [options] [QUERY …]
       lore @NAME                 recall an alias (prints it; -o opens the reader)
       lore search QUERY          list matches without the interface
       lore get TARGET            print a topic, snippet or alias  (TARGET: @alias, an id, or a query)
       lore alias add|ls|rm|mv|note …
       lore index [--source DIR]  (re)build the offline index from the course sources
       lore courses | info | config

Offline search over the course library: topics, code snippets and definitions.
With no arguments it opens the interface; with a query it opens it already searching.

options:
  -c, --course COURSE   limit the search to one course (git, python, sql, …)
  -k, --kind KIND       topic | snippet | term
  --theme NAME          void | nebula | matrix
  --vi                  vi key bindings in the search box
  --pick                use as a picker:  lore --pick git rebase | pbcopy
  --version             show the version

Inside the interface press F1 (or ? on an empty prompt) for every key.
"""


def _console(stream=None):
    from rich.console import Console

    return Console(file=stream or sys.stdout, highlight=False)


def eprint(*a) -> None:
    print(*a, file=sys.stderr)


# ── index handling ──────────────────────────────────────────────────────────

def ensure_store(settings: Settings, quiet: bool = False) -> Store | None:
    try:
        return Store()
    except IndexMissing:
        pass
    src = settings.source_dir
    if src.is_dir() and list(src.glob("*.md")):
        if not quiet:
            eprint(f"No index yet — building it from {src} (one time, a few seconds)…")
        from lore.indexer import build

        try:
            counts = build(src)
        except Exception as e:  # pragma: no cover
            eprint(f"lore: could not build the index: {e}")
            return None
        if not quiet:
            eprint(f"Indexed {counts['courses']} courses: {counts['topics']:,} topics, {counts['snippets']:,} snippets, {counts['terms']:,} terms.")
        return Store()
    eprint(f"lore: no index at {index_path()} and no course sources at {src}.")
    eprint("      Point lore at the courses with:  lore index --source /path/to/_build/sources")
    return None


def cmd_index(args: argparse.Namespace, settings: Settings) -> int:
    from lore.indexer import build

    src = Path(args.source).expanduser() if args.source else settings.source_dir
    if not src.is_dir():
        eprint(f"lore: {src} is not a directory")
        return 2
    try:
        counts = build(src, progress=(lambda name: eprint(f"  {name}")) if sys.stderr.isatty() else None)
    except FileNotFoundError as e:
        eprint(f"lore: {e}")
        return 2
    print(f"Indexed {counts['courses']} courses from {src}")
    print(f"  {counts['topics']:,} topics · {counts['snippets']:,} snippets · {counts['terms']:,} terms")
    print(f"  {index_path()}  ({index_path().stat().st_size / 1e6:.0f} MB)")
    return 0


def cmd_courses(store: Store) -> int:
    counts = store.course_counts()
    width = max(len(k) for k in store.courses)
    for key, (title, _brand, _o) in store.courses.items():
        print(f"{key:<{width}}  {counts.get(key, 0):>4} topics  {title}")
    return 0


def cmd_info(store: Store, settings: Settings) -> int:
    import datetime

    m = store.meta
    built = datetime.datetime.fromtimestamp(int(m.get("built_at", "0"))).strftime("%Y-%m-%d %H:%M")
    c = store.counts
    print(f"lore {__version__}")
    print(f"  index     {store.path}  (built {built})")
    print(f"  source    {m.get('source')}{'  — newer than the index, run: lore index' if store.stale() else ''}")
    print(f"  content   {c.get('courses')} courses · {c.get('topics'):,} topics · {c.get('snippets'):,} snippets · {c.get('terms'):,} terms")
    print(f"  aliases   {aliases_path()}  ({len(Aliases().items)})")
    print(f"  config    {config_path()}{'' if config_path().is_file() else '  (not created)'}")
    print(f"  theme     {settings.theme}")
    return 0


# ── item printing ───────────────────────────────────────────────────────────

def item_text(item: Item, code: bool = False) -> str:
    """Plain text for an item: a snippet's code, a definition, or a topic's markdown."""
    if item.kind == "snippet":
        return item.body + ("\n" + item.aux if item.aux and not code else "")
    return item.body


def show_item(item: Item, store: Store, settings: Settings, code_only: bool = False, raw: bool = False) -> None:
    theme = get_theme(settings.theme)
    out = sys.stdout
    if raw or not out.isatty():
        if item.kind == "snippet" and (code_only or not out.isatty()):
            print(item.body)
        elif item.kind == "snippet":
            print(f"{item.caption}\n\n```{item.lang}\n{item.body}\n```" + (f"\n\n```text\n{item.aux}\n```" if item.aux else ""))
        else:
            print(f"# {item.title}\n\n{item.body}" if item.kind in ("topic", "guide", "summary", "exercise") else item.body)
        return
    from lore.render import ansi_lines, render

    console = _console()
    width = min(console.size.width - 2, 110)
    course = store.courses.get(item.course, (item.course, item.course, 0))[1]
    where = f"{course} › {('§' + str(item.section_no) + ' ') if item.section_no else ''}{item.section}"
    if item.kind in ("snippet", "term") and item.parent:
        parent = store.get(item.parent)
        if parent:
            where += f" › {parent.number} {parent.title}".rstrip()
    elif item.number and not item.number.endswith(".0"):
        where += f" › {item.number}"
    p = theme.p
    out.write(f"\x1b[38;2;{int(p.faint[1:3], 16)};{int(p.faint[3:5], 16)};{int(p.faint[5:7], 16)}m  {where}\x1b[0m\n")
    if item.kind == "snippet":
        md = (f"{item.caption}\n\n" if item.caption and not code_only else "") + f"```{item.lang}\n{item.body}\n```\n"
        if item.aux and not code_only:
            md += f"\n```text\n{item.aux}\n```\n"
    elif item.kind == "term":
        md = f"**{item.title}**\n\n{item.body}"
    else:
        md = f"# {item.title}\n\n{item.body}"
    r = render(md, width, theme, selected=None)
    lines = ansi_lines(r, theme)
    text = "\n".join("  " + ln for ln in lines) + "\n"
    if len(lines) > console.size.height - 3 and item.kind not in ("snippet", "term"):
        import pydoc

        try:
            pydoc.pager(text)
            return
        except Exception:  # pragma: no cover
            pass
    out.write(text)


def resolve_target(target: str, store: Store, aliases: Aliases, args=None) -> tuple[Item | None, Alias | None, str]:
    """TARGET is `@alias`, an item id (`git:7.3`, `git:7.3#2`) or a search query (best match)."""
    if target.startswith("@") and len(target) > 1:
        a = aliases.get(target)
        if a is None:
            return None, None, f"no alias named {target}"
        res = aliases.resolve(a, store)
        if a.kind == "text":
            return None, a, ""
        if res.item is None:
            return None, a, f"@{a.name} points at something that is no longer in the index"
        return res.item, a, ""
    item = store.get(target)
    if item:
        return item, None, ""
    from lore.search import Searcher

    res = Searcher(store).search(target, getattr(args, "course", None), getattr(args, "kind", None), limit=5)
    if not res.hits:
        return None, None, f"nothing matches '{target}'"
    return res.hits[0].item, None, ""


# ── commands ────────────────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace, store: Store, settings: Settings) -> int:
    from lore.search import Searcher

    query = " ".join(args.query)
    res = Searcher(store).search(query, args.course, args.kind, limit=args.n)
    hits = res.hits[: args.n]
    if args.json:
        print(json.dumps([{"id": h.item.id, "kind": h.item.kind, "course": h.item.course, "title": h.item.title,
                           "section": h.item.section, "number": h.item.number, "score": round(h.score, 2)} for h in hits], indent=2))
        return 0 if hits else 1
    if not hits:
        eprint(f"nothing matches '{query}'")
        return 1
    if res.corrected:
        eprint(f"(showing results for '{res.corrected}')")
    for h in hits:
        it = h.item
        title = it.title.replace("`", "")
        print(f"{it.id:<28} {it.kind:<8} {store.courses[it.course][1]:<12} {title[:70]}")
    return 0


def cmd_get(args: argparse.Namespace, store: Store, aliases: Aliases, settings: Settings) -> int:
    item, alias, err = resolve_target(" ".join(args.target), store, aliases, args)
    if err:
        eprint(f"lore: {err}")
        return 1
    if alias is not None and alias.kind == "text":
        text = alias.text
        print(text)
        aliases.touch(alias.name)
        if args.copy:
            _copy(text)
        return 0
    assert item is not None
    if alias:
        aliases.touch(alias.name)
    if args.copy:
        _copy(item.body if item.kind in ("snippet",) else item_text(item, code=True))
    show_item(item, store, settings, code_only=args.code, raw=args.raw)
    return 0


def _copy(text: str) -> None:
    from lore import clipboard

    how = clipboard.copy(text)
    eprint(f"copied to the clipboard ({how})" if how else "lore: no clipboard tool found")


def cmd_alias(args: argparse.Namespace, store: Store, aliases: Aliases, settings: Settings) -> int:
    act = args.action
    try:
        if act == "ls":
            items = aliases.ordered() if args.sort == "used" else sorted(aliases.items.values(), key=lambda a: a.name)
            if not items:
                print("No aliases yet. Save one with Ctrl+A in the interface, or: lore alias add NAME QUERY")
                return 0
            for a in items:
                res = aliases.resolve(a, store)
                kind = "note" if a.kind == "text" else (res.item.kind if res.item else "missing")
                flag = "  (moved)" if res.moved else ""
                print(f"@{a.name:<20} {kind:<8} {a.summary[:60]}{flag}")
            return 0
        if act == "add":
            if args.text is not None:
                text = sys.stdin.read() if args.text == "-" else args.text
                a, rep = aliases.add_text(args.name, text, args.note or "", store)
            else:
                target = " ".join(args.target)
                if not target:
                    eprint("lore: say what to alias — a query, an id, or --text")
                    return 2
                item, _alias, err = resolve_target(target, store, aliases, args)
                if err or item is None:
                    eprint(f"lore: {err or 'no such entry'}")
                    return 1
                a, rep = aliases.add_ref(args.name, item, args.note or "", store)
            print(f"@{a.name} {'updated' if rep else 'saved'} → {a.summary}")
            return 0
        if act == "rm":
            for n in args.names:
                print(f"@{n.lstrip('@')} removed" if aliases.remove(n) else f"no alias named @{n.lstrip('@')}")
            return 0
        if act == "mv":
            aliases.rename(args.old, args.new, store)
            print(f"@{args.old.lstrip('@')} → @{args.new.lstrip('@')}")
            return 0
        if act == "note":
            if aliases.get(args.name) is None:
                eprint(f"no alias named @{args.name.lstrip('@')}")
                return 1
            aliases.set_note(args.name, " ".join(args.text))
            return 0
    except AliasError as e:
        eprint(f"lore: {e}")
        return 1
    return 2


def cmd_recall(name: str, args, store: Store, aliases: Aliases, settings: Settings) -> int:
    """`lore @name`: print the alias, or open it in the reader with -o."""
    a = aliases.get(name)
    if a is None:
        # `@git` style course scope when it is not an alias
        if store.resolve_course(name.lstrip("@")):
            return run_ui(store, aliases, settings, query=f"@{name.lstrip('@')} ", args=args)
        eprint(f"lore: no alias named {name}. See them with: lore alias ls")
        return 1
    if args.open and sys.stdout.isatty():
        return run_ui(store, aliases, settings, open_alias=a.name, args=args)
    item, alias, err = resolve_target(name, store, aliases)
    if err:
        eprint(f"lore: {err}")
        return 1
    aliases.touch(a.name)
    if a.kind == "text":
        print(a.text)
        if args.copy:
            _copy(a.text)
        return 0
    assert item is not None
    if args.copy:
        _copy(item.body)
    show_item(item, store, settings, code_only=args.code, raw=args.raw)
    return 0


def _tty_output():
    """When stdout is piped (`lore | pbcopy`) the interface is drawn on the controlling terminal instead."""
    if sys.stdout.isatty():
        return None
    try:
        from prompt_toolkit.output.defaults import create_output

        return create_output(stdout=open("/dev/tty", "w"))
    except OSError:
        return None


def run_ui(store: Store, aliases: Aliases, settings: Settings, query: str = "", open_alias: str | None = None, args=None) -> int:
    piped = not sys.stdout.isatty() and sys.stdin.isatty() and Path("/dev/tty").exists()
    if not (sys.stdin.isatty() and (sys.stdout.isatty() or (piped and getattr(args, "pick", False)))):
        if query:
            ns = argparse.Namespace(query=query.split(), course=getattr(args, "course", None), kind=getattr(args, "kind", None), n=10, json=False)
            return cmd_search(ns, store, settings)
        eprint("lore: the interface needs a terminal. Try:  lore search QUERY   or   lore get QUERY")
        return 2
    from lore.ui import LoreApp

    course = getattr(args, "course", None)
    app = LoreApp(store, aliases, Recent.load(recent_path()), settings, get_theme(settings.theme), query=query, course=course,
                  kind=getattr(args, "kind", None), output=None if sys.stdout.isatty() else _tty_output())
    outcome = app.run(open_alias=open_alias)
    if outcome and outcome.text:
        if sys.stdout.isatty() and not outcome.markdown:
            from rich.syntax import Syntax

            theme = get_theme(settings.theme)
            _console().print(Syntax(outcome.text, outcome.lang or "text", theme=theme.syntax_theme, word_wrap=True, background_color="default"))
        else:
            print(outcome.text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lore", add_help=False)
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("--version", action="store_true")
    p.add_argument("-c", "--course")
    p.add_argument("-k", "--kind", choices=["topic", "snippet", "term"])
    p.add_argument("--theme", choices=list(PALETTES))
    p.add_argument("--vi", action="store_true")
    p.add_argument("-o", "--open", action="store_true", help="with @alias: open in the reader")
    p.add_argument("-y", "--copy", action="store_true")
    p.add_argument("--code", action="store_true")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--pick", action="store_true", help="draw on the terminal even when stdout is piped; print the choice")
    p.add_argument("query", nargs="*")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings, warnings = load_settings()
    for w in warnings:
        eprint(f"lore: config: {w}")

    # subcommands first
    if argv and argv[0] in SUBCOMMANDS:
        return _subcommand(argv[0], argv[1:], settings)

    args = build_parser().parse_args(argv)
    if args.help:
        print(HELP, end="")
        return 0
    if args.version:
        print(f"lore {__version__}")
        return 0
    if args.theme:
        settings.theme = args.theme
    if args.vi:
        settings.editing_mode = "vi"
    store = ensure_store(settings)
    if store is None:
        return 2
    aliases = Aliases()
    if args.course:
        found = store.resolve_course(args.course)
        if not found:
            eprint(f"lore: unknown course '{args.course}'. See them with: lore courses")
            return 2
        args.course = found
    query = " ".join(args.query).strip()
    if query.startswith("@") and " " not in query:
        return cmd_recall(query, args, store, aliases, settings)
    return run_ui(store, aliases, settings, query=query, args=args)


def _subcommand(name: str, rest: list[str], settings: Settings) -> int:
    p = argparse.ArgumentParser(prog=f"lore {name}")
    if name == "index":
        p.add_argument("--source")
        return cmd_index(p.parse_args(rest), settings)
    store = ensure_store(settings)
    if store is None:
        return 2
    aliases = Aliases()
    if name == "courses":
        return cmd_courses(store)
    if name == "info":
        return cmd_info(store, settings)
    if name == "config":
        print(f"config file: {config_path()}{'' if config_path().is_file() else '  (not created)'}")
        print(f"data dir:    {data_dir()}")
        print(f"source:      {settings.source_dir}")
        print(f"theme: {settings.theme}   editing_mode: {settings.editing_mode}   preview: {settings.preview}")
        return 0
    if name == "search":
        p.add_argument("query", nargs="+")
        p.add_argument("-n", type=int, default=10)
        p.add_argument("-c", "--course")
        p.add_argument("-k", "--kind", choices=["topic", "snippet", "term"])
        p.add_argument("--json", action="store_true")
        a = p.parse_args(rest)
        if a.course:
            a.course = store.resolve_course(a.course) or a.course
        return cmd_search(a, store, settings)
    if name in ("get", "open"):
        p.add_argument("target", nargs="+")
        p.add_argument("-c", "--course")
        p.add_argument("-k", "--kind", choices=["topic", "snippet", "term"])
        p.add_argument("--code", action="store_true", help="print only the code of a snippet")
        p.add_argument("--raw", action="store_true", help="print markdown, not the rendered page")
        p.add_argument("-y", "--copy", action="store_true", help="also copy it to the clipboard")
        a = p.parse_args(rest)
        if a.course:
            a.course = store.resolve_course(a.course) or a.course
        return cmd_get(a, store, aliases, settings)
    if name in ("alias", "aliases"):
        sub = p.add_subparsers(dest="action", required=False)
        ls = sub.add_parser("ls")
        ls.add_argument("--sort", choices=["name", "used"], default="name")
        add = sub.add_parser("add")
        add.add_argument("name")
        add.add_argument("target", nargs="*")
        add.add_argument("--text", help="alias a piece of text instead of an entry ('-' reads stdin)")
        add.add_argument("--note")
        add.add_argument("-c", "--course")
        add.add_argument("-k", "--kind", choices=["topic", "snippet", "term"])
        rm = sub.add_parser("rm")
        rm.add_argument("names", nargs="+")
        mv = sub.add_parser("mv")
        mv.add_argument("old")
        mv.add_argument("new")
        note = sub.add_parser("note")
        note.add_argument("name")
        note.add_argument("text", nargs="+")
        a = p.parse_args(rest or ["ls"])
        if a.action is None:
            a.action, a.sort = "ls", "name"
        if getattr(a, "course", None):
            a.course = store.resolve_course(a.course) or a.course
        return cmd_alias(a, store, aliases, settings)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
