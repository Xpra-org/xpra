# Share a desktop that is already in use

Shadow mode lets you view and control the desktop that is currently displayed
on another computer. Use it for remote assistance or to return to work that is
already open on a physical desktop.

It works with Linux, macOS, and Windows servers. The display usually needs to
be active and unlocked. If you want a separate remote session instead, use
[desktop mode](Desktop.md); to run only selected applications, use
[seamless mode](Seamless.md).

## Connect securely with SSH

If Xpra is installed on the remote computer and you can log in to it with SSH,
start sharing its current desktop with one command:

```shell
xpra shadow ssh://HOST/
```

Replace `HOST` with the remote computer’s name or IP address. The shadow
server stops when you disconnect, leaving the desktop itself untouched.

If you prefer a graphical tool, open **Xpra** from your application menu and
choose **Shadow**. Enter the remote computer’s address and credentials there.

## Before you share

- Anyone connected can see the display and, unless input is disabled, control
  its keyboard and pointer. Confirm that sharing it is appropriate.
- Screen capture can use more CPU on both computers than a regular Xpra
  session, especially at high resolutions or with rapidly changing content.
- For an existing Xpra seamless or desktop session, attach directly instead of
  shadowing it. Direct attachment preserves Xpra’s normal window and display
  handling.

<details markdown="1">
<summary>Keep a shadow server running or connect without SSH</summary>

Start a persistent shadow server manually when you need to configure it more
closely:

```shell
xpra shadow :0
```

On Linux and other X11 systems, `:0` commonly means the primary display. On
macOS and Windows there is no X11 display name, so omit it. You can also omit
it when the system has only one active display.

To accept TCP connections, bind an address and port:

```shell
xpra shadow :0 --bind-tcp=0.0.0.0:10000
```

This TCP example intentionally has no authentication or encryption. Do not
expose it beyond a trusted network until you have configured both
[authentication](Authentication.md) and [encryption](../Network/Encryption.md).
</details>

<details markdown="1">
<summary>Diagnostics and implementation details</summary>

While the server is running, it is also available through its Unix-domain
socket. For example:

```shell
xpra info ssh://HOST/DISPLAY
```

Use `-d ssh` or another relevant category to enable
[debug logging](Logging.md). The shadow server also displays a system-tray
menu while it is running and changes its icon when a client connects.

![Shadow server tray menu](../images/win32-shadow-tray-menu.png)

For general diagnostic steps, see [Debugging Xpra](../Debugging.md).

Known platform-specific work is tracked in these issues:

- [#899](https://github.com/Xpra-org/xpra/issues/899) generic shadow improvements
- [#389](https://github.com/Xpra-org/xpra/issues/389) Windows shadow server improvements
- [#558](https://github.com/Xpra-org/xpra/issues/558) NVENC support for shadowing on Windows
- [#390](https://github.com/Xpra-org/xpra/issues/390) damage events for the POSIX shadow server
- [#391](https://github.com/Xpra-org/xpra/issues/391) macOS shadow server improvements
- [#530](https://github.com/Xpra-org/xpra/issues/530) resize shadow windows on the client
- [#972](https://github.com/Xpra-org/xpra/issues/972) fullscreen mode in the client
- [#1099](https://github.com/Xpra-org/xpra/issues/1099) keyboard layout on Windows
- [#1150](https://github.com/Xpra-org/xpra/issues/1150) named pipes for Windows
- [#1321](https://github.com/Xpra-org/xpra/issues/1321) scrolling with the macOS shadow screen
- [#1322](https://github.com/Xpra-org/xpra/issues/1322) resizing the macOS shadow screen
</details>

## Next steps

- [Connect to and configure Xpra clients](Client.md)
- [Use SSH or another connection method](../Network/README.md)
- [Forward clipboard, audio, and other features](../Features/README.md)
