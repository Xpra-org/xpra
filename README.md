Xpra started as _"screen for X"_ as its [seamless mode](./docs/Usage/Seamless) allows you to run X11 programs,
usually on a remote host, direct their display to your local machine,
and then to disconnect from these programs and reconnect from the same or another machine(s),
without losing any state.
Effectively giving you remote access to individual graphical applications.  
Later, it evolved to handle more many more use cases:
[accessing existing desktop sessions](./docs/Usage/Shadow-Server) and [starting remote desktop sessions](./docs/Usage/Start-Desktop),
and [many network protocols](./docs/Network/README.md).  

Xpra is _open-source_ ([GPLv2+](./COPYING)) with clients available for [many supported platforms](./Platforms)
and the server includes a built-in [HTML5 client](https://github.com/Xpra-org/xpra-html5).  
Xpra is usable over a variety of [network protocols](./docs/Network/README.md) and does its best to adapt to the any network conditions.

# Key Features
Xpra forwards and synchronizes many extra desktop features which allows remote applications to integrate transparently into the client's desktop environment:
[audio input and output](./docs/Features/Audio), [printers](./docs/Features/Printing), [clipboard](./docs/Features/Clipboard),
[system trays](./docs/Features/System-Tray), [notifications](./docs/Features/Notifications),  [drag and drop](./docs/Features/DragAndDrop), [webcams](./docs/Features/Webcam), etc

It can also [open documents and URLs remotely](./docs/Features/File-Transfers), display [high bit depth content](./docs/Features/Image-Depth) and it will try honour the [display's DPI](./docs/Features/DPI).

# Network Access
Xpra servers can support [many different types of connections](./docs/Network/README.md) using a single TCP port:
[SSL](./docs/Network/SSL), [SSH](./docs/Network/SSH), (secure) http / websockets, RFB, etc..\
Connections can be secured using [encryption](./docs/Network/Encryption) and [many authentication modules](./docs/Usage/Authentication).\
Sessions can be automatically announced on LANs using [multicast DNS](./docs/Network/Multicast-DNS)
so that clients can connect more easily using a GUI (ie: `xpra mdns-gui`).\
Its flexible [proxy server](./docs/Usage/Proxy-Server) can be used as a relay or front end for multiple server sessions.

# Getting Started
Either [download the official packages](./wiki/Download) or [install from source](./docs/Building/README.md) (usually just `python3 ./setup.py install`).

Then you can just run:
```
xpra start ssh://USER@HOST/ --start=xterm
```
To start `xterm` on `HOST` and display it locally (`xterm` must be installed on `HOST`).  
For more examples, see [usage](./docs/Usage/README.md).
