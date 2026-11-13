#!/usr/bin/env python3
"""
Generate an SVG timeline of xpra release branches (one bar per branch, release -> EOL),
styled after Ubuntu's release-schedule chart.

Data sources:
 - EOL dates: the wiki's Versions.md ("Current releases" + "End-of-life releases" tables)
 - release dates: docs/CHANGELOG.md "## [X.Y] YYYY-MM-DD" headings, from master and the
   `vX.Y.x` branch (some branches, e.g. 3.1 / 5.1, are only in their own branch's changelog),
   then the `vX.Y` / `vX.Y.0` tag date as a last resort.

usage: versions_svg.py [--wiki ~/projects/xpra.wiki/Versions.md] [--repo ~/projects/xpra]
                       [--today YYYY-MM-DD] [--release X.Y=YYYY-MM-DD ...] > xpra-versions.svg
"""

import re
import sys
import argparse
import calendar
import subprocess
from datetime import date
from pathlib import Path

HEADING_RE = re.compile(r"^## \[(\d+\.\d+)(?:\.0)?\] (\d{4}-\d{2}-\d{2})", re.M)
VERSION_RE = re.compile(r"v(\d+\.\d+)")


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def parse_eol(text: str) -> date | None:
    """ '2017-01' -> 2017-01-31, '2020' / '~ 2030' -> year end, 'Q1 2027' -> quarter end """
    text = text.strip()
    if m := re.search(r"(\d{4})-(\d{2})", text):
        return month_end(int(m[1]), int(m[2]))
    if m := re.search(r"Q([1-4])\s*(\d{4})", text):
        return month_end(int(m[2]), int(m[1]) * 3)
    if m := re.search(r"(\d{4})", text):
        return date(int(m[1]), 12, 31)
    return None   # "To be confirmed"


def table_rows(md: str, header: str):
    """ yield the cells of each row of the first markdown table after `header` """
    section = md.split(header, 1)[1]
    started = False
    for line in section.splitlines():
        if line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells[0] in ("Version", "---") or set(cells[0]) <= {"-", " "}:
                continue
            yield cells
        elif started:
            return


def load_branches(wiki: Path):
    md = wiki.read_text()
    branches = {}       # "X.Y" -> (label, eol, lts)
    for cells in table_rows(md, "## End-of-life releases"):
        version, eol = cells[0], cells[1]
        m = VERSION_RE.search(version)
        if m:
            branches[m[1]] = (version, parse_eol(eol), "LTS" in version)
    for cells in table_rows(md, "## Current releases"):
        # | [v5.1.x](url) | LTS+1 | Q1 2027 |
        name, status, eol = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", cells[0]), cells[1], cells[2]
        m = re.search(r"v(\d+)(?:\.(\d+))?", name)    # "v5.1.x" or "v7.x" (-> 7.0)
        end = parse_eol(eol)
        if not m or not end:
            continue    # master / "To be confirmed"
        ver = f"{m[1]}.{m[2] or 0}"
        lts_m = re.search(r"LTS\S*", status)     # "LTS+1", "new LTS - release planned ..."
        lts = bool(lts_m)
        label = f"{name} {lts_m[0]}" if lts_m else name
        branches[ver] = (label, end, lts)
    return branches


