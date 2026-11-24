---
name: generate-changelog-entries
description: Write Xpra Markdown release notes in docs/CHANGELOG.md from a Git tag or commit range. Use when asked to summarize commits for a release or fill a release-note placeholder with GitHub links.
---

# Generate changelog entries

1. Inspect the current changelog diff and neighboring release sections. Use the requested version and commit range. For “since the tag,” use `git log <tag>..HEAD` so local commits are included. Follow any repository instructions governing when the changelog can be edited.
2. Review commit messages and inspect diffs or regression tests when the impact is unclear. Describe what users or maintainers observed, such as a missing icon, incorrect window position, or test failure. For dependency-only bumps, state the package and new version. Avoid attributing a symptom the commit does not establish.
3. Match the structure of previous releases. Add a category heading only when several entries form a clear group. Use separate bullets for independent changes, even when they share an issue or component. Combine links on one line only for tightly coupled fixes or follow-ups.
4. Give every commit in scope a descriptive Markdown link to `https://github.com/Xpra-org/xpra/commit/<full-commit-hash>`. Use the hashes from the requested range, including commits that are still local. Generate these URLs from Git history without requiring them to resolve on GitHub.
5. Update the target release block and replace its placeholder when present. Preserve its existing version and date unless the user requests a change. Check the release block's links against `git rev-list <range>` for omissions and duplicates, and run `git diff --check -- docs/CHANGELOG.md`.
