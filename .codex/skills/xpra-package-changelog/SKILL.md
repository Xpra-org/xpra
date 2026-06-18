---
name: xpra-package-changelog
description: Sync Xpra Markdown release notes from docs/CHANGELOG.md into packaging/rpm/xpra.spec and packaging/debian/xpra/changelog. Use when asked to copy a release entry into RPM or Debian package changelog formats, strip Markdown URLs while preserving descriptions, update package changelog dates, or replace TODO placeholders for an Xpra release.
---

# Xpra Package Changelog

Use this skill to mirror one Xpra release entry from `docs/CHANGELOG.md` into the RPM spec `%changelog` and Debian `debian/changelog` format.

## Workflow

1. Read the latest or requested release section from `docs/CHANGELOG.md`.
2. Strip Markdown links by replacing `[description](url)` with `description`.
3. Preserve release-note descriptions and inline punctuation. Do not include commit URLs.
4. Convert Markdown category bullets to package changelog headings:
   - RPM: `- Category:` and continuation lines indented with three spaces.
   - Debian: `  * Category:` and continuation lines indented with four spaces.
5. Update the release datetime:
   - RPM header uses local date format like `* Thu Jun 18 2026 Antoine Martin <antoine@xpra.org> 5.1.6-10`.
   - Debian trailer uses RFC 2822 format like ` -- Antoine Martin <antoine@xpra.org>  Thu, 18 Jun 2026 19:16:58 +0700`.
6. Replace only the matching top release block or TODO placeholder. Leave older releases and unrelated worktree changes untouched.
7. Validate with:
   - `dpkg-parsechangelog -l packaging/debian/xpra/changelog`
   - `rpmspec --parse packaging/rpm/xpra.spec` when available. A missing local source archive warning is acceptable if the command exits 0.
   - `git diff --check -- packaging/rpm/xpra.spec packaging/debian/xpra/changelog`

## Helper Script

Use `scripts/format_release_notes.py` to convert a Markdown release entry into package-ready text:

```bash
python3 ~/.codex/skills/xpra-package-changelog/scripts/format_release_notes.py \
  docs/CHANGELOG.md --version 5.1.6 --format rpm

python3 ~/.codex/skills/xpra-package-changelog/scripts/format_release_notes.py \
  docs/CHANGELOG.md --version 5.1.6 --format debian
```

If `--version` is omitted, the script uses the first release section in `docs/CHANGELOG.md`.