def git(repo: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def release_dates(repo: Path, versions) -> dict[str, date]:
    dates = {v: date.fromisoformat(d) for v, d in HEADING_RE.findall((repo / "docs/CHANGELOG.md").read_text())}
    for v in versions:
        if v in dates:
            continue
        major = v.split(".")[0]
        for ref in (f"origin/v{v}.x", f"v{v}.x", f"origin/v{major}.x", f"v{major}.x"):
            found = dict(HEADING_RE.findall(git(repo, "show", f"{ref}:docs/CHANGELOG.md")))
            if v in found:
                dates[v] = date.fromisoformat(found[v])
                break
        else:
            for tag in (f"v{v}", f"v{v}.0"):
                if d := git(repo, "log", "-1", "--format=%cs", tag).strip():
                    dates[v] = date.fromisoformat(d)
                    break
    return dates


def render(rows, today: date) -> str:
    first_year = min(r[1] for r in rows).year
    last_year = max(r[2] for r in rows).year + 1
    left, right, width = 110, 885, 900
    rh, gap = 22, 5
    h = len(rows) * (rh + gap)

    def x(d: date) -> float:
        t = d.year + (d.timetuple().tm_yday - 1) / 365.25
        return left + (t - first_year) / (last_year - first_year) * (right - left)

    out = [f'''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h + 80}" role="img" aria-label="Xpra Release History">
  <title>Xpra Release History</title>
  <style>
    text {{ font-family: sans-serif; fill: #333; }}
    .label {{ font-size: 12px; }}
    .tick {{ font-size: 11px; fill: #888; }}
    .grid {{ stroke: #e8e8e8; stroke-width: 1; }}
    .today {{ stroke: #cc4444; stroke-width: 1.5; stroke-dasharray: 4,3; }}
    .bar {{ rx: 2; ry: 2; }}
    .rel {{ fill: #0A2472; }}
    .lts {{ fill: #1E96FC; }}
    .ended {{ opacity: 0.45; }}
    .legend-icon {{ width: 14px; height: 14px; rx: 2; ry: 2; }}
  </style>
  <rect width="{width}" height="{h + 80}" fill="white"/>
  <g transform="translate(0, 10)">''']
    for yr in range(first_year + 1, last_year + 1):
        xx = x(date(yr, 1, 1))
        out.append(f'    <line class="grid" x1="{xx:.1f}" y1="0" x2="{xx:.1f}" y2="{h}"/>')
        out.append(f'    <text class="tick" x="{xx:.1f}" y="{h + 16}" text-anchor="middle">{yr}</text>')
    for i, (label, start, end, lts) in enumerate(rows):
        cls = ("lts" if lts else "rel") + (" ended" if end < today else "")
        x0, x1 = x(start), x(end)
        out.append(f'    <g transform="translate(0, {i * (rh + gap)})">')
        out.append(f'      <text class="label" x="{left - 8}" y="15" text-anchor="end">{label}</text>')
        out.append(f'      <rect class="bar {cls}" x="{x0:.1f}" y="0" width="{x1 - x0:.1f}" height="{rh}">'
                   f'<title>{label}: {start:%Y-%m} to {end:%Y-%m}</title></rect>')
        out.append('    </g>')
    if first_year <= today.year < last_year:
        tx = x(today)
        out.append(f'    <line class="today" x1="{tx:.1f}" y1="0" x2="{tx:.1f}" y2="{h}"/>')
    out.append(f'''    <g transform="translate({left + 1}, {h + 32})">
      <rect class="legend-icon rel" x="0" y="0"/><text class="label" x="18" y="11">Release</text>
      <rect class="legend-icon lts" x="110" y="0"/><text class="label" x="128" y="11">LTS release</text>
      <rect class="legend-icon rel ended" x="240" y="0"/><text class="label" x="258" y="11">End-of-life (faded)</text>
      <line class="today" x1="400" y1="0" x2="400" y2="14"/><text class="label" x="408" y="11">Today</text>
    </g>
  </g>
</svg>''')
    return "\n".join(out)


def main() -> int:
    home = Path.home() / "projects"
    p = argparse.ArgumentParser()
    p.add_argument("--wiki", type=Path, default=home / "xpra.wiki" / "Versions.md")
    p.add_argument("--repo", type=Path, default=home / "xpra")
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    p.add_argument("--release", action="append", default=[], metavar="X.Y=YYYY-MM-DD",
                   help="override / supply a release date")
    args = p.parse_args()

    branches = load_branches(args.wiki)
    dates = release_dates(args.repo, branches)
    for o in args.release:
        v, d = o.split("=")
        dates[v] = date.fromisoformat(d)
    rows = []
    for v, (label, eol, lts) in branches.items():
        if v not in dates:
            print(f"warning: no release date for {v}, skipped (use --release {v}=YYYY-MM-DD)", file=sys.stderr)
            continue
        print(f"{label:16} {dates[v]} -> {eol}", file=sys.stderr)
        rows.append((label, dates[v], eol, lts))
    rows.sort(key=lambda r: r[1], reverse=True)
    print(render(rows, args.today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
