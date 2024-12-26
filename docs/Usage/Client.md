# Xpra Client

There are many ways to launch the xpra client. \
The default GUI interface can be used to access the launcher and the session browser.

## Launcher
The launcher is accessible using the `launcher` subcommand:
```shell
xpra launcher [session-file.xpra]
```
It provides a GUI for filling in the address of the server you want to connect to: mode, hostname or IP address, port, etc. \
These options can be loaded from and saved into a session file.

## Session Files
Session files use the extension `.xpra` and record all the session settings, including the connection parameters shown in the session launcher. \
Any command line option can be specified in this file by removing the `--` that precedes options when they're used via the command line.
ie: `--min-quality=50` becomes just `min-quality=50`. \
Double-clicking a session file brings up the launcher and if the session file contains `autoconnect=true` then the connection will be made without first showing the launcher dialog.
The [html5 client](https://github.com/Xpra-org/xpra-html5) can also generate session files from its connection form.

## Session Browser
`xpra sessions` shows the session browser, this window lists all the sessions that can be found either on the local system or through [mDNS](../Network/Multicast-DNS.md) on the local network. \
From this list, it is possible to start a connection to the sessions, either using the regular client or using the html5 client in a browser.

## URL mapping
This mechanism allows browsers and other applications to launch an xpra client and specify connection options without having to first download or generate a session file. \
For example, this is a valid URL for connecting to _HOST_ in _ssl_ mode on port 10000: `xpra+ssl://HOST:10000/`. \
For more details, see [url mode mapping](https://github.com/Xpra-org/xpra/issues/1894#issue-792112051)

## Platform Quirks
Both the URL mapping and session files require xpra to be installed using proper packages rather than archives. \
This ensures that the operating system integration is registered correctly. \
On MS Windows, that means using `EXE` or `MSI` installers and not `ZIP` files. On MacOS, `PKG` and not `DMG` archives. \
When installing from source on other platforms, [manual steps](https://github.com/Xpra-org/xpra/issues/1894#issuecomment-765501182) may be required.

## Command line
The command line is the most powerful tool for running the client and has the advantage of printing out diagnostic messages directly
on the terminal where it is executed. \
On MS Windows, the command you should use is `Xpra_cmd.exe` rather than plain `Xpra.exe` as  the latter uses a log file. \
The command line should always be used when testing or debugging.
