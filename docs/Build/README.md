# Building Xpra

Build Xpra from source when you need a development checkout, a custom
installation, or packages for a platform not covered by the usual downloads.
Start with the platform guide, then install dependencies before running the
build commands.

<div class="docs-section-heading" markdown="1">

## Platform guides

Choose the instructions that match the system where you will build Xpra.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### [Fedora, CentOS, and RHEL](RPM.md)

Build RPM packages and install the dependencies for Red Hat-based systems.

</section>

<section class="docs-card" markdown="1">

### [Debian and Ubuntu](Debian.md)

Build Debian packages or install Xpra from source on Debian-based systems.

</section>

<section class="docs-card" markdown="1">

### [Microsoft Windows](MSWindows.md)

Set up the Windows build environment and produce the Windows installer.

</section>

<section class="docs-card" markdown="1">

### [macOS](MacOS.md)

Build the macOS application bundle and its platform dependencies.

</section>

<section class="docs-card" markdown="1">

### [Other platforms](Other.md)

See the general instructions for platforms not covered by the dedicated guides.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Download the source

Use one of the following locations, depending on whether you need the current
development tree or a released source archive.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### GitHub

The main repository contains the current Xpra source. The HTML5 client lives in
its own repository:

- [Xpra](https://github.com/Xpra-org/xpra)
- [Xpra HTML5](https://github.com/Xpra-org/xpra-html5)

</section>

<section class="docs-card" markdown="1">

### Release archives

Download released source packages from [PyPI](https://pypi.org/project/xpra/)
or [xpra.org](https://xpra.org/src/). See [source metrics](Source.md) for more
information about the codebase.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Build from a checkout

Install the required [dependencies](Dependencies.md) first, then clone and
install Xpra:

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### Source installation

```shell
git clone https://github.com/Xpra-org/xpra
cd xpra
python3 ./setup.py install --prefix=/usr --single-version-externally-managed --root=/
cp fs/bin/xpra* fs/bin/run_scaled /usr/bin/
```

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Build caveats

Keep source and binary installations separate, and make sure the Python version
matches the branch you are building.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Do not mix installation methods

**Do not** mix a source installation with binary packages. Remove one
installation completely before installing the other.

</section>

<section class="docs-card" markdown="1">

### Python versions

Current Xpra versions require Python 3. For Python 2, use the 3.x LTS branch;
see the [supported versions](https://github.com/Xpra-org/xpra/wiki/Versions).

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Why copy the scripts?

The final step installs Xpra’s own scripts, replacing the unusable scripts that
setuptools may otherwise mangle.

</section>
</div>
