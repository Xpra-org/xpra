---
name: xpra-package-changelog
description: Sync Xpra Markdown release notes from docs/CHANGELOG.md into packaging/rpm/xpra.spec and packaging/debian/xpra/changelog. Use when asked to copy a release entry into RPM or Debian package changelog formats, strip Markdown URLs while preserving descriptions, update release dates and package changelog datetimes, or replace TODO placeholders for an Xpra release.
---

# Xpra Package Changelog

Use this skill to mirror one Xpra release entry from `docs/CHANGELOG.md` into the RPM spec `%changelog` and Debian `debian/changelog` format, while also refreshing the release date or datetime in all affected files.

## Workflow

1. Read the latest or requested release section from `docs/CHANGELOG.md`.
2. Update the Markdown release header date in `docs/CHANGELOG.md` to the current local date in `YYYY-MM-DD` format.
3. Strip Markdown links by replacing `[description](url)` with `description`.
4. Preserve release-note descriptions and inline punctuation. Do not include commit URLs.
5. Convert Markdown category bullets to package changelog headings:
   - RPM: `- Category:` and continuation lines indented with three spaces.
   - Debian: `  * Category:` and continuation lines indented with four spaces.
6. Update the release datetime in every packaging file you touch:
   - Markdown header uses ISO local date like `## [6.5.1] 2026-06-28`.
   - RPM header uses local date format like `* Sun Jun 28 2026 Antoine Martin <antoine@xpra.org> 6.5.1-10`.
   - Debian trailer uses RFC 2822 format like ` -- Antoine Martin <antoine@xpra.org>  Sun, 28 Jun 2026 15:44:43 +0700`.
7. Replace only the matching top release block or TODO placeholder. Leave older releases and unrelated worktree changes untouched.
8. Validate with:
   - `dpkg-parsechangelog -l packaging/debian/xpra/changelog`
   - `rpmspec --parse packaging/rpm/xpra.spec` when available. A missing local source archive warning is acceptable if the command exits 0.
   - `git diff --check -- docs/CHANGELOG.md packaging/rpm/xpra.spec packaging/debian/xpra/changelog`

## Helper Script

Use `scripts/format_release_notes.py` to convert a Markdown release entry into package-ready text:

```bash
python3 ~/.codex/skills/xpra-package-changelog/scripts/format_release_notes.py   docs/CHANGELOG.md --version 5.1.6 --format rpm

python3 ~/.codex/skills/xpra-package-changelog/scripts/format_release_notes.py   docs/CHANGELOG.md --version 5.1.6 --format debian
```

If `--version` is omitted, the script uses the first release section in `docs/CHANGELOG.md`.
