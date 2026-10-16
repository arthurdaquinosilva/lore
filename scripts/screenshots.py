"""Record lore for the README: the start screen, a search with its preview, and the reader.

    python scripts/screenshots.py   # writes docs/assets/{cover,search,reader}.svg

The images are the real interface running on the real index, in a throwaway LORE_HOME so your own
aliases never end up in them. Needs the course sources (LORE_SOURCE, default ~/programming-material).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from _termshot import ROOT, capture, save_svg, to_text

OUT = ROOT / "docs" / "assets"


def prepare(home: Path) -> None:
    os.environ["LORE_HOME"] = str(home)
    from lore.aliases import Aliases
    from lore.indexer import build
    from lore.paths import default_source
    from lore.store import Store

    build(default_source())
    store = Store()
    al = Aliases()
    from lore.search import Searcher

    search = Searcher(store)
    for name, query, kind in (("undo-commit", "git reset --soft HEAD~1", "snippet"), ("n-plus-one", "n+1 query problem", "topic"),
                              ("flex-center", "box alignment shorthands", "topic"), ("closure", "closure", "term")):
        hits = search.search(query, kind=kind).hits
        if not hits:
            raise SystemExit(f"no hit for {query!r}")
        al.add_ref(name, hits[0].item, store=store)
    store.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        prepare(home)
        cover = capture([], 120, 36, home=home)
        save_svg(to_text(cover), OUT / "cover.svg", 120, title=None, frameless=True)

        search = capture([("git rebase onto", 1.0), ("\x1b[B", 0.6)], 120, 30, home=home)
        save_svg(to_text(search), OUT / "search.svg", 120, title="lore", frameless=False)

        reader = capture([("flexbox center", 0.8), ("\x1b[B", 0.3), ("\x1b[B", 0.3), ("\r", 1.0), ("\t", 0.5)], 120, 34, home=home)
        save_svg(to_text(reader), OUT / "reader.svg", 120, title="lore", frameless=False)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    main()
