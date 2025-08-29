# Command line usage Examples

Xpra includes a _start_ GUI capable of replacing most of the example command lines found below. \

These examples should work for the [current versions](https://github.com/Xpra-org/xpra/wiki/Versions).\
Use `man xpra` to get the manual corresponding to the version you have installed. \
On MS Windows, please see [windows command line](./Client.md#command-line). \

## Simple [seamless](Seamless.md) application forwarding
This is how xpra is most often used.\
This command will start an `xterm` (or any graphical application of your choice) on `HOST` and display it to your local desktop through an [SSH](../Network/SSH.md) transport:
```shell
xpra seamless ssh://USERNAME@HOST/ --start-child=xterm
```

<details>
  <summary>Step by step</summary>

Instead of starting and attaching to the session using a single command:\
first connect to the server via ssh and start the xpra server instance on a free display of your choice (`:100 in this example`):
```shell
xpra seamless :100 --start=xterm
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

SSH is great, it provides host verification, secure authentication and encryption, it is available on all platforms and is well tested.

However, in some cases, you may not want to give remote users shell access, or you may want to share sessions between multiple remote users. \
For this type of use case, you can use TCP sockets:
```shell
xpra seamless --start=xterm --bind-tcp=0.0.0.0:10000
```
Then, assuming that the port you have chosen (`10000` in the example above) is allowed through the firewall, you can connect from the client using:
```shell
xpra attach tcp://SERVERHOST:10000/
```

Beware: this TCP socket is insecure in this example, see [authentication](Authentication.md).
</details>
<details>
  <summary>Attach with a session file</summary>
  Typing the same attach commands over and over again can be tedious, especially if you tweak the command line options.

  Instead, you can create session files and just double-click on them to connect to the session:
  ```shell
cat > ~/Desktop/example.xpra
mode=ssh
host=YOURSERVER
speaker=off
```
  For more information, see [session files](./Client.md#session-files)
</details>

***

## Forwarding a [full desktop](Desktop.md)
Xpra can also forward a full desktop environment using the [desktop](Desktop.md) mode:
```shell
xpra desktop --start-child=fluxbox
```
Just like above, you can connect via SSH, TCP or any other [supported transport](../Network/README.md).

***

## Cloning / [Shadowing](Shadow.md) an existing display
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

## Other Documentation Links
* [Client](Client.md) - launching the xpra client
* [Client OpenGL](Client-OpenGL.md) - for better window rendering performance
* [OpenGL](OpenGL.md) - running accelerated OpenGL application on the server
* [Configuration](Configuration.md) - using configuration files
* [Encodings](Encodings.md) - advanced picture encoding configuration, ie: [NVENC](NVENC.md)
* [Logging](Logging.md) - debugging
* [Security](Security.md) - hardening, options and using xpra for better security
* [Proxy Server](Proxy-Server.md) - using a proxy server as a single entry point
  * [Apache Proxy Server](Apache-Proxy.md) - using apache
  * [Nginx Proxy Server](Apache-Proxy.md) - using nginx
* [WSL](WSL.md) - Windows Subsystem for Linux
* [Xdummy](Xdummy.md) - the alternative virtual framebuffer
