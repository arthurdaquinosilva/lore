# Features

## Searching

Type in the prompt and the list under it updates on every key. Each row has two lines: the title with the matched words highlighted, and an excerpt around the match. The pane on the right previews the selected row.

```text
❯ git rebase onto                                          14 results · 2 ms
─────────────────────────────────────────────────────────────────────────────
▌ ❯ git rebase --onto main server client  bash  Git 8.6 │ Git › §8 Rewriting History
    …is ready and the server work is not…               │ › 8.6
  ▤ --onto: Moving a Range                       Git 8.6 │ --onto: Moving a Range
```

Three kinds of result:

| Icon | Kind | What it is |
| --- | --- | --- |
| ▤ | **topic** | One numbered subsection of a course (`git:7.3`), plus section openers, introductions, summaries and exercises |
| ❯ | **snippet** | One fenced code block (`git:7.3#2`) with the output printed under it and the sentence that introduced it |
| ◆ | **term** | A definition written as "**A term** is …" (`git:term:reflog`) |

How results are ranked:

- A full-text match over **title**, **headings**, **text** and **code**, weighted in that order. The last word is a prefix, so `usest` finds `useState` as you type.
- A title that equals your query, starts with it, or contains every word moves up. Definitions rank above topics for "what is …" style queries; exercises and their solutions rank below everything else.
- Words the index has never seen are repaired against the vocabulary of titles (`rebsae` → `rebase`), and the header says so. If too few results match every word, partial matches are added and marked.
- Small filler words (`the`, `how`, `do`, `vs`, …) are ignored.

### Filters

Type them anywhere in the query; they combine.

| Filter | Meaning |
| --- | --- |
| `in:git` · `course:git` · `@git` | One course. A key, a name or an unambiguous prefix (`in:type` is TypeScript) |
| `kind:topic` · `kind:snippet` · `kind:term` | One kind of result (`kind:code`, `kind:def` also work) |
| `lang:bash` | Only snippets in one language |

**Ctrl+T** cycles the kind and **Ctrl+S** cycles the course; the chips at the top right show what is active. **Esc** clears the query, then the filters, then leaves.

### Start screen

With an empty query lore shows your **aliases** (most recently used first), what you **recently opened** and your **recent searches**. Enter on a search puts it back in the prompt.

## The reader

Enter opens a result in a scrolling reader. Topics render as markdown: headings, lists, tables, syntax-highlighted code, and the output the course printed under each block. Exercise solutions appear on a rail under a `▸ Solution` heading. The course's HTML callouts become bullet lists and its figures become a one-line note with the caption.

| Key | |
| --- | --- |
| **j k** · ↑ ↓ | scroll a line |
| **Space** · **b** · PgDn · PgUp | a page; **d** · **u** a half page |
| **g** · **G** | top · bottom |
| **n** · **p** | next · previous topic in the course |
| **Tab** · Shift+Tab | select the next · previous code block (marked with an accent rail) |
| **y** | copy the selected code block, or the whole topic when none is selected |
| **a** | alias the selected code block, or the topic |
| **/** | find in the page; **Enter** keeps it, **]** and **[** jump between matches |
| **t** | contents of the whole course: every section and topic, jump anywhere |
| **P** | print the selection to the terminal and quit |
| **q** · Esc · Backspace | back |

Opening a snippet from the results scrolls to its block with it already selected; opening a definition highlights the term in its topic.

## Aliases

An alias is a short name for something you look up again and again. It can point at a topic, a single code block, a definition, or hold text of your own.

- **Create:** **Ctrl+A** on a result, **a** in the reader, or `lore alias add NAME QUERY|ID` / `lore alias add NAME --text "…"`. If the name is taken, lore says what it points at and asks for Enter a second time before replacing it.
- **Recall:** `lore @name` prints it (a snippet prints its code, a topic goes through your pager); `-y` also copies, `-o` opens the reader, `--code` prints only the code. In the interface, type `@` and part of the name.
- **Manage:** `lore alias ls`, `mv`, `note`, `rm`; **Ctrl+X** twice on the start screen deletes the selected alias.

Aliases live in `aliases.json` and are not part of the index, so `lore index` never touches them. Each remembers its course, its title slug and, for a snippet, a fingerprint of the code. If a course is renumbered or rewritten, lore finds the target again and `lore alias ls` marks it *(moved)*; if it is gone, the row says so.

## Copying and printing

**Ctrl+Y** (search) and **y** (reader) copy: a snippet's code, a definition's sentence, or a topic's markdown. lore uses `pbcopy`, `wl-copy`, `xclip`, `xsel` or `clip.exe`, and falls back to the OSC 52 escape, which most terminals honour, including over SSH and tmux.

**Ctrl+O** and **P** print the selection to the terminal and quit. When stdout is a pipe, `--pick` draws the interface on the terminal and prints only the choice:

```sh
lore --pick git rebase | pbcopy
```

## Command line

```sh
lore                          # interface
lore QUERY …                  # interface, already searching   (-c COURSE, -k KIND)
lore @NAME                    # recall an alias                (-y copy, -o reader, --code, --raw)
lore search QUERY …           # list matches                   (-n N, -c, -k, --json)
lore get TARGET               # print a topic or snippet       (--code, --raw, -y)
lore alias add|ls|mv|note|rm …
lore index [--source DIR]     # (re)build the index
lore courses | info | config
```

`TARGET` is `@alias`, an item id (`git:7.3`, `git:7.3#2`) or a query (the best match). Output to a pipe is plain: a snippet prints just its code, a topic prints markdown, and nothing contains colour codes.

## How the index is built

`lore index` reads each course's assembled source (`<course>.md`): a `===META===` header, an `===INTRO===`, `===SECTION: …===` blocks of `## N.M` subsections and a `===CONCLUSION===`. Every subsection becomes a topic, every fenced block a snippet, every "**A term** is …" sentence a definition. HTML in the sources is rewritten to markdown: two-column grids and "title over text" cards become `- **label** — text` bullets, tables become markdown tables, `<figure>` becomes a note, `<details>` becomes a solution rail, and scripts and widgets are dropped. Code fences are never touched.

The result is one SQLite file with an FTS5 index (porter stemming), a trigram index of titles for substring matches, and the vocabulary used for typo repair. Bodies are stored compressed. For the 20 current courses: about 5,700 topics, 11,000 snippets, 1,900 definitions and 41 MB, built in about three seconds.
