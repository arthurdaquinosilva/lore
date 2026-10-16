===META===
title: Mini Mastery
brand: Mini
storage: mini_mastery
===INTRO===
# Mini Mastery

> A tiny course used by the tests, shaped like the real ones: an introduction, two sections and a conclusion, with callout grids, a figure, a solution and a few code blocks.

---

## How to use this course

Read the sections in order. Every command here was run, and the output printed under each block is what it printed. This paragraph is long enough to be kept as its own entry in the index rather than being merged into the introduction above.

===SECTION: Undoing Things===
Undoing is the part of version control people learn last and need first.

## 1.1 Resetting the Branch

A **soft reset** is a reset that moves the branch pointer and leaves the index and the working tree alone. Use it to redo a commit.

<div style="display:grid;grid-template-columns:12rem 1fr;gap:.5rem .9rem;margin:1.2rem 0;align-items:start">
  <div style="font-weight:600">--soft</div><div>Move the branch only.</div>
  <div style="font-weight:600">--hard</div><div>Move the branch and overwrite your files.</div>
</div>

Undo the last commit but keep its changes staged:

```bash
git reset --soft HEAD~1
git status --short
```

```text
M  notes.txt
```

<figure id="fig-x" style="margin:1rem 0"><svg viewBox="0 0 10 10"><title>Three trees</title><rect width="5" height="5"/></svg><figcaption>The three trees a reset can move.</figcaption></figure>

## 1.2 Reverting a Commit

`git revert` makes a new commit that undoes an earlier one, which is why it is safe on shared branches.

```bash
git revert HEAD
```

## Exercises

**1.** Which reset mode leaves the working tree alone?

<details markdown="1"><summary>Solution</summary>

Both `--soft` and `--mixed`. Only `--hard` touches the working tree.

```bash
git reset --mixed HEAD~1
```
</details>

===SECTION: Searching Text===
## 2.1 Regular Expressions

A **regular expression** is a pattern that describes a set of strings. The `grep -E` flag turns on the extended syntax.

```bash
grep -rn "TODO" src/
```

```text
src/app.py:12:# TODO: handle errors
```

## 2.2 Windowing

Use a sliding window when a problem asks about contiguous ranges.

```python
def window(xs, k):
    return [sum(xs[i:i + k]) for i in range(len(xs) - k + 1)]
```

===CONCLUSION===
# Conclusion

You can now undo, revert and search. That is the whole of this small course, and the paragraph is intentionally longer than two hundred characters so that the conclusion is indexed as an entry of its own and can be found by a search for conclusion.
