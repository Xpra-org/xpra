#!/usr/bin/env python3
"""Remove specific names from import/cimport statements in Cython files.

Reads a TSV (path<TAB>lineno<TAB>name, as emitted by
`TSV=1 find_unused_cimports.py`) and rewrites each file, removing only the
named imports. Handles single-line and multi-line parenthesised import
blocks, cleans up commas, and drops now-empty lines / whole statements.
Everything else is preserved verbatim.

Usage:
    TSV=1 python3 find_unused_cimports.py xpra > candidates.tsv
    # review candidates.tsv, delete any lines you are unsure about, then:
    python3 rewrite.py candidates.tsv

ALWAYS transpile-verify afterwards (see SKILL.md) — this script trusts the
TSV; it does not re-check that a name is genuinely unused.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_unused_cimports import parse_imports, bound_names  # noqa: E402


def load_candidates(tsv):
    by_file = {}
    with open(tsv) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            path, lineno, name = line.split("\t")
            by_file.setdefault(path, set()).add(name)
    return by_file


def remove_name_from_line(line, name):
    """Try to remove `name` (as a whole word) plus one adjacent comma.
    Returns (new_line, changed)."""
    # trailing comma form:  NAME ,
    new = re.sub(r"\b" + re.escape(name) + r"\b\s*,\s*", "", line, count=1)
    if new != line:
        return new, True
    # leading comma form:  , NAME   (name was last in list)
    new = re.sub(r",\s*\b" + re.escape(name) + r"\b", "", line, count=1)
    if new != line:
        return new, True
    # bare form (single name, possibly inside parens)
    new = re.sub(r"\b" + re.escape(name) + r"\b", "", line, count=1)
    if new != line:
        return new, True
    return line, False


def rewrite_file(path, remove):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    delete_lines = set()
    modified = {}  # absolute line index -> modified text

    for start, buf in parse_imports(lines):
        nlines = buf.count("\n") + 1
        stmt_indices = list(range(start, start + nlines))
        names = [b for b, _t in bound_names(buf)]
        to_remove_here = [n for n in names if n in remove]
        if not to_remove_here:
            continue
        remaining = [n for n in names if n not in remove]
        if not remaining:
            # drop the entire statement
            delete_lines.update(stmt_indices)
            continue
        # per-line removal
        work = {idx: lines[idx] for idx in stmt_indices}
        for name in to_remove_here:
            for idx in stmt_indices:
                text = work[idx]
                if re.search(r"\b" + re.escape(name) + r"\b", text):
                    new, changed = remove_name_from_line(text, name)
                    if changed:
                        work[idx] = new
                        break
        # finalise: rstrip trailing whitespace, drop blank continuation lines
        first = stmt_indices[0]
        for idx in stmt_indices:
            text = work[idx].rstrip()
            if idx != first and text.strip() == "":
                delete_lines.add(idx)
            else:
                modified[idx] = text

    if not delete_lines and not modified:
        return False

    out = []
    for idx, line in enumerate(lines):
        if idx in delete_lines:
            continue
        out.append(modified.get(idx, line))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return True


def main():
    tsv = sys.argv[1]
    by_file = load_candidates(tsv)
    for path in sorted(by_file):
        changed = rewrite_file(path, by_file[path])
        print(f"{'CHANGED' if changed else 'nochange'}  {path}  (-{len(by_file[path])})")


if __name__ == "__main__":
    main()
