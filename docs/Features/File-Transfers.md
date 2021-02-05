![Upload](https://xpra.org/icons/upload.png)

This feature shares most of the code with [printer forwarding](./Printing.md).

This is not meant to replace a network filesystem, it is only there to facilitate the transfer of individual files between the client and server.

For more details, see [#494](https://github.com/Xpra-org/xpra/issues/494) and [#1026](https://github.com/Xpra-org/xpra/issues/1026).


# Client to Server
Assuming that file-transfers are enabled (which is the default - see configuration options below), the client can send files to the server using the system tray upload menu:

![Upload Example](https://xpra.org/images/upload.png)


# Server to Client
The server can send files to the client using:
* the `xpra send-file` subcommand
* the dbus interface: [#904](https://github.com/Xpra-org/xpra/issues/904)
* the xpra control interface, ie: `xpra control :10 send-file /path/to/the-file-to-send`

To send to a specific client: `xpra control :10 send-file /path/to/the-file-to-send open CLIENT_UUID` \
The client UUID can be seen with: `xpra info | grep uuid`.
To send to all the clients, replace use "*". (quoted to prevent shell expansion)

Depending on the client configuration, the `open` flag may not be honoured by the client.


# Configuration Options
* `file-transfer` enables or disables all file transfers
* `file-size-limit` the maximum size for file transfers
* `open-files` allows files to be opened after being received - which may be a security risk
* `open-command` the command to use for opening files

## Debugging
To debug this feature, use the flag `-d file`
