---
name: find-unused-cython-imports
description: Find and remove unused imports/cimports in xpra's Cython .pyx/.pxd files, which ruff and flake8 do not check. Use when asked to find or remove unused imports (especially in .pyx/.pxd/Cython files), clean up imports codebase-wide, or "do more like <commit that removed unused imports>". For pure-Python .py files, use `ruff check --select F401` instead.
---

# find-unused-cython-imports

`ruff`/`flake8` only lint `.py` files, so unused `import`/`cimport` statements in xpra's ~117 `.pyx` and ~32 `.pxd` Cython files go undetected. This skill finds them with a bundled scanner and — crucially — **verifies every removal by transpiling with `cython`**, which does full name resolution without needing any native libraries.

Bundled scripts (in this skill's directory):
- `find_unused_cimports.py` — detector (heuristic).
- `rewrite.py` — removes named imports from statements (single-line + multi-line paren blocks), then you re-verify.

## First: the two traps that cause false positives

A naive "does the name appear elsewhere?" check is wrong in two ways here. The bundled scanner already handles both — do not reimplement the check without them:

1. **`#` inside a string literal is not a comment.** Log lines like
   `log("resource %#x freed", <uintptr_t> ptr)` contain `#` inside `"%#x"`.
   Splitting the line on `#` hides the real `<uintptr_t>` usage after it, so the
   type looks unused when it is not. Truncate a line at `#` only when the `#` is
   outside quotes.
2. **A `.pxd` shares its namespace with the companion `.pyx`.** A name cimported
   in `foo.pxd` may be used only in `foo.pyx` (which relies on it instead of
   self-importing). Removing it from the `.pxd` breaks the build. Count
   non-import usage in the companion `.pyx` too, and also check that no other
   module does `from xpra.<this_module> cimport <name>` (re-export).

## The verification oracle

`cython` transpilation (`.pyx` → `.c`) resolves every C-level name and **errors
on a wrongly-removed `cimport`** (`'<name>' is not a type identifier`,
`undeclared name`, …). It does **not** need the native libs, so it works even for
nvenc / amf / vpx / avif / wayland files:

```sh
cython -X language_level=3 -I . <file>.pyx -o /tmp/out.c
```

Transpilation does **not** validate runtime Python `import`s — an undefined
Python name only raises `NameError` at runtime, not at transpile time. So Python
imports are covered by the scanner's static token scan, not by transpilation.

## Workflow

Run from the repo root.

### 1. Baseline — confirm each candidate file transpiles cleanly *before* editing

```sh
SKILL=.claude/skills/find-unused-cython-imports
TSV=1 python3 $SKILL/find_unused_cimports.py xpra > /tmp/candidates.tsv
cut -f1 /tmp/candidates.tsv | sort -u | while read f; do
  [ "${f##*.}" = pyx ] || continue
  cython -X language_level=3 -I . "$f" -o /tmp/_b.c >/dev/null 2>&1 || echo "PRE-FAIL $f"
done
```
Any file that already fails to transpile can't be used as an oracle — set it aside and inspect by hand.

### 2. Review the candidate list

Skim `/tmp/candidates.tsv`. Delete any rows you want to keep (e.g. an import
kept deliberately for a side effect, or one you're unsure about). The scanner is
a heuristic; you are the gate.

### 3. Remove

```sh
python3 $SKILL/rewrite.py /tmp/candidates.tsv
```

### 4. Verify — transpile every edited `.pyx`, and every consumer of an edited `.pxd`

```sh
for f in $(git diff --name-only -- '*.pyx'); do
  cython -X language_level=3 -I . "$f" -o /tmp/_v.c >/tmp/err.txt 2>&1 \
    || { echo "FAIL $f"; tail -5 /tmp/err.txt; }
done
```
A `.pxd` can't be transpiled alone: transpile the `.pyx` files in its module
(its companion `.pyx` and any file that `cimport`s from it). If a file fails,
the removed name was actually used — `git checkout -- <file>` it and drop that
row.

Independently confirm the Python-level imports (not covered by transpile): every
removed name should have **zero** non-import, comment-stripped occurrences in its
edited file. Re-running `find_unused_cimports.py` on the edited tree should
report `0 candidate unused imports` (idempotent).

### 5. Tidy & commit

Whole-line removals can leave a doubled blank line; collapse any blank run your
edit newly created (vs `HEAD`) down to one. Then confirm scope and commit
straight to master (this repo's convention — no throw-away branch):

```sh
ruff check ./xpra --ignore E902 --ignore E501       # .py side unaffected
git diff --name-only | grep -v '\.pyx$\|\.pxd$'      # expect: nothing else
git add -- '*.pyx' '*.pxd' && git commit
```

## Notes

- The scanner keys "used" on the bound local name (respects `import x as y`).
- Multi-line parenthesised `cimport (...)` blocks and `\`-continued lines are
  parsed as one statement.
- Names appearing only inside a `#`-comment or a string literal count as *not*
  used for a comment but *as* used for a string (conservative — avoids removing
  something a string references). A name used only in a commented-out line is
  therefore reported as unused; that's usually correct (the code is dead), but
  eyeball it.
