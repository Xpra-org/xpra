---
title: Download Xpra for macOS
---
<script>document.documentElement.classList.add("js")</script>

[← all platforms](README.md)

# Xpra for macOS

{% include download-picker.html name="channel" label="Channel" items=site.data.downloads.channels %}

{% include download-picker.html name="arch" label="Architecture" items=site.data.downloads.macos.arches %}

{% include download-picker.html name="build" label="Build" items=site.data.downloads.builds %}

{% include download-files.html platform="macos" %}

## Installing

These packages are *not notarized*, see
[Can't you just right click?](https://lapcatsoftware.com/articles/unsigned.html) for how to open them.

🔴 If macOS complains that the application is damaged, run:\
`sudo xattr -rd com.apple.quarantine /Applications/Xpra.app`

## Which file?

| Format | Use it for |
| --- | --- |
| `DMG` | disk image: drag the application to the `Applications` folder |
| `PKG` | installer package: also installs the file association |

* `arm64` is for Apple silicon (M1 and later), `x86_64` is for Intel Macs
* **Light** builds are smaller and have more limited codec support, **Full** builds include all the codecs and server support
* the `SBOM` files use the [CycloneDX](https://cyclonedx.org/) JSON format

## Alternatives

* [Homebrew](https://formulae.brew.sh/cask/xpra): `brew install --cask xpra` - installs the stable release
* [build from source](../Build/MacOS.md)
* the [HTML5 client](https://github.com/Xpra-org/xpra-html5) runs in any browser and is served by xpra servers
* [other clients](../Usage/Clients.md)

{% include download-banner.html %}

Looking for a specific file or an older version? See [all downloads](All.md).

<script src="{{ '/assets/js/download.js' | relative_url }}"></script>
