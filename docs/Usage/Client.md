# Connect to an Xpra session

Use the Xpra client to connect to a session that is running on this computer,
on a server, or on another computer on your local network. For most people,
the graphical tools are the easiest place to start.

## Connect, save, or find a session

Open **Xpra** from your application menu, then choose the task you need:

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Connect

Choose **Connect** to enter a server address and credentials. You can save
these details as a session file to reuse the connection later.

</section>

<section class="docs-card" markdown="1">

### Browse

Choose **Browse** to see sessions found on this computer or advertised on your
local network. Select one to connect with the regular client or in a browser.

</section>

<section class="docs-card" markdown="1">

### Reuse a saved connection

Double-click an `.xpra` session file to open its saved connection details. If
it is set to connect automatically, Xpra connects without showing the dialog.

</section>
</div>

## Connect from a terminal

When you need a repeatable command, or are troubleshooting a connection, use:

```shell
xpra attach ssh://USER@HOST/DISPLAY
```

Replace `USER`, `HOST`, and `DISPLAY` with the account name, server name, and
Xpra display number or session name. The display can be omitted when that
account has only one active Xpra session.

On Windows, use `Xpra_cmd.exe` rather than `Xpra.exe` when running from a
terminal: it prints diagnostic messages there instead of sending them to a log
file.

<details markdown="1">
<summary>Create and edit session files</summary>

Session files use the `.xpra` extension and store the settings shown by the
connection window. The launcher can create them for you. To open one from a
terminal, run:

```shell
xpra launcher session-file.xpra
```

You can also edit a session file in a text editor. Command-line options use
the same names, without the leading `--`; for example, `--min-quality=50`
becomes `min-quality=50` in the file. Set `autoconnect=true` to connect as
soon as the file is opened.

The [HTML5 client](https://github.com/Xpra-org/xpra-html5) can generate session
files from its connection form as well.
</details>

<details markdown="1">
<summary>Browser links, session discovery, and platform details</summary>

Run `xpra sessions` to open the session browser. It lists sessions found
locally and through [multicast DNS](../Network/Multicast-DNS.md) on the local
network.

Applications and browsers can also open Xpra connection links. For example,
`xpra+ssl://HOST:10000/` connects to `HOST` in SSL mode on port `10000`. See
[URL mode mapping](https://github.com/Xpra-org/xpra/issues/1894#issue-792112051)
for details.

Browser links and `.xpra` files need Xpra to be installed from a proper system
package so the operating system can register the integration. On Windows, use
the EXE or MSI installer rather than a ZIP archive; on macOS, use the PKG
installer rather than a DMG archive. Source installations on other platforms
may need [manual integration steps](https://github.com/Xpra-org/xpra/issues/1894#issuecomment-765501182).
</details>

## Next steps

- [Choose a session type and start a server](README.md)
- [Configure persistent client settings](Configuration.md)
- [Use SSH or another connection method](../Network/README.md)
