#!/usr/bin/env python3
"""Re-align a markdown table in place, so hand-edited cells stay tidy.

    python3 retable.py docs/Usage/Clients.md              # the "| Feature " table
    python3 retable.py docs/Usage/Clients.md --start 30   # the table at that line
    python3 retable.py docs/Usage/Clients.md --check      # report only, no write

Every row is padded to the widest cell in its column and the separator row is
regenerated. Rows whose column count differs from the header are an error: that
is almost always a `|` typed into a cell without escaping it.
"""

import argparse
import sys


def find_table(lines: list[str], start: int | None, prefix: str) -> tuple[int, int]:
    if start is None:
        matches = [i for i, line in enumerate(lines) if line.startswith(prefix)]
        if not matches:
            sys.exit(f"no table header starting with {prefix!r}")
        if len(matches) > 1:
            sys.exit(f"{len(matches)} tables start with {prefix!r}: pass --start LINE (1-based)")
        start = matches[0]
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    if end - start < 3:
        sys.exit(f"line {start + 1} does not start a table with a body")
    return start, end


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path")
    parser.add_argument("--start", type=int, help="1-based line number of the header row")
    parser.add_argument("--prefix", default="| Feature ", help="header row prefix used to find the table")
    parser.add_argument("--check", action="store_true", help="validate and report, do not write")
    args = parser.parse_args()

    with open(args.path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    start, end = find_table(lines, args.start - 1 if args.start else None, args.prefix)
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[start:end]]
    header, _sep, *body = rows

    for offset, row in enumerate(body):
        if len(row) != len(header):
            sys.exit(f"{args.path}:{start + 2 + offset}: {len(row)} cells, header has {len(header)} "
                     f"(an unescaped '|' in a cell?): {row[0]!r}")

    # Cell widths are counted in characters: the emoji used here (✅ ⚠️ ◐) are
    # one character each but render wider, so perfect visual alignment is not on
    # offer. Consistency is what keeps the diffs readable.
    widths = [max(len(row[col]) for row in rows[:1] + body) for col in range(len(header))]

    out = ["| " + " | ".join(cell.ljust(w) for cell, w in zip(header, widths)) + " |",
           "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += ["| " + " | ".join(cell.ljust(w) for cell, w in zip(row, widths)) + " |" for row in body]

    if out == lines[start:end]:
        print(f"{args.path}: table at line {start + 1} already aligned ({len(body)} rows)")
        return
    if args.check:
        sys.exit(f"{args.path}: table at line {start + 1} needs re-aligning")
    lines[start:end] = out
    with open(args.path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{args.path}: re-aligned {len(body)} rows x {len(header)} columns at line {start + 1}")


if __name__ == "__main__":
    main()
