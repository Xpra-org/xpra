# Table of Contents
1. [About](#about)
2. [Installation](#installation)
3. [Usage](#usage)
4. [Documentation](#documentation)
5. [Help](#help)

# About
Xpra is known as _"screen for X"_ : its [seamless mode](./docs/Usage/Seamless.md) allows you to run X11 programs,
usually on a remote host, direct their display to your local machine,
and then to disconnect from these programs and reconnect from the same or another machine(s),
without losing any state.
Effectively giving you remote access to individual graphical applications.  
It can also be used to
[access existing desktop sessions](./docs/Usage/Shadow-Server.md) and [start remote desktop sessions](./docs/Usage/Start-Desktop.md).

Xpra is _open-source_ ([GPLv2+](./COPYING)) with clients available for [many supported platforms](https://github.com/Xpra-org/xpra/wiki/Platforms)
and the server includes a built-in [HTML5 client](https://github.com/Xpra-org/xpra-html5).  
Xpra is usable over a wide variety of [network protocols](./docs/Network/README.md) and does its best to adapt to any network conditions.

Xpra forwards and synchronizes many extra desktop features which allows remote applications to integrate transparently into the client's desktop environment:
[audio input and output](./docs/Features/Audio.md), [printers](./docs/Features/Printing.md), [clipboard](./docs/Features/Clipboard.md),
[system trays](./docs/Features/System-Tray.md), [notifications](./docs/Features/Notifications.md), [webcams](./docs/Features/Webcam.md), etc

It can also [open documents and URLs remotely](./docs/Features/File-Transfers.md), display [high bit depth content](./docs/Features/Image-Depth.md) and it will try honour the [display's DPI](./docs/Features/DPI.md).

---

# Installation
## Official stable downloads
* Microsoft Windows: [EXE](https://xpra.org/dists/windows/Xpra-x86_64_Setup.exe), [ZIP](https://xpra.org/dists/windows/Xpra.zip), [MSI](https://xpra.org/dists/windows/Xpra-x86_64.msi)
* MacOS: [DMG](https://xpra.org/dists/MacOS/x86_64/Xpra.dmg), [PKG](https://xpra.org/dists/osx/x86_64/Xpra.pkg)
* Linux: [RPM](https://github.com/Xpra-org/xpra/wiki/Download#-for-rpm-distributions), [DEB](https://github.com/Xpra-org/xpra/wiki/Download#-for-debian-based-distributions)

All the packages are signed. There are also [beta builds](https://xpra.org/beta) available.  
For more information, see [xpra downloads](https://github.com/Xpra-org/xpra/wiki/Download)

## Build from source
```
git clone https://github.com/Xpra-org/xpra; cd xpra
python3 ./setup.py install
```
For more details, see [building from source](https://github.com/Xpra-org/xpra/tree/master/docs/Build).

---

# Usage
## Seamless Mode
To start an `xterm` on a remote host and display it locally:
```
xpra start ssh://USER@HOST/ --start=xterm
```
(both `xpra` and `xterm` must be installed on `HOST`).  
For more examples, see [usage](./docs/Usage/README.md).

## Shadow
To view an existing desktop session running on a remote host:
```
xpra shadow ssh://USER@HOST/
```

## Network Access
Xpra servers can support [many different types of connections](./docs/Network/README.md) using a single TCP port:
[SSL](./docs/Network/SSL.md), [SSH](./docs/Network/SSH.md), (secure) http / websockets, RFB, etc..\
Connections can be secured using [encryption](./docs/Network/Encryption.md) and [many authentication modules](./docs/Usage/Authentication.md).\
Sessions can be automatically announced on LANs using [multicast DNS](./docs/Network/Multicast-DNS.md)
so that clients can connect more easily using a GUI (ie: `xpra mdns-gui`).\
Its flexible [proxy server](./docs/Usage/Proxy-Server.md) can be used as a relay or front end for multiple server sessions.

---

# Documentation
There is extensive documentation [right here](./docs) for the current development version.  
This documentation is also included with each release.  

For more generic version-agnostic information, checkout [the wiki](https://github.com/Xpra-org/xpra/wiki).

---

# Help
Make sure to check the [FAQ](https://github.com/Xpra-org/xpra/blob/master/docs/FAQ.md), your question may already be answered there.  
You can send your questions to the [mailing list](http://lists.devloop.org.uk/mailman/listinfo/shifter-users) or join us on the IRC channel: `#xpra` on [libera.chat](https://libera.chat).  
If you have hit a bug (sorry about that!), please see [reporting bugs](https://github.com/Xpra-org/xpra/wiki/Reporting-Bugs).
