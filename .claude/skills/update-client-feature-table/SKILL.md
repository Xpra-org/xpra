---
name: update-client-feature-table
description: Refresh the alternative-client comparison tables in docs/Usage/Clients.md (features, and project size / build cost) from the client repos they describe (go-xpra, rust-xpra, xpra-html5, vispra). Use when asked to update, refresh or check those tables, or when told to "look at the updates to ~/projects/<client>" and reflect them in the docs.
---

# update-client-feature-table

`docs/Usage/Clients.md` compares the xpra client implementations, feature by feature and project by
project. It describes *other* repositories, so it goes stale on their commits, not on this one's — a
refresh means reading those repos and rewriting only the entries that actually moved.

## The shape of the section

Nothing here is one wide table: prose in a six-column grid forced a horizontal scrollbar. There are
four layers, and a change usually has to land in more than one:

1. **`## Client implementations`** — identity only: link, maintainer, license. No languages here;
   they belong to the size table below, which says more about them.
2. **`## Project size and build`** — one row per client: languages, source size, binary size, build
   time. Measured, not estimated — see [Measuring the size table](#measuring-the-size-table).
3. **The feature matrix** — one narrow `| Feature | xpra | html5 | vispra | rust | go |` table
   carrying only markers, so it fits on screen. No prose, ever; a qualifier here re-widens the table.
4. **A `###` section per client** — one intro sentence carrying what has no matrix row (maturity,
   platforms, any server requirement) followed by a two-column `| Feature | Notes |` table with the
   detail the markers cannot carry.

Feature names must match between the matrix and the per-client tables. The name is the text **before
the ` (`**: a matrix row reading `Picture encodings (rgb/jpeg/png/webp/avif)` pairs with a
`Picture encodings` notes row. A per-client table only lists the rows it has something to add; a row
the matrix already says everything about is left to the matrix alone — since the counted rows below
carry the per-option detail, a note that just re-lists the same options is noise and comes out.

Above the legend sits the line that dates the whole section:

```markdown
This comparison should be correct as of **YYYY-MM-DD HH:MM ±ZZZZ**, the last time it was checked
against each client's repository.
```

It records when the repos were *read*, which is the only honest claim this doc can make about
clients it does not control — a refresh that finds nothing still moves it forward.

## Markers

```markdown
Legend: 🟢 supported · 🟠 partial, platform-limited or degraded · 🔴 absent
```

🟠 is for a feature that is really there but really incomplete: desktop notifications that are only
written to the log, a transport that works on one of three backends, h264 on Windows and nowhere
else. "Works everywhere, with fewer options than the native client" is 🟢, and the options it lacks
belong in its notes row.

**Graded rows** carry one marker: the feature is one thing and it either works, half-works or is
missing.

**Counted rows** name a fixed menu of options in the Feature cell and carry **one marker per option,
in that order**, so the cells can be read down the column as well as across:

| Row                                       | Options, in order                                  |
|-------------------------------------------|----------------------------------------------------|
| `Transports (tcp/ssl/ssh/ws/quic)`        | `ws` covers `wss`; `quic` covers WebTransport       |
| `Transport security (tls/ssh/aes)`        | TLS trust, an ssh tunnel, xpra's own AES layer      |
| `Packet encoding (rencodeplus/yaml)`      |                                                    |
| `Compression in (lz4/zstd/brotli)`        | what the client can decompress                      |
| `Compression out (lz4/zstd/brotli)`       | what it compresses before sending                   |
| `Picture encodings (rgb/jpeg/png/webp/avif)` | `scroll` and `void` are not encodings, leave them to the notes |
| `Video encodings (h264/vp8/vp9/av1)`      | hevc and the rest go in the notes                   |
| `Speaker audio (opus/vorbis/mp3/flac/aac)` |                                                   |

Rules for a counted row, all of them about keeping the table on screen:

- **At most five options**, and the Feature cell under 40 characters. A sixth option that only the
  native client has is a note, not a column of four 🔴.
- **Every client gets the same number of markers**, in the same order — an option no one implements
  is a row of 🔴 in every column and is better dropped from the list entirely.
- Adding an option to a row means editing all five cells. Do not leave a short cell behind.
- **A parenthesis in a Feature cell means "counted"**, so a graded row must not carry one: the mmap
  row is `Shared memory`, with the word `mmap` in its notes, not `Shared memory (mmap)`.

Worth re-running after any edit to the matrix — it catches a cell that lost a marker, which is
invisible in the rendered table:

```sh
python3 - <<'EOF'
import re
rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in open("docs/Usage/Clients.md") if ln.startswith("| ") and not set(ln.strip()) <= set("|-: ")]
for r in rows:
    if r[1:] and all(set(c) <= set("🟢🟠🔴") and c for c in r[1:]):
        want = len(r[0].split("(")[1].rstrip(")").split("/")) if "(" in r[0] else 1
        if any(len(c) != want for c in r[1:]):
            print(f"{r[0]}: want {want} markers, got {[len(c) for c in r[1:]]}")
EOF
```

## The repos behind each client

| Client             | Local clone             | Upstream                           |
|--------------------|-------------------------|------------------------------------|
| Native xpra client | this repo               | `Xpra-org/xpra`                    |
| xpra-html5         | `~/projects/xpra-html5` | `Xpra-org/xpra-html5`              |
| vispra             | `~/projects/vispra`     | `MajidNajafi/vispra` (third party) |
| Rust client        | `~/projects/rust-xpra`  | `Xpra-org/rust-xpra`               |
| Go client          | `~/projects/go-xpra`    | `Xpra-org/go-xpra`                 |

`~/projects/kotlin-xpra` (Android, Kotlin/Compose) is a sibling client that has **no column yet** —
worth raising when it comes up, but adding it is a bigger edit than a refresh.

## Method

1. **Find what changed.** The "correct as of" line above the legend is the cut-off: `git log
   --format='%h %ad %s' --date=iso --since='<that datetime>'` in each client repo gives the candidate
   changes. Compare timestamps, not dates — several rounds of this can land in one day. The README
   and CHANGELOG of each client are the best summary of its current state: read them whole, not just
   the diff, since a feature can regress or be re-scoped without a commit that says so.
2. **Verify against the code, not the prose.** A README describes intent; the hello capabilities
   describe what the server will actually send. Anything not advertised in the hello is never sent,
   so an unadvertised feature is absent no matter what else the repo says:
   - go-xpra: `client/hello.go` (one `buildHello`, commented with the server-side references)
   - rust-xpra: `src/client/client.rs`
   - xpra-html5: `Client.js`, `init_encodings()` and `_get_network_caps()`
   - vispra: `src/core/protocol/`
   - Counted rows need this most: a codec named in a `const` list is not the same as one offered in
     the hello, and a helper with no caller (vispra's `lz4Compress`, reached only from its own test)
     is not an implemented option.
   - Backend coverage differs *within* a client — check for a per-backend file
     (`x11/cursor.go`, `wayland/cursor.go`, `win32/cursor.go`) before writing 🟢 rather than 🟠.
3. **Re-measure the size table** whenever a client's tree or packaging moved — see below. Nothing in
   it can be reasoned out from a diff.
4. **Edit both layers, then re-align.** Hand-edit the matrix markers and the client's notes row, then
   run the bundled script, which pads every column of every `| Feature ` table and regenerates the
   separator rows (keeping the matrix's `:---:` centering):
   ```sh
   python3 .claude/skills/update-client-feature-table/retable.py docs/Usage/Clients.md
   ```
   It also fails on a row whose cell count drifted from the header — usually an unescaped `|`. The
   identity and size tables have their own header, so re-align those with `--prefix '| Client '` —
   which also matches the `| Client tray / menu ` body rows, and only skips them because the script
   requires a `|---|` separator on the line below a header. Do not remove that check: without it the
   script turns those rows into separators and eats the row underneath.
5. **Update the prose too** when a client moves enough to contradict it: the paragraph under
   "Client implementations" and each client's intro sentence are edited separately from the tables.
6. **Stamp it.** Set the "correct as of" line to `date '+%Y-%m-%d %H:%M %z'` taken at the start of
   the pass — every time, including a pass that changed nothing, since "checked and unchanged" is
   exactly what the line is there to say.

## Measuring the size table

Every number in it is measured on the machine doing the refresh, and the table says so. Round hard —
these are orders of magnitude, not benchmarks — and never carry a stale number forward because the
measurement is inconvenient.

**Source size**: tracked files only, in each project's own languages, with vendored third-party
sources excluded and the project's own tests included. `git ls-files` is what keeps build output,
`node_modules` and untracked scratch files out of the count:

```sh
count() { git -C ~/projects/$1 ls-files -- "${@:2}" | wc -l
          git -C ~/projects/$1 ls-files -- "${@:2}" | xargs wc -l | tail -1; }
count xpra       '*.py' '*.pyx' '*.pxd' '*.c' '*.h' '*.cu'
count xpra-html5 '*.js' '*.css' '*.html' ':!:html5/js/lib/*'   # jquery, simple-keyboard, aurora
count vispra     '*.ts' '*.tsx' '*.css' ':!:src/vendor/*'      # its npm deps are not in the tree
count rust-xpra  '*.rs'
count go-xpra    '*.go'
```

The two browser clients vendor differently — html5 commits its libraries, vispra pulls them from
npm — so the html5 row names the excluded weight (about 70 kloc) rather than pretending the trees
are comparable.

**Binary size**: from the published artefacts in `~/projects/repos`, not from a local build, since
that is what a user actually downloads. The column is a *range*, and the point of the range is that
a distribution package leans on the distribution's Python, GTK and codecs while a Windows or macOS
installer carries all of it:

```sh
ls -l ~/projects/repos/stable/Fedora/*/x86_64/xpra-{common,client,client-gtk3,codecs}-*.rpm
ls -l ~/projects/repos/stable/MSWindows/x86_64/Xpra-x86_64_Setup_*.exe
ls -l ~/projects/repos/stable/MacOS/*/Xpra-*.dmg ~/projects/repos/stable/MacOS/*/Xpra-*.pkg
find ~/projects/repos/beta -name 'rust-xpra*' -o -name 'go-xpra*' | grep -v SRPMS   # the two native clients
find ~/projects/repos -name 'xpra-html5*' \( -name '*.deb' -o -name '*.rpm' \)
```

For the native xpra client, sum the *client* subpackages (`xpra-common` dominates, plus `xpra`,
`xpra-client`, `xpra-client-gtk3`, `xpra-codecs`) rather than the whole set — the server packages are
not what this page compares. For the browser clients, the size that matters is what is served: the
built tree, with the pre-compressed `.br`/`.gz` twins excluded, since a browser fetches one of each
file, not three.

**Build time**: wall-clock, from cold, on this machine, with the CPU named in the doc so the numbers
mean something. Always build into the scratch directory — never into the user's own `build/`,
`target/` or `GOCACHE`, and never `cargo clean` their tree:

```sh
cd ~/projects/xpra       && time python3 setup.py build --build-base=$SCRATCH/xpra-build --without-nvidia
cd ~/projects/rust-xpra  && time CARGO_TARGET_DIR=$SCRATCH/rust-target cargo build --release
cd ~/projects/go-xpra    && time GOCACHE=$SCRATCH/gocache go build -o $SCRATCH/go-xpra ./cmd/go-xpra
cd ~/projects/vispra     && time npm run build
cd ~/projects/xpra-html5 && time python3 ./setup.py install $SCRATCH/html5-install
```

Two caveats worth carrying into the doc rather than hiding: xpra's Linux build reuses the `.c` files
Cython already generated in the tree, so a first-ever build is longer than the measured one; and the
Windows and macOS builds are the ones that take over ten minutes, which no Linux measurement will
show. The browser clients need their dependencies installed already (`npm ci` time is not build
time).

## Rules that keep the comparison honest

- **Committed state only.** These clients are developed in parallel with this doc, so their working
  trees often hold the next feature (`git status --short`). Documenting uncommitted work publishes a
  claim about a repo that does not have it yet. Leave it out, and say in the reply what was left out
  and why, so the user can ask for it once it lands.
- **The legend means what it says.** A feature that works on one of three backends is 🟠 with the
  limit named, never 🟢.
- **Name the limit, not just the feature.** "PNG icons; on Wayland only with
  `xdg-toplevel-icon-v1`" is the useful note; "Icons" is not. The per-client READMEs have a
  "what it does not do" / "known limitations" section written for exactly this.
- **Do not upgrade an intro sentence out of enthusiasm.** "Proof of concept - the README says it is
  not yet usable" stays until that README says otherwise.
- A new feature needs a matrix row with a cell for *every* client, including a 🔴 for the ones that
  lack it — then a notes row only under the clients that have something to qualify.
- A number nobody measured is not a number. If an artefact is missing from `~/projects/repos` (no
  Windows build of a client, say), leave that platform out of its cell and say so, rather than
  scaling a Linux figure.

## Committing

Commit straight to master (this repo's convention). Subject line names the columns that moved, e.g.
`update the client feature table for the rust and go clients`, with the body listing what each
client gained. Docs-only, so the pre-commit hooks have nothing to lint.
