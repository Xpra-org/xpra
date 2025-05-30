# Seamless Mode
Seamless mode is how xpra is generally used, via the `xpra seamless` subcommand.
(or its alias, the legacy `xpra start` subcommand)

This mode allows for individual windows to be forwarded to the client,
these windows appear on the client's desktop just like other local applications.

All window management operations are handled directly by the client's operating system or window manager,
which means that any latency between client and server does not get in the way of window management actions like minimizing,
moving or resizing the windows.\
This makes a huge difference in usability when compared to other modes
([desktop](Desktop.md) and [shadow](Shadow.md)) and other remote desktop solutions like `VNC`.

Obviously, this also means that unlike `VNC`, the remote windows are not trapped within a single desktop window.
Except with the [html5 client](https://github.com/Xpra-org/xpra-html5) where the windows must still be contained within the browser's canvas.

This mode is not available on MS Windows and MacOS, though it can be approximated with [shadow specific applications or windows](https://github.com/Xpra-org/xpra/issues/3476)
