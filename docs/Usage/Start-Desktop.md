# Desktop Mode
_desktop mode_ as opposed to [seamless mode](./Seamless.md) runs a full desktop session in a window instead of having each individual window forwarded separately.\
This feature requires X11 server support and is not available on MacOS or MS Windows servers.

The behaviour is more similar to VNC but with the added benefits of the xpra protocol: sound, printer forwarding, etc. (see [features](../Features/README.md))

You can also connect using VNC clients.\
To access an existing desktop session, use the [shadow server](./Shadow-Server.md)- which is also available on MacOS and MS Windows.


## Usage
To start a desktop session simply run:
```shell
xpra start-desktop --start=xterm
```
Then connect as usual from the client, or using a VNC client.

Alternatively, you can start a session and connect in one command from the client using the ssh syntax:
```shell
xpra start-desktop --start=xterm ssh://USER@HOST/
```


## Window Manager or Desktop Environment
In order to run a window manager or even a full desktop environment within this desktop session, simply replace the "xterm" example above with the command that starts the WM or DE of your choice, ie for "fluxbox":
```shell
xpra start-desktop --start=fluxbox
```
When choosing a window manager, be aware that the more featureful ones also tend to use more bandwidth and will appear to run more slowly.


## Desktop Size

By default the desktop size will start using a screen resolution of 1920x1080, this virtual screen can be resized at any point using regular X11 tools (ie: "xrandr").

To change the initial desktop size:
```shell
xpra start-desktop --resize-display="1024x768" --start=fluxbox
```

## Caveats
* to get the session to terminate when you exit the window manager, use `--start-child` with `--exit-with-children`
* some desktop environments may show options to shutdown or reboot the system from their start menu, which may or may not be appropriate
