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
