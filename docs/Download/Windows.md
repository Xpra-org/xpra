---
title: Download Xpra for MS Windows
---
<script>document.documentElement.classList.add("js")</script>

[← all platforms](README.md)

# Xpra for MS Windows

{% include download-picker.html name="channel" label="Channel" items=site.data.downloads.channels %}

{% include download-picker.html name="arch" label="Architecture" items=site.data.downloads.windows.arches %}

{% include download-picker.html name="build" label="Build" items=site.data.downloads.builds %}

{% include download-files.html platform="windows" %}

## Which file?

| Format | Use it for |
| --- | --- |
| `EXE` | the general purpose installer, recommended |
| `MSI` | unattended or managed installations |
| `ZIP` | a portable installation without administrator rights, there is no file association |

* **Light** builds are smaller and have more limited codec support, **Full** builds include all the codecs and server support
* `arm64` builds are fully supported, but have more limited hardware support
* the `SBOM` files use the [CycloneDX](https://cyclonedx.org/) JSON format, they may be slightly incomplete for Full builds

## Unattended installation

* use the `MSI` installer
* or run the `EXE` installer with the `/verysilent` [InnoSetup command line argument](https://jrsoftware.org/ishelp/index.php?topic=setupcmdline)

See also: [running xpra as a Windows service](../Usage/Windows-Service.md), [WSL](../Usage/WSL.md).

## Alternatives

* [MSYS2](https://www.msys2.org/): `pacman -S mingw-w64-x86_64-python3-xpra` - no NVIDIA codecs or file association, but you control the components and dependencies yourself
* [build from source](../Build/MSWindows.md)
* the [HTML5 client](https://github.com/Xpra-org/xpra-html5) runs in any browser and is served by xpra servers
* [other clients](../Usage/Clients.md)

{% include download-banner.html %}

Looking for a specific file or an older version? See [all downloads](All.md).

<script src="{{ '/assets/js/download.js' | relative_url }}"></script>
