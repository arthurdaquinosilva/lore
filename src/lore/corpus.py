"""Read the courses' assembled markdown sources into entries: topics, snippets and terms."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from lore.htmlclean import FENCE, clean

OUTPUT_LANGS = {"text", "txt", "console", "output"}
SECTION = re.compile(r"^===SECTION:\s*(.+?)\s*===\s*$")
NUMBERED = re.compile(r"^(\d+(?:\.\d+)+)\s+(.*)$")


@dataclass
class Entry:
    id: str
    course: str
    kind: str  # topic | guide | exercise | summary
    section_no: int  # 0 for the introduction, N+1 for the conclusion
    section: str
    number: str
    title: str
    body: str  # cleaned markdown, without the heading line
    seq: int = 0
    slug: str = ""
    snippets: list["Snippet"] = field(default_factory=list)
    terms: list["Term"] = field(default_factory=list)


@dataclass
class Snippet:
    id: str
    parent: str
    course: str
    lang: str
    code: str
    output: str
    caption: str
    sig: str
    index: int


@dataclass
class Term:
    id: str
    parent: str
    course: str
    name: str
    definition: str


@dataclass
class Course:
    key: str
    title: str
    brand: str
    entries: list[Entry] = field(default_factory=list)


def slugify(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or "x"


def _split_blocks(text: str) -> Iterator[tuple[str, str, str]]:
    """Yield ('prose'|'code', lang, text) for a cleaned markdown body."""
    prose: list[str] = []
    code: list[str] = []
    fence: tuple[str, int, str] | None = None
    for line in text.split("\n"):
        fm = FENCE.match(line)
        if fence is None:
            if fm:
                if "".join(prose).strip():
                    yield "prose", "", "\n".join(prose)
                prose = []
                fence = (fm.group(2)[0], len(fm.group(2)), fm.group(3))
                code = []
            else:
                prose.append(line)
        else:
            if fm and fm.group(2)[0] == fence[0] and len(fm.group(2)) >= fence[1] and not fm.group(3):
                yield "code", fence[2], "\n".join(code)
                fence = None
            else:
                code.append(line)
    if fence is not None:
        yield "code", fence[2], "\n".join(code)
    elif "".join(prose).strip():
        yield "prose", "", "\n".join(prose)


def _flat_md(s: str) -> str:
    s = re.sub(r"^(#{1,6}|>|[-*+]|\d+\.)\s+", "", s.strip())
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return s.replace("*", "").strip()


def _caption(prose: str) -> str:
    """What introduces a code block: its paragraph, plus the sentence before when that is only `Verify:`."""
    paras = [p for p in re.split(r"\n\s*\n", prose) if p.strip() and not p.strip().startswith(":::") and set(p.strip()) - set("-*_ ")]
    if not paras:
        return ""
    text = " ".join(_flat_md(ln) for ln in paras[-1].split("\n") if ln.strip())
    if len(text) < 40 and len(paras) > 1:
        prev = " ".join(_flat_md(ln) for ln in paras[-2].split("\n") if ln.strip())
        sentences = re.split(r"(?<=[.!?])\s+", prev)
        text = (sentences[-1] + " " + text).strip()
    if len(text) > 220:
        sentences = re.split(r"(?<=[.!?:])\s+", text)
        out = ""
        for sent in reversed(sentences):
            if len(out) + len(sent) > 220:
                break
            out = sent + " " + out
        text = out.strip() or text[:217].rstrip() + "…"
    return text


@dataclass
class Block:
    kind: str  # prose | snippet | output | plain
    text: str
    lang: str = ""
    index: int = 0  # 1-based position among the entry's snippets


def classify(body: str) -> list[Block]:
    """Split a body into prose, snippets, the output printed under a snippet, and plain text blocks.

    The snippet numbering here is the one in the index (`topic-id#N`), so the renderer and the indexer agree."""
    raw = list(_split_blocks(body))
    out: list[Block] = []
    n = 0
    i = 0
    while i < len(raw):
        kind, lang, text = raw[i]
        i += 1
        if kind == "prose":
            out.append(Block("prose", text))
            continue
        lang_l = lang.lower()
        is_output = lang_l in OUTPUT_LANGS or lang_l.startswith("output")
        if is_output:
            shown = lang_l.split("-", 1)[1] if lang_l.startswith("output-") else ""
            out.append(Block("output" if out and out[-1].kind == "snippet" else "plain", text.strip("\n"), shown))
            continue
        if not text.strip() or len(text.strip()) < 6:
            out.append(Block("plain", text.strip("\n"), lang_l))
            continue
        n += 1
        out.append(Block("snippet", text.strip("\n"), lang_l or "text", n))
    return out


def extract_snippets(entry: Entry) -> list[Snippet]:
    found: list[Snippet] = []
    blocks = classify(entry.body)
    last_prose = ""
    for j, b in enumerate(blocks):
        if b.kind == "prose":
            last_prose = b.text
        elif b.kind == "snippet":
            output = blocks[j + 1].text if j + 1 < len(blocks) and blocks[j + 1].kind == "output" else ""
            sig = hashlib.sha1(b.text.strip()[:400].encode()).hexdigest()[:12]
            found.append(Snippet(f"{entry.id}#{b.index}", entry.id, entry.course, b.lang, b.text, output, _caption(last_prose), sig, b.index))
    return found


_TERM = re.compile(r"\*\*([A-Za-z][^*\n]{1,60}?)\*\*[,]?\s+(?:is|are|means|refers to|describes|names)\s")


def extract_terms(entry: Entry) -> list[Term]:
    found: dict[str, Term] = {}
    for kind, _lang, text in _split_blocks(entry.body):
        if kind != "prose":
            continue
        for para in re.split(r"\n\s*\n", text):
            if para.lstrip().startswith(("|", ":::", "#", ">")):
                continue
            flat = " ".join(para.split())
            for m in _TERM.finditer(flat):
                name = re.sub(r"^(?:a|an|the)\s+", "", m.group(1).strip(" :,."), flags=re.I)
                if not (2 <= len(name) <= 48) or len(name.split()) > 6:
                    continue
                if name.lower().startswith(("the ", "this ", "that ", "it ", "what ", "why ", "how ", "step ", "note")):
                    continue
                start = flat.rfind(". ", 0, m.start())
                start = 0 if start < 0 else start + 2
                end = flat.find(". ", m.end())
                sentence = flat[start: end + 1 if end >= 0 else len(flat)]
                if len(sentence) > 420:
                    sentence = sentence[:417].rstrip() + "…"
                key = name.lower()
                if key not in found and len(sentence) >= 30:
                    found[key] = Term(f"{entry.course}:term:{slugify(name)}", entry.id, entry.course, name, sentence)
    return list(found.values())


def parse_course(path: Path) -> Course:
    key = path.stem
    raw = path.read_text(encoding="utf-8")
    parts = _split_top(raw)
    meta = _meta(parts.get("meta", ""))
    course = Course(key, meta.get("title", key), meta.get("brand", meta.get("title", key)))
    seen: set[str] = set()
    seq = 0

    def add(kind: str, section_no: int, section: str, number: str, title: str, body: str, slug_hint: str = "") -> None:
        nonlocal seq
        body = clean(body)
        if not body.strip() and kind != "topic":
            return
        base = f"{key}:{number}" if number else f"{key}:{slug_hint or slugify(title)}"
        eid, n = base, 2
        while eid in seen:
            eid, n = f"{base}-{n}", n + 1
        seen.add(eid)
        seq += 1
        entry = Entry(eid, key, kind, section_no, section, number, title, body, seq, slugify(title))
        entry.snippets = extract_snippets(entry)
        entry.terms = extract_terms(entry)
        course.entries.append(entry)

    if "intro" in parts:
        _subsections(parts["intro"], "guide", 0, "Introduction", add, key, skip_title=True)
    for no, (title, text) in enumerate(parts.get("sections", []), start=1):
        _subsections(text, "topic", no, title, add, key)
    if "conclusion" in parts:
        _subsections(parts["conclusion"], "guide", len(parts.get("sections", [])) + 1, "Conclusion", add, key, skip_title=True)
    return course


def _meta(text: str) -> dict[str, str]:
    out = {}
    for line in text.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _split_top(raw: str) -> dict:
    """Split the assembled source on its ===META===/===INTRO===/===SECTION: …=== markers (outside fences)."""
    parts: dict = {"sections": []}
    current: list[str] | None = None
    target = ""
    title = ""
    fence: tuple[str, int] | None = None

    def close() -> None:
        if current is None:
            return
        text = "\n".join(current)
        if target == "section":
            parts["sections"].append((title, text))
        elif target:
            parts[target] = text

    for line in raw.split("\n"):
        fm = FENCE.match(line)
        if fence:
            if fm and fm.group(2)[0] == fence[0] and len(fm.group(2)) >= fence[1] and not fm.group(3):
                fence = None
            if current is not None:
                current.append(line)
            continue
        if fm:
            fence = (fm.group(2)[0], len(fm.group(2)))
            if current is not None:
                current.append(line)
            continue
        s = line.strip()
        if s in ("===META===", "===INTRO===", "===CONCLUSION==="):
            close()
            target = {"===META===": "meta", "===INTRO===": "intro", "===CONCLUSION===": "conclusion"}[s]
            current = []
            continue
        m = SECTION.match(line)
        if m:
            close()
            target, title, current = "section", m.group(1), []
            continue
        if current is not None:
            current.append(line)
    close()
    return parts


def _subsections(text: str, kind: str, section_no: int, section: str, add, key: str, skip_title: bool = False) -> None:
    """Split a section on its `## ` headings (outside fences) and add one entry per subsection."""
    chunks: list[tuple[str, list[str]]] = [("", [])]
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        fm = FENCE.match(line)
        if fence:
            if fm and fm.group(2)[0] == fence[0] and len(fm.group(2)) >= fence[1] and not fm.group(3):
                fence = None
            chunks[-1][1].append(line)
            continue
        if fm:
            fence = (fm.group(2)[0], len(fm.group(2)))
            chunks[-1][1].append(line)
            continue
        if line.startswith("## "):
            chunks.append((line[3:].strip(), []))
        else:
            chunks[-1][1].append(line)
    opener = "\n".join(chunks[0][1]).strip()
    if skip_title:
        opener = re.sub(r"^# .*\n?", "", opener).strip()
    if opener and kind == "topic":
        add("topic", section_no, section, f"{section_no}.0", section, opener)
    elif opener and kind == "guide" and len(opener) > 200:
        add("guide", section_no, section, "", section, opener, slug_hint=("intro" if section_no == 0 else "conclusion"))
    for heading, body_lines in chunks[1:]:
        heading = re.sub(r"`([^`]*)`", r"\1", heading) if False else heading
        body = "\n".join(body_lines).strip()
        m = NUMBERED.match(re.sub(r"\s+", " ", heading))
        if m:
            add("topic", section_no, section, m.group(1), m.group(2), body)
        elif heading.lower().startswith("exercises"):
            add("exercise", section_no, section, "", f"Exercises — {section}", body, slug_hint=f"s{section_no}-exercises")
        elif heading.lower().startswith("what this section established"):
            add("summary", section_no, section, "", f"What this section established — {section}", body,
                slug_hint=f"s{section_no}-summary")
        else:
            add("guide" if kind == "guide" else "topic", section_no, section, "", heading, body,
                slug_hint=f"s{section_no}-{slugify(heading)}")


def load_all(source: Path) -> list[Course]:
    return [parse_course(p) for p in sorted(source.glob("*.md")) if "===META===" in p.read_text(encoding="utf-8")[:200]]
