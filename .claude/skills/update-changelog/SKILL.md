---
name: update-changelog
description: Update docs/CHANGELOG.md with every commit since the last release notes update, one user-facing line per change linking to the GitHub commit. Use when the user asks to "update the changelog", "update the release notes", or add recent commits to docs/CHANGELOG.md.
---

# update-changelog

Adds the commits made since the last changelog update to the top (unreleased) section of `docs/CHANGELOG.md`.
Readers use these notes to decide whether a release is relevant to them.

## Steps

### 1. Find the commits to add

```sh
git log --oneline -5 -- docs/CHANGELOG.md          # last "update the release notes" commit
git log --oneline <last-update>..HEAD              # new commits
git diff docs/CHANGELOG.md                         # uncommitted edits already made by the user - keep them
```

Earlier updates sometimes missed commits, so also check every commit since the last release tag.
A commit counts as covered if the changelog already links its hash, its `(cherry picked from commit ...)` origin,
or the commit named in a "Port of ..." body:

```sh
tag=$(git describe --tags --abbrev=0)
for h in $(git log --format=%H $tag..HEAD); do
  grep -q "$h" docs/CHANGELOG.md && continue
  o=$(git log -1 --format=%b $h | sed -n 's/.*cherry picked from commit \([0-9a-f]*\).*/\1/p')
  [ -n "$o" ] && grep -q "$o" docs/CHANGELOG.md && continue
  git log -1 --format='%h %ad %s' --date=short $h
done
```

Skip only housekeeping commits: `update the release notes`, `bump version`, and changelog-only doc commits.
Everything else goes in, including branch-specific test changes (put those under Cosmetic).
Add the missed older commits too, and tell the user which ones were missed.

### 2. Understand what each commit fixes

Read `git show <hash>`: the body, the diff, and any new tests. Tests often show the real bug best.
Work out what the user saw: which clients or servers, which options, and whether the code path is
on by default (check `xpra/scripts/config.py`). That decides both the wording and the category.

### 3. Write the entries

Format, under the right category in the top section:
```
  * [description of the problem](https://github.com/Xpra-org/xpra/commit/<full 40-char hash>)
```

- **Describe the problem, not the code change.** Say what broke and for whom, e.g. "GTK clients fail to restack a window above or below another window", not "pass GdkWindow instead of ClientWindow". Mention the option or platform when the bug depends on it, e.g. "with `modal-windows` enabled, ...".
- **One commit per line.** A fixup or a very closely related commit goes on the same line: `  * [main change](url) + [fixup](url)`. Other short forms already in the file also work, such as `[... ](url) [and ...](url)` and `+ [on macOS](url)`.
- **Which hash to link:**
  - a `git cherry-pick -x` commit links the master commit named in `(cherry picked from commit ...)`
  - a manual port (e.g. body says "Port of <hash>") links the **branch commit**, not master
  - everything else links the branch commit
- Always use full hashes: `git rev-parse <short>`.

### 4. Categories

Use the categories already in the top section, keeping their emoji. The usual ones are:
`🔧 Platforms, build and packaging`, `⚠️ Major`, `🌈 Encodings`, `Minor`, `*️⃣ Keyboard`, `📋 Clipboard`,
`🎥 Recorder / replay`, `🖧 Network`, `💄 Cosmetic`. Some are subsystem-specific, e.g. `Wayland backend`, `CUDA and NVENC`, `macOS`, `MS Windows`.

- Add a **new category** only when more than 4 commits refer to the same subsystem. Move the related existing entries into it.
- **Major**: crashes, broken features, sessions or windows unusable, on default settings.
- **Minor**: real bugs with a narrow trigger, like a non-default option or an unusual setup.
- **Cosmetic**: logging errors, spurious warnings, unit tests, CI, type checks.

### 5. Finish

- Change the date on the top section header (`## [x.y.z] YYYY-MM-DD`) to today.
- Check coverage again with the loop from step 1. Only the housekeeping commits should be left.
- Only edit `docs/CHANGELOG.md`. Do not commit unless asked.
- Report what was added and where, which older commits had been missed, and anything left out and why.
