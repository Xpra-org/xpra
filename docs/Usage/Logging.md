Debug logging is controlled by the `--debug` (or `-d`) option.

## Examples:
Enable `geometry` debugging with a client:
```shell
xpra attach -d geometry
```

Use the special category value `all` to enable all logging. (this will be very verbose and should be avoided)\
You can also prefix a `CATEGORY` with a dash "`-`" to disable debug logging for it.\
For example, to log everything except the `window` and `focus` categories:
```shell
xpra start :10 -d all,-window,-focus
```


## Environment Variables
Each logging category can also be enabled using environment variables. This can be useful if you cannot modify the command line, or if the logging should happen very early on, or if you aren't calling the code from its normal wrappers.\
Use: `XPRA_CATEGORY_DEBUG=1 xpra ...` to enable debug logging for your chosen `CATEGORY`.\
For example, to enable "geometry" debugging with the attach subcommand use:
```shell
XPRA_GEOMETRY_DEBUG=1 xpra attach
```


## Control channel
It is also possible to enable and disable debug logging of a server at runtime using the `control` subcommand:
```shell
xpra control :DISPLAY debug enable CATEGORY
```
The debug control commands are also available trough the server's dbus interface, see [#904](https://github.com/Xpra-org/xpra/issues/904).

This can be used to affect the clients connected to this server using `client debug`:
```shell
xpra control :DISPLAY client debug enable geometry
```


You can enable many categories at once:
```shell
xpra control :2 debug enable window geometry screen
```
Or only enable loggers that match multiple categories with `+`:
```shell
xpra control :2  debug disable focus+grab
```


## Detailed Logging
Some subsystems require special environment variables to enable logging, this is done to minimize the cost of logging in performance critical paths.\
In particular the X11 bindings, as those can process thousands of events per second.

Log all X11 events:
```shell
XPRA_X11_DEBUG_EVENTS="*" xpra start :10
```
or just specific events:
```shell
XPRA_X11_DEBUG_EVENTS="EnterNotify,CreateNotify" xpra start :10
```


---


# List of categories
The full list of categories can be shown using:
```shell
xpra -d help
```

|Area|Description|
|----|-----------|
|**Client:**|
|client|all client code|
|paint|client window paint code|
|draw|client draw packets processing|
|cairo|calls to the cairo drawing library|
|opengl|[OpenGL rendering](./Client-OpenGL.md)|
|info|`About` and `Session info` dialogs|
|launcher|client launcher program|
|**General:**|
|clipboard|all [clipboard](../Features/Clipboard.md) operations|
|notify|[notifications forwarding](../Features/Notifications.md)|
|tray|[system tray forwarding](../Features/System-Tray.md)|
|printing|[printer forwarding](../Features/Printing.md)|
|file|[file transfers](../Features/File-Transfers.md)|
|keyboard|[keyboard](../Features/Keyboard.md) mapping and key event handling|
|screen|screen and workarea dimensions|
|fps|Frames per second|
|xsettings|XSettings synchronization|
|dbus|DBUS calls|
|rpc|Remote Procedure Calls|
|menu|Menus|
|events|System and window events|
|**Window:**|
|window|all window code|
|damage|X11 repaint events|
|geometry|window geometry|
|shape|window shape forwarding (`XShape`)|
|focus|window focus|
|workspace|window workspace synchronization|
|metadata|window metadata|
|alpha|window Alpha channel (transparency)|
|state|window state changes|
|icon|window icons|
|frame|window frame|
|grab|window grabs (both keyboard and mouse)|
|dragndrop|window drag-n-drop events|
|filters|window filters|
|**[Encoding](./Encodings.md):**|
|codec|all codecs|
|loader|codec loader|
|video|video encoding and decoding|
|score|video pipeline scoring and selection|
|encoding|encoding selection and compression|
|scaling|picture scaling|
|scroll|scrolling detection and compression|
|subregion|video subregion processing|
|regiondetect|video region detection|
|regionrefresh|video region refresh|
|refresh|refresh of lossy screen updates|
|compress|pixel compression|
|**[Codec](./Encodings.md):**|
|csc|colourspace conversion codecs|
|cuda|CUDA device access (nvenc)|
|cython|Cython CSC module|
|swscale|swscale CSC module|
|libyuv|libyuv CSC module|
|decoder|all decoders|
|encoder|all encoders|
|avcodec|avcodec decoder|
|libav|libav common code (used by swscale, avcodec and ffmpeg)|
|ffmpeg|ffmpeg encoder|
|pillow|pillow encoder and decoder|
|jpeg|JPEG codec|
|vpx|libvpx encoder and decoder|
|nvenc|nvenc hardware encoder|
|nvfbc|nfbc screen capture|
|x264|libx264 encoder|
|x265|libx265 encoder|
|webp|libwebp encoder and decoder|
|webcam|webcam access|
|**Pointer:**|
|mouse|mouse motion|
|cursor|mouse cursor shape|
|**Misc:**|
|gtk|all GTK code: bindings, client, etc|
|util|all utility functions|
|gobject|command line clients|
|test|test code|
|verbose|very verbose flag|
|**[Network](../Network/README.md):**|
|network|all network code|
|bandwidth|bandwidth detection and management|
|ssh|[SSH](../Network/SSH.md) connections|
|ssl|[SSL](../Network/SSL.md) connections|
|http|HTTP requests|
|rfb|RFB Protocol|
|mmap|mmap transfers|
|protocol|packet input and output|
|websocket|WebSocket layer|
|named-pipe|Named pipe|
|udp|UDP|
|crypto|[encryption](../Network/Encryption.md)
|auth|[authentication](./Authentication.md)
|upnp|UPnP|
|**Server:**|
|server|all server code|
|proxy|[proxy server](./Proxy-Server.md)|
|shadow|[shadow server](./Shadow-Server.md)|
|command|server control channel|
|timeout|server timeouts|
|exec|executing commands|
|mdns|[mDNS](../Network/Multicast-DNS.md) session publishing|
|stats|server statistics|
|xshm|XShm pixel capture|
|**Audio:**|
|sound|all audio|
|gstreamer|GStreamer internal messages|
|av-sync|Audio-video sync|
|**X11:**|
|x11|all X11 code|
|xinput|XInput bindings|
|bindings|X11 Cython bindings|
|core|X11 core bindings|
|randr|X11 RandR bindings|
|ximage|X11 XImage bindings|
|error|X11 errors|
|**Platform:**|
|platform|all platform support code|
|import|platform support imports|
|osx|MacOS platform support|
|win32|Microsoft Windows platform support|
|posix|Posix platform|
