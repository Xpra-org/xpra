#!/usr/bin/env python3
"""Re-align markdown tables in place, so hand-edited cells stay tidy.

    python3 retable.py docs/Usage/Clients.md              # every "| Feature " table
    python3 retable.py docs/Usage/Clients.md --start 30   # only the table at that line
    python3 retable.py docs/Usage/Clients.md --check      # report only, no write

Every row is padded to the widest cell in its column and the separator row is
regenerated, keeping whatever `:` alignment markers it already carried. Rows
whose column count differs from the header are an error: that is almost always a
`|` typed into a cell without escaping it.
"""

import argparse
import sys


def is_separator(line: str) -> bool:
    """A `|---|:--:|` row: what tells a header apart from a body row that happens to match the prefix."""
    return line.startswith("|") and set(line) <= set("|-: ") and "-" in line


def find_tables(lines: list[str], start: int | None, prefix: str) -> list[tuple[int, int]]:
    if start is None:
        # a body row can start with the prefix too ("| Client tray / menu"), and taking one for a
        # header eats the row below it as the new separator - so require the separator to be there
        starts = [i for i, line in enumerate(lines)
                  if line.startswith(prefix) and i + 1 < len(lines) and is_separator(lines[i + 1])]
        if not starts:
            sys.exit(f"no table header starting with {prefix!r}")
    else:
        starts = [start]
    tables = []
    for begin in starts:
        end = begin
        while end < len(lines) and lines[end].startswith("|"):
            end += 1
        if end - begin < 3:
            sys.exit(f"line {begin + 1} does not start a table with a body")
        tables.append((begin, end))
    return tables


def separator(cells: list[str], widths: list[int]) -> str:
    """Regenerate the separator row, preserving its `:` alignment markers."""
    out = []
    for cell, width in zip(cells, widths):
        left, right = cell.startswith(":"), cell.endswith(":")
        dashes = "-" * (width + 2 - left - right)
        out.append(":" * left + dashes + ":" * right)
    return "|" + "|".join(out) + "|"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path")
    parser.add_argument("--start", type=int, help="1-based line number of the header row")
    parser.add_argument("--prefix", default="| Feature ", help="header row prefix used to find the table")
    parser.add_argument("--check", action="store_true", help="validate and report, do not write")
    args = parser.parse_args()

    with open(args.path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    tables = find_tables(lines, args.start - 1 if args.start else None, args.prefix)
    stale = []
    # last table first, so rewriting one does not move the line numbers of the next
    for start, end in reversed(tables):
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[start:end]]
        header, sep, *body = rows

        for offset, row in enumerate(body):
            if len(row) != len(header):
                sys.exit(f"{args.path}:{start + 3 + offset}: {len(row)} cells, header has {len(header)} "
                         f"(an unescaped '|' in a cell?): {row[0]!r}")

        # Cell widths are counted in characters: the emoji used here (✅ ⚠️ ◐) are
        # one character each but render wider, so perfect visual alignment is not on
        # offer. Consistency is what keeps the diffs readable.
        widths = [max(len(row[col]) for row in rows[:1] + body) for col in range(len(header))]

        out = ["| " + " | ".join(cell.ljust(w) for cell, w in zip(header, widths)) + " |",
               separator(sep, widths)]
        out += ["| " + " | ".join(cell.ljust(w) for cell, w in zip(row, widths)) + " |" for row in body]

        if out == lines[start:end]:
            print(f"{args.path}: table at line {start + 1} already aligned ({len(body)} rows)")
            continue
        stale.append(start + 1)
        if not args.check:
            lines[start:end] = out
            print(f"{args.path}: re-aligned {len(body)} rows x {len(header)} columns at line {start + 1}")

    if args.check:
        if stale:
            sys.exit(f"{args.path}: tables needing re-alignment at line(s) {', '.join(map(str, sorted(stale)))}")
        return
    if stale:
        with open(args.path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


if __name__ == "__main__":
    main()
