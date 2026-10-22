<div align="center">

<img src="https://raw.githubusercontent.com/arthurdaquinosilva/lore/main/docs/assets/cover.svg?sanitize=true" alt="lore's start screen: the LORE: wordmark, counts, the input bar and your aliases with a preview" width="900">

# ✦ lore

**Your courses, searchable offline.**
A devdocs for the terminal: type a few words, pick a suggestion, read it or copy the code, and keep aliases for what you look up again and again.

[![tests](https://github.com/arthurdaquinosilva/lore/actions/workflows/tests.yml/badge.svg)](https://github.com/arthurdaquinosilva/lore/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/arthurdaquinosilva/lore/blob/main/pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/arthurdaquinosilva/lore/blob/main/LICENSE)

</div>

## See it in action

<p align="center">
<img src="https://raw.githubusercontent.com/arthurdaquinosilva/lore/main/docs/assets/search.svg?sanitize=true" alt="lore searching for 'git rebase onto': suggestions on the left, a preview of the selected one on the right" width="820">
</p>

## Why lore

- **Instant.** The whole library is one SQLite file on your machine. Results update on every key in a few milliseconds, with no network and no browser.
- **Three kinds of answer.** ▤ topics, ❯ code snippets *with the output the course printed under them*, and ◆ definitions. Typos are repaired, filters narrow the search (`in:git`, `kind:term`, `lang:bash`).
- **Read or grab.** A preview beside the list, a scrolling reader with highlighted code and exercise solutions, and one key to copy a code block.
- **Aliases.** Name a topic, a single code block, a definition or your own text, and bring it back with `lore @name`.
- **Feels good.** The same calm look as [ember](https://github.com/arthurdaquinosilva/ember): rule layout, key bar, the shared pitch palette, vi or emacs keys.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/arthurdaquinosilva/lore/main/install.sh | sh
```

The installer picks a suitable Python, puts lore in its own virtual environment (using [pipx](https://pipx.pypa.io/) if you have it), links the `lore` command into `~/.local/bin`, and builds the index from your course sources. Nothing is added to your projects' environments. Remove it any time with `… | sh -s -- --uninstall`.

Prefer to do it yourself?

```sh
pipx install "lore-docs @ git+https://github.com/arthurdaquinosilva/lore.git"
lore index --source ~/programming-material/_build/sources
```

Then run `lore`. Requires Python 3.10+ and git on macOS or Linux.

> **Tip:** lore searches the course sources it was pointed at (`~/programming-material/_build/sources` by default). Run `lore index` again whenever the courses change; it takes about three seconds and never touches your aliases.

## Quick tour

```sh
lore                            # open the interface
lore git rebase onto            # …already searching
lore -c sql window functions    # one course (also: in:sql inside the query)
lore alias add undo "git reset --soft"
lore @undo                      # recall it: prints the code, -y also copies it
lore --pick git log | pbcopy    # use it as a picker
```

| | |
| --- | --- |
| **type** | search; the list and the preview follow |
| **↑ ↓** · Tab / Shift+Tab | move through the suggestions |
| **Enter** | read the selected result |
| **Ctrl+A** | save it as an alias |
| **Ctrl+Y** | copy the snippet, definition or topic |
| **Ctrl+T** · **Ctrl+S** | cycle the kind · the course |
| **Esc** | clear the query; leave when it is empty |
| **F1** · **?** | every key |

In the reader: **j k** scroll, **n p** next and previous topic, **Tab** select a code block, **y** copy, **a** alias, **/** find, **t** contents of the course, **q** back.

<p align="center">
<img src="https://raw.githubusercontent.com/arthurdaquinosilva/lore/main/docs/assets/reader.svg?sanitize=true" alt="lore's reader: a topic with a selected code block and the output printed under it" width="820">
</p>

## Documentation

| Guide | What's inside |
| --- | --- |
| [Features](https://github.com/arthurdaquinosilva/lore/blob/main/docs/features.md) | Searching and ranking, filters, the reader, aliases, copying, the command line, how the index is built |
| [Configuration](https://github.com/arthurdaquinosilva/lore/blob/main/docs/configuration.md) | The installer, where files live, `config.toml`, keeping the index current |

## Command line

```sh
lore                         # interface
lore QUERY …                 # interface, already searching   (-c COURSE, -k KIND)
lore @NAME                   # recall an alias               (-y copy, -o reader, --code)
lore search QUERY … --json   # list matches without the interface
lore get git:7.3             # print a topic, snippet (git:7.3#2) or alias
lore alias add|ls|mv|note|rm
lore index [--source DIR]    # (re)build the index
lore courses | info | config
lore --vi
```

## Development

```sh
git clone https://github.com/arthurdaquinosilva/lore.git && cd lore
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                 # unit tests, plus the interface driven through a pseudo-terminal
.venv/bin/python scripts/screenshots.py    # re-record docs/assets/*.svg from the real interface
```

lore is built on [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) (input and layout), [Rich](https://github.com/Textualize/rich) (markdown and code output) and [Pygments](https://pygments.org/) (highlighting), with SQLite FTS5 for search.

## Known limits

- It reads the assembled course sources (`_build/sources/<course>.md`), not the HTML pages. A different source format needs a change in `corpus.py` and `htmlclean.py`.
- Figures are not drawn; the reader shows their caption. Interactive widgets in the courses are dropped.
- Ranking is full-text, not semantic: a vague question can surface noisy snippets, so prefer the words the courses use.

## License

[MIT](https://github.com/arthurdaquinosilva/lore/blob/main/LICENSE) © Arthur D'Aquino
