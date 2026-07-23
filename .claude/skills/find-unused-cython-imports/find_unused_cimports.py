#!/usr/bin/env python3
"""Methodically find unused imports/cimports in Cython .pyx/.pxd files.

Heuristic: parse every import/cimport statement (handling multi-line
parenthesised forms), collect the bound local names (respecting `as`
aliases), then check whether each bound name appears as a word token
anywhere else in the file. If not, it's a candidate unused import.

Usage:
    python3 find_unused_cimports.py [ROOT ...]     # default ROOT: xpra
    TSV=1 python3 find_unused_cimports.py xpra      # machine-readable: path<TAB>lineno<TAB>name

Two false-positive traps this handles (see SKILL.md):
  * `#` inside a string literal is NOT a comment (strip_comment).
  * a .pxd shares its namespace with the companion .pyx, so usage there counts.
Always confirm removals by transpiling with cython (see SKILL.md).
"""
import os
import re
import sys

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def strip_comment(line):
    """Return `line` truncated at the first `#` that is NOT inside a string
    literal. Keeps string contents (conservative: names inside strings still
    count as usage, which avoids false positives)."""
    quote = None
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in ("'", '"'):
                quote = c
            elif c == "#":
                return line[:i]
        i += 1
    return line


def parse_imports(lines):
    """Yield (lineno, bound_name, raw_statement_text) for each imported name."""
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        # Detect start of an import statement
        m = re.match(r"^(from\s+[.\w]+\s+)?(c?import)\b", stripped)
        if not m:
            i += 1
            continue
        start = i
        # Gather continuation lines: parentheses or trailing backslash
        buf = line
        # Count parens balance
        depth = buf.count("(") - buf.count(")")
        while (depth > 0 or buf.rstrip().endswith("\\")) and i + 1 < n:
            i += 1
            buf += "\n" + lines[i]
            depth = buf.count("(") - buf.count(")")
        yield start, buf
        i += 1


def bound_names(statement):
    """Given a full import statement, return list of (bound_name, imported_token)."""
    # Normalise
    s = statement
    # Remove line-continuation backslashes and parens
    s = s.replace("\\", " ")
    results = []

    # from X import/cimport ...
    m = re.match(r"^\s*from\s+([.\w]+)\s+(c?import)\s+(.*)$", s, re.S)
    if m:
        names_part = m.group(3)
        names_part = names_part.replace("(", " ").replace(")", " ")
        # split by comma
        for chunk in names_part.split(","):
            chunk = chunk.strip()
            if not chunk or chunk == "*":
                continue
            # handle "name as alias"
            am = re.match(r"^(\w+)\s+as\s+(\w+)$", chunk)
            if am:
                results.append((am.group(2), am.group(1)))
            else:
                nm = re.match(r"^(\w+)$", chunk)
                if nm:
                    results.append((nm.group(1), nm.group(1)))
        return results

    # plain: import X / cimport X  (possibly comma separated, with as)
    m = re.match(r"^\s*(c?import)\s+(.*)$", s, re.S)
    if m:
        names_part = m.group(2)
        for chunk in names_part.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            am = re.match(r"^([.\w]+)\s+as\s+(\w+)$", chunk)
            if am:
                results.append((am.group(2), am.group(2)))
            else:
                nm = re.match(r"^([.\w]+)$", chunk)
                if nm:
                    # bound name is the top-level package for dotted imports
                    top = nm.group(1).split(".")[0]
                    results.append((top, top))
        return results

    return results


def nonimport_tokens(path):
    """Return a dict of word -> count for all tokens NOT inside an import
    statement (multi-line aware), with # comments stripped."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    import_line_indices = set()
    for start, buf in parse_imports(lines):
        nlines = buf.count("\n") + 1
        for k in range(start, start + nlines):
            import_line_indices.add(k)
    usage = {}
    for idx, line in enumerate(lines):
        if idx in import_line_indices:
            continue
        code = strip_comment(line)
        for w in WORD.findall(code):
            usage[w] = usage.get(w, 0) + 1
    return usage


def analyse(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    lines = text.split("\n")

    # For a .pxd, its cimported names are shared with the companion .pyx
    # (same namespace). Count *non-import* usage there too, to avoid false
    # positives where the .pyx relies on the .pxd's cimport.
    extra_usage = {}
    if path.endswith(".pxd"):
        companion = path[:-4] + ".pyx"
        if os.path.isfile(companion):
            extra_usage = nonimport_tokens(companion)

    # Build a map of import statement line ranges so we can exclude them
    # when counting usages.
    import_line_indices = set()
    imports = []  # (lineno, bound, token, statement)
    for start, buf in parse_imports(lines):
        nlines = buf.count("\n") + 1
        for k in range(start, start + nlines):
            import_line_indices.add(k)
        for bound, token in bound_names(buf):
            imports.append((start, bound, token, buf.strip().split("\n")[0]))

    # Build usage count of each word outside import statements.
    usage = {}
    for idx, line in enumerate(lines):
        if idx in import_line_indices:
            continue
        code = strip_comment(line)
        for w in WORD.findall(code):
            usage[w] = usage.get(w, 0) + 1

    unused = []
    for lineno, bound, token, stmt in imports:
        if usage.get(bound, 0) == 0 and extra_usage.get(bound, 0) == 0:
            unused.append((lineno + 1, bound, stmt))
    return unused


def main():
    roots = sys.argv[1:] or ["xpra"]
    files = []
    for root in roots:
        if os.path.isfile(root):
            files.append(root)
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith((".pyx", ".pxd")):
                    files.append(os.path.join(dirpath, fn))
    files.sort()
    total = 0
    for path in files:
        try:
            unused = analyse(path)
        except Exception as e:
            print(f"ERROR {path}: {e}", file=sys.stderr)
            continue
        if unused:
            if os.environ.get("TSV"):
                for lineno, bound, stmt in unused:
                    print(f"{path}\t{lineno}\t{bound}")
            else:
                print(f"\n### {path}")
                for lineno, bound, stmt in unused:
                    print(f"  L{lineno}: {bound!r}   [{stmt}]")
            total += len(unused)
    if not os.environ.get("TSV"):
        print(f"\n=== {total} candidate unused imports across {len(files)} files ===")


if __name__ == "__main__":
    main()
