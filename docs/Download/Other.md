---
title: Download Xpra for other platforms
---

[← all platforms](README.md)

# Xpra for other platforms

## Source

The source code is available from the [GitHub repository](https://github.com/Xpra-org/xpra) and as release snapshots:

* [PyPI releases](https://pypi.org/project/xpra/#history) - preferred
* [xpra.org source archives](https://xpra.org/src/) - identical to PyPI
* [GitHub releases](https://github.com/Xpra-org/xpra/releases) - backup

See [building from source](../Build/README.md) and the [dependencies](../Build/Dependencies.md).

## Clients for any platform

* the [HTML5 client](https://github.com/Xpra-org/xpra-html5) runs in any modern browser, including mobile devices, and is served by xpra servers
* [go-xpra](https://github.com/Xpra-org/go-xpra), [rust-xpra](https://github.com/Xpra-org/rust-xpra) and others: see the [client comparison](../Usage/Clients.md)

## Distribution packages

Many distributions ship their own `xpra` package, but some of these are
[old or broken](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages): prefer the
[xpra.org repositories](Linux.md) where available.

* [MSYS2](https://www.msys2.org/) on MS Windows: `pacman -S mingw-w64-x86_64-python3-xpra`
* [Homebrew](https://formulae.brew.sh/cask/xpra) on macOS: `brew install --cask xpra`
* other platforms: see the [build documentation](../Build/Other.md)

{% include download-banner.html %}
