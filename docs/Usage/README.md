# Usage Examples

The examples below should work for the [current versions](https://github.com/Xpra-org/xpra/wiki/Versions).\
[The online manual](https://xpra.org/manual.html) is for the current development version, use `man xpra` to get the version corresponding to the version you have installed.

## Simple [seamless](./Seamless.md) application forwarding
This is how xpra is most often used.\
This command will start an `xterm` (or any graphical application of your choice) on `HOST` and display it to your local desktop through an [SSH](./SSH) transport:
```shell
xpra start ssh://USERNAME@HOST/ --start-child=xterm
```

<details>
  <summary>Step by step</summary>

Instead of starting and attaching to the session using a single command:\
on the server which will export the application (`xterm` in the example), start an xpra server instance on a free display of your choice (`:100 in this example`):
```shell
xpra start :100 --start=xterm
```
then from the client, just connect to this xpra instance:
```shell
xpra attach ssh://USERNAME@HOST/100
```
(replace `HOST` with the hostname or IP of the server)
</details>
<details>
  <summary>Connecting locally</summary>

If you are attaching from the same machine and using the same user account, this is sufficient:
```shell
xpra attach :100
```
And if there is only a single xpra session running, you can omit the display and simply run:
```shell
xpra attach
```
</details>
<details>
  <summary>Access without SSH</summary>

SSH is great, it provides secure authentication and encryption, it is available on all platforms and is well tested.

However, in some cases, you may not want to give remote users shell access, or you may want to share sessions between multiple remote users. \
In this case, use TCP sockets:
```shell
xpra start --start=xterm --bind-tcp=0.0.0.0:10000
```
Then, assuming that the port you have chosen (`10000` in the example above) is allowed through the firewall, you can connect from the client using:
```shell
xpra attach tcp://SERVERHOST:10000/
```

Beware: this TCP socket is insecure, see [authentication](./Authentication.md).
</details>

***

## Forwarding a [full desktop](./Start-Desktop.md)
Xpra can also forward a full desktop environment using the [start-desktop](./Start-Desktop.md) mode:
```shell
xpra start-desktop --start-child=fluxbox
```
Just like above, you can connect via SSH, TCP or any other [supported transport](../Network/README.md).

***

## Cloning / [Shadowing](./Shadow-Server.md) an existing display
This mode allows you to access an existing display remotely.\
Simply run:
```shell
xpra shadow ssh://SERVERHOST/
```

***

## [Clipboard](../Features/Clipboard.md) sharing tool
Xpra synchronizes the clipboard state between the client and server, so it can be used as a clipboard sharing tool:
```shell
xpra shadow --clipboard=yes --printing=no --windows=no --speaker=no ssh://SERVERHOST/
```
(other features are disabled to keep just the clipboard)

***

## [Printer](../Features/Printing.md) forwarder
```shell
xpra shadow --printing=yes --windows=no --speaker=no ssh://SERVERHOST/ 
```
The local printers should be virtualized on the server.
