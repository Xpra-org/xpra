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
