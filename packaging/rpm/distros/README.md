# RPM build manifests (`distros/*.list`)

Each `.list` file is a build manifest for one RPM target. The
[Xpra-org/repo-build-scripts](https://github.com/Xpra-org/repo-build-scripts)
read the manifest and build each entry **in the order it is listed**, using the
matching spec file from `packaging/rpm/`.

## Which list is used

For a given target, the build scripts pick the *most specific* matching manifest
and fall back to less specific names, for example:

```
centos-stream9-arm64.list  ->  centos-stream9.list  ->  centos.list  ->  default.list
```

(roughly: `<distro>-<version>-<arch>`, `<distro>-<version>`, `<distro>`, `<arch>`,
then `default`). Only one manifest is used per target, so each `.list` is
self-contained and ends with the `xpra` package itself.

## File format

* One build target per line (the spec basename without `.spec`, e.g.
  `python3-fido2`, or a non-Python component such as `openh264`).
* Blank lines and `# comments` are ignored.
* A `PYTHON3=python3.NN` line sets the interpreter used for **all subsequent**
  builds in that manifest. For example the EL9 manifests build everything against
  `python3.12` rather than the system `python3.9`.

## Build order matters

Targets are built top to bottom. If package **B** needs package **A** at build
time, **A must be listed before B** — the build scripts will produce A and make it
available before B is built.

This is how missing build dependencies are fixed: **reorder the manifest, do not
patch the failing spec.**

### Canonical example: `python3-wheel` before `python3-fido2`

On EL9 the manifests set `PYTHON3=python3.12`, but the distro provides no
`python3.12-wheel`. `python3-fido2` builds with `pip wheel ... --no-build-isolation`,
which requires `wheel` to already be importable for `python3.12`. If `python3-fido2`
is listed first the build fails with:

```
error: invalid command 'bdist_wheel'
```

The fix is simply to list `python3-wheel` ahead of `python3-fido2`, so the build
scripts produce `python3.12-wheel` in time:

```
python3-pyu2f
python3-wheel      # built first, provides python3.12-wheel
python3-fido2      # can now build with --no-build-isolation
python3-uinput
```

The same rule applies to any manifest that uses a `PYTHON3=` override targeting an
interpreter for which the distribution ships no `pythonX.Y-wheel`.
