---
name: update-client-feature-table
description: Refresh the alternative-client feature comparison table in docs/Usage/Clients.md from the client repos it describes (go-xpra, rust-xpra, xpra-html5, vispra). Use when asked to update, refresh or check that table, or when told to "look at the updates to ~/projects/<client>" and reflect them in the docs.
---

# update-client-feature-table

`docs/Usage/Clients.md` compares the xpra client implementations feature by feature. The columns
describe *other* repositories, so the table goes stale on their commits, not on this one's — a
refresh means reading those repos and rewriting only the cells that actually moved.

## The repos behind each column

| Column             | Local clone             | Upstream                           |
|--------------------|-------------------------|------------------------------------|
| Native Xpra client | this repo               | `Xpra-org/xpra`                    |
| xpra-html5         | `~/projects/xpra-html5` | `Xpra-org/xpra-html5`              |
| vispra             | `~/projects/vispra`     | `MajidNajafi/vispra` (third party) |
| Rust client        | `~/projects/rust-xpra`  | `Xpra-org/rust-xpra`               |
| Go client          | `~/projects/go-xpra`    | `Xpra-org/go-xpra`                 |

`~/projects/kotlin-xpra` (Android, Kotlin/Compose) is a sibling client that has **no column yet** —
worth raising when it comes up, but adding it is a bigger edit than a refresh.

## Method

1. **Find what changed.** `git log -1 --format=%ad --date=short -- docs/Usage/Clients.md` in this
   repo gives the date the table was last touched; `git log --format='%h %ad %s' --date=short
   --since=<that date>` in each client repo gives the candidate changes. The README and CHANGELOG of
   each client are the best summary of its current state — read them whole, not just the diff.
2. **Verify against the code, not the prose.** A README describes intent; the hello capabilities
   describe what the server will actually send. Anything not advertised in the hello is never sent,
   so an unadvertised feature is absent no matter what else the repo says:
   - go-xpra: `client/hello.go` (one `buildHello`, commented with the server-side references)
   - rust-xpra: `src/client/client.rs`
   - Backend coverage differs *within* a client — check for a per-backend file
     (`x11/cursor.go`, `wayland/cursor.go`, `win32/cursor.go`) before writing ✅ rather than ◐.
3. **Edit the cells, then re-align.** Hand-edit the affected cells, then run the bundled script,
   which pads every column and regenerates the separator row:
   ```sh
   python3 .claude/skills/update-client-feature-table/retable.py docs/Usage/Clients.md
   ```
   It also fails on a row whose cell count drifted from the header — usually an unescaped `|`.
4. **Update the prose too** when a column moves enough to contradict it: the maturity sentence under
   "Client implementations" and the row list are edited separately from each other.

## Rules that keep the table honest

- **Committed state only.** These clients are developed in parallel with this doc, so their working
  trees often hold the next feature (`git status --short`). Documenting uncommitted work publishes a
  claim about a repo that does not have it yet. Leave it out, and say in the reply what was left out
  and why, so the user can ask for it once it lands.
- **The legend means what it says**: ✅ broad support · ◐ partial or platform-limited · — absent.
  A feature that works on one of three backends is ◐ with the limit named, never ✅.
- **Name the limit, not just the feature.** "◐ PNG icons; on Wayland only with
  `xdg-toplevel-icon-v1`" is the useful cell; "◐ Icons" is not. The per-client READMEs have a
  "what it does not do" / "known limitations" section written for exactly this.
- **Do not upgrade a maturity cell out of enthusiasm.** "⚠️ Proof of concept; README says not yet
  usable" stays until that README says otherwise.
- Rows are features, columns are clients: a new feature row needs a cell for *every* client,
  including a `—` for the ones that lack it.

## Committing

Commit straight to master (this repo's convention). Subject line names the columns that moved, e.g.
`update the client feature table for the rust and go clients`, with the body listing what each
client gained. Docs-only, so the pre-commit hooks have nothing to lint.
