# RPM specs

This directory contains the RPM spec files used by the repository build scripts.
For manifest-driven distro builds, package ordering, and `PYTHON3=` handling in
the `.list` files, see [distros/README.md](distros/README.md).
For further build documentation, see [../docs/Build](../docs/Build).

To manually build one spec for a specific Python interpreter, set `PYTHON3` on
the `rpmbuild` command line:

```shell
PYTHON3=python3.15 rpmbuild -ba packaging/rpm/python3-pillow.spec
```

The selected interpreter must be installed in the build environment, along with
the matching development packages and any Python-version-specific build
dependencies required by the spec.

## Git snapshot sources

Some upstreams have no releases and must be packaged from a git snapshot.
Do not use a forge's on-the-fly archive endpoint for these, ie:

```spec
Source0:	https://chromium.googlesource.com/libyuv/libyuv/+archive/%{git_commit}.tar.gz
```

googlesource (and cgit) build those tarballs on demand and the result is not
byte reproducible, so the `sha256` check in `%prep` breaks on every download
even though the commit has not changed.

Prefer an archive that stores the file: a GitHub release or `archive/<tag>`
tarball, or a distribution's source package. `libyuv.spec` uses Debian's
`orig.tar.xz`, which is immutable and identical to the upstream git tree:

```spec
Source0:	https://snapshot.debian.org/archive/debian/%{deb_snapshot}/pool/main/liby/libyuv/libyuv_%{deb_version}.orig.tar.xz
```

Use `snapshot.debian.org` rather than `deb.debian.org`: the pool only keeps the
version currently in the archive, so a `deb.debian.org` URL breaks as soon as
Debian updates the package, whereas snapshot keeps every version forever.
The timestamp is the `first_seen` value reported by:

```shell
curl https://snapshot.debian.org/mr/package/libyuv/<version>/srcfiles?fileinfo=1
```

## PyPI sources

Use the stable source distribution URL form for PyPI archives:

```spec
Source0:        https://files.pythonhosted.org/packages/source/p/pillow/pillow-%{version}.tar.gz
```

Do not use the hash-path URL copied from a specific PyPI download, because it
changes when the source archive changes:

```spec
Source0:        https://files.pythonhosted.org/packages/65/6e/09db70a523a96d25e115e71cc56a6f9031e7b8cd166c1ac8438307c14058/numpy-%{version}.tar.gz
```

PyPI source distribution filenames are specified as
`{name}-{version}.tar.gz`. The source distribution format specification says the
name component is normalized using the same rules as binary distributions, and
the name normalization specification lowercases project names and replaces each
run of `.`, `_`, or `-` with a single `-`. Use that normalized project name in
the URL path and filename unless the upstream sdist still uses a legacy spelling.

References:

- https://packaging.python.org/en/latest/specifications/source-distribution-format/#source-distribution-file-name
- https://packaging.python.org/en/latest/specifications/name-normalization/#name-normalization
