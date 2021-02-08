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

# Key Features
Xpra forwards and synchronizes many extra desktop features which allows remote applications to integrate transparently into the client's desktop environment:
[audio input and output](./docs/Features/Audio.md), [printers](./docs/Features/Printing.md), [clipboard](./docs/Features/Clipboard.md),
[system trays](./docs/Features/System-Tray.md), [notifications](./docs/Features/Notifications.md), [webcams](./docs/Features/Webcam.md), etc

It can also [open documents and URLs remotely](./docs/Features/File-Transfers.md), display [high bit depth content](./docs/Features/Image-Depth.md) and it will try honour the [display's DPI](./docs/Features/DPI.md).

# Network Access
Xpra servers can support [many different types of connections](./docs/Network/README.md) using a single TCP port:
[SSL](./docs/Network/SSL.md), [SSH](./docs/Network/SSH.md), (secure) http / websockets, RFB, etc..\
Connections can be secured using [encryption](./docs/Network/Encryption.md) and [many authentication modules](./docs/Usage/Authentication.md).\
Sessions can be automatically announced on LANs using [multicast DNS](./docs/Network/Multicast-DNS.md)
so that clients can connect more easily using a GUI (ie: `xpra mdns-gui`).\
Its flexible [proxy server](./docs/Usage/Proxy-Server.md) can be used as a relay or front end for multiple server sessions.

# Getting Started
Either [download the official packages](https://github.com/Xpra-org/xpra/wiki/Download) or [install from source](./docs/Build/README.md) (usually just `python3 ./setup.py install`).

Then you can just run:
```
xpra start ssh://USER@HOST/ --start=xterm
```
To start `xterm` on `HOST` and display it locally (`xterm` must be installed on `HOST`).  
For more examples, see [usage](./docs/Usage/README.md).

# Help
You can send your questions to the [mailing list](http://lists.devloop.org.uk/mailman/listinfo/shifter-users) or join us on the IRC channel: [#winswitch on irc.freenode.net](irc://irc.freenode.net/winswitch).
