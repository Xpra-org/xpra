![Server-Connected](https://xpra.org/icons/server-connected.png)

This feature refers to the ability of using an existing display server (an existing session, usually connected to a real physical display) and use xpra to access it remotely.

It is supported on all platforms including MS Windows and Mac OS X, but not on Wayland.\
It is not optimized on all platforms and may cause high CPU load on both the server and the client in some cases.

On most platforms, the display being shadowed must be active: not locked or turned off.


# SSH Usage Example

If you have SSH access to the machine whose X11 display you wish to access remotely, simply run from your client:

    xpra shadow ssh://HOST/

This will connect over SSH to `HOST`, start and xpra shadow server and connect to it.\
The shadow server will be stopped once you disconnect.\
Xpra must already be installed on the server.

The xpra shadow server will be accessible like any other xpra server through its unix domain socket (ie: `xpra info ssh://HOST/DISPLAY`), and it will show a system tray menu whilst active, and a different icon when a client is connected:
![shadow tray example](https://xpra.org/images/win32-shadow-tray-menu.png)


# Manually
If starting via SSH is not supported as above, as is the case on most MS Windows and MacOS systems, or simply if you want to start the shadow server manually, and potentially configure more options, you can start it from a shell.

To expose your existing main display session (usually found at `:0` on *nix) using a TCP server on port 10000:

    xpra shadow :0 --bind-tcp=0.0.0.0:10000

Notes:
* this is insecure and does not cover [authentication](./Authentication.md) or [encryption](../Network/Encryption.md)
* MS Windows and Mac OS X do not have X11 display names (`:0` in the example above), in this case you can simply omit the display argument
* if there is only a single `$DISPLAY` active on the system, you do not need to specify it (no `:0`)


# Relevant Tickets
* [#899](https://github.com/Xpra-org/xpra/issues/899) generic shadow improvements
* [#389](https://github.com/Xpra-org/xpra/issues/389) ms windows shadow server improvements
* [#558](https://github.com/Xpra-org/xpra/issues/558) nvenc support for shadowing on win32
* [#390](https://github.com/Xpra-org/xpra/issues/390) damage events for the posix shadow server
* [#391](https://github.com/Xpra-org/xpra/issues/391) osx shadow server improvements: mdns, keyboard support, etc
* [#530](https://github.com/Xpra-org/xpra/issues/530) allow client side shadow windows to be resized
* [#972](https://github.com/Xpra-org/xpra/issues/972) fullscreen mode in xpra client
* [#1099](https://github.com/Xpra-org/xpra/issues/1099) Keyboard Layout issue with Windows Shadow Server
* [#1150](https://github.com/Xpra-org/xpra/issues/1150) named pipes for win32
* [#1321](https://github.com/Xpra-org/xpra/issues/1321) scrolling with the osx shadow server
* [#1322](https://github.com/Xpra-org/xpra/issues/1322) resize osx shadow screen
