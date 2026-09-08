---
name: backport-review
description: Review commits from a newer release branch for backport suitability, then safely port the selected fixes to a maintenance branch. Use for release backport triage or implementation, not ordinary feature development.
---

# Backport Review

Review a defined newer-branch range against the target maintenance branch and give each commit a concrete disposition: apply, port with prerequisites/conflicts, skip as feature/test/cosmetic/packaging-only, or already present. Do not treat every commit since a branch point as an intended review set: confirm the range from a user-supplied anchor, date window, or explicit commit list.

## Review

- Inspect the changed files and intent, then compare them with the target branch's current code. A different commit hash does not mean the fix is absent.
- Identify prerequisite and follow-up groups. A correction for a new feature is not a standalone backport; concurrency and ownership fixes often need their neighboring fixes applied in order.
- Separate runtime correctness fixes from tests, version bumps, documentation, feature work, and packaging changes. Mark packaging changes as conditional on the maintained package layout and platforms.
- State whether a patch applies cleanly only as supporting evidence; a conflict can still be a valuable, small port.
- Give a concise per-commit breakdown with hashes, purpose, and the recommended disposition, followed by an ordered candidate set.

## Apply selected fixes

Before changing anything, inspect `git status` and preserve unrelated tracked and untracked work. Confirm the target branch and record its starting commit.

- Apply commits individually or in small dependency groups with provenance (`-x` when using cherry-pick).
- Never generate a mailbox by passing a list of revisions directly to `git format-patch`; it can be interpreted as ranges and include unintended history. Use one commit per patch or a verified explicit range.
- When conflicts arise, port the behaviour rather than blindly taking either side. Preserve target-branch logic that is not part of the fix, especially later local changes around lifecycle, threading, or platform-specific code.
- Do not restore files deleted or superseded on the target solely to satisfy a source-branch patch. Adapt the affected callers instead, or skip the inapplicable portion.
- If a proposed regression test depends on a different target test lifecycle or environment, keep the production fix but omit or adapt the test; do not leave a known failing test behind.
- Update the target release's `docs/CHANGELOG.md` for user-facing fixes. Link each entry to its upstream GitHub commit and describe the observed problem rather than the implementation. Reuse the existing headings; add one only for a clear group, and combine links on one line only for tightly coupled fixes or follow-ups.
- Stop and report if the operation would overwrite unrelated work, needs unprovided authority, or the scope is no longer clear.

## Verify and hand off

- Run `git diff --check`, check for unresolved conflict markers, and run focused tests or at least a compile/import check for changed Python modules when relevant.
- Report the applied commits, ports/adaptations, intentionally skipped candidates, verification performed, and any tests that could not be used.
- Preserve pre-existing untracked files and say so when they were present.
