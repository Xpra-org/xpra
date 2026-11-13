---
name: versions-timeline-svg
description: Generate an SVG timeline chart of xpra release branches (release date -> end-of-life, LTS highlighted, today marker), in the style of Ubuntu's release-schedule graph, from the wiki's Versions page. Use when asked to graph, chart or plot xpra versions / releases / EOL dates / support periods, or to refresh that SVG.
---

# versions-timeline-svg

Draws one horizontal bar per release branch, newest at the top: dark blue = regular release,
light blue = LTS, faded = already end-of-life, dashed red line = today, year gridlines along the x axis.
The look copies Ubuntu's release-schedule SVG (white background, sans-serif 12px labels, 2px rounded bars,
`#0A2472` / `#1E96FC`); each bar has a `<title>` tooltip with its dates.

## Steps

```sh
cd ~/projects/xpra.wiki && git pull -q            # the local wiki clone is often behind
cd ~/projects/xpra
python3 .claude/skills/versions-timeline-svg/versions_svg.py > <scratchpad>/xpra-versions.svg
```

The script prints each bar's `label start -> eol` on stderr: check them.
Then render a preview to look at it (`rsvg-convert` is not installed, use ImageMagick):
`magick xpra-versions.svg xpra-versions.png`, and Read the PNG.

Options: `--wiki PATH` (default `~/projects/xpra.wiki/Versions.md`), `--repo PATH`,
`--today YYYY-MM-DD`, `--release X.Y=YYYY-MM-DD` (repeatable: supply or override a release date).

## Where the data comes from

- **EOL dates**: the wiki `Versions.md`, both the "End-of-life releases" table (`2017-01` -> last day of the month,
  a bare year like `2020` -> Dec 31) and the "Current releases" table (`Q1 2027` -> end of quarter, `~ 2030` -> Dec 31,
  `To be confirmed` / `master` -> skipped). `LTS` in the version or status column makes it an LTS bar.
  `v7.x` style names map to `7.0`.
- **Release dates** (the wiki doesn't have them): `## [X.Y] YYYY-MM-DD` headings in `docs/CHANGELOG.md` on master,
  then that heading in the `vX.Y.x` branch's changelog, then the `vX.Y` / `vX.Y.0` tag date.
  - Tags older than ~3.1 don't exist (svn-era history), so those come from the master changelog.
  - 3.1 is not in any changelog heading: it falls back to the `v3.1` tag (2021-06-12).
  - 5.1 is only in the `v5.1.x` branch changelog (2025-04-09).
- A branch missing from the wiki tables gets no bar: fix the wiki, not the script.
  Check that every LTS lineage is complete: 3.0 -> 3.1 and 5.0 -> 5.1 are separate LTS branches,
  the older one's EOL being when its successor took over (v5.0.x LTS: 2025-04, when 5.1 was released;
  it was missing from the wiki EOL table until 2026-11).

## Things to point out to the user

- Any date that was inferred: approximate EOLs ("2020", "Q1 2027", "~ 2030") and tag-date fallbacks.
- Inconsistencies between the wiki and the changelog, e.g. the wiki saying a release is "planned"
  while `docs/CHANGELOG.md` already has a dated heading for it.
- Branches skipped for lack of a release date (stderr warning).
