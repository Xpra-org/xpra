# Frequently Asked Questions

## Installation
### Which version shall I be using?
Always use the [latest released version](https://github.com/Xpra-org/xpra/wiki/Versions)
### Should I use the version shipped with my Linux distribution?
Emphatically [NO](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages)
### Which versions are supported? Which ones are compatible with which versions? On which platforms?
See [versions](https://github.com/Xpra-org/xpra/wiki/Versions) and [platforms](https://github.com/Xpra-org/xpra/wiki/Platforms)
### Why do I get a GPG signature warning when I try to install
You probably forgot to import the GPG key before installing the package.\
The key signature is: `c11c 0a4d f702 edf6 c04f 458c 18ad b31c f18a d6bb`.
### I get a GPG error: `KEYEXPIRED 1273837137`
The key had expired. Try re-importing the [updated key](https://xpra.org/gpg.asc).\
On Debian you may have to delete the key (`apt-key -d`) before adding it again.
### Debian's APT says *Origin changed*, *this must be accepted explicitly...* when updating
Run `apt-get update --allow-releaseinfo-change`.
### Debian's Aptitude says *Some index files failed to download* when updating
See above.

***


## Usage questions
### Where is xpra's system tray icon?
Some desktop environments [make it impossible to show a system tray icon](./Features/System-Tray.md#caveats).
### Why does Xpra use any CPU when the session is idle?
[Audio forwarding](./Features/Audio.md) will consume a fairly constant amount of CPU and bandwidth. Turn speaker forwarding off if you don't need it.\
Some applications will also repaint their windows unnecessarily. If you don't use them, try minimizing their windows.
### Why does the clipboard keep flashing? Why is clipboard synchronization unreliable?
Make sure that no other tool is also doing clipboard synchronization. Avoid clipboard managers at all cost.
### I use [RDP #696](https://github.com/Xpra-org/xpra/issues/696) or [x2go #735](https://github.com/Xpra-org/xpra/issues/735) and I have clipboard or other problems
These tools will do their own clipboard synchronization which will definitely interfere with xpra's.\
Try disabling one of the clipboard synchronization mechanisms, and if possible, do not layer remote desktop protocols on top of each other.
### Where is the command output when I use `Xpra.exe`?
`Xpra.exe` is a graphical application, the command output will go to a `Xpra.log` file found in `%APPDATA%\Xpra`.\
Use `Xpra_cmd.exe` instead.
### How can I start `gpg-agent`, `dbus`, etc for each session?
The solution is often distribution specific.  
You may want to add `--start=/path/to/Xsession` to your server options.\
Or you may want to add each application individually using a `start` option for each application.
### VirtualBox won't release mouse
[disable auto capture keyboard](https://github.com/Xpra-org/xpra/issues/3118#issuecomment-838985119)

***


## Problems
### Some gnome applications take a long time to start (ie: `gnome-terminal`)
Try adding `--source-start=gnome-keyring-daemon` to your server. (see [gnome-terminal takes too long to launch](https://github.com/Xpra-org/xpra/issues/3109), not supported with older versions so use `--start=gnome-keyring-daemon` instead)
### My xpra seamless or desktop session has crashed! Can I recover it?
Generally yes, as long as the virtual display server (vfb) has not crashed.\
If the xpra server is completely gone, you can start a new one to re-use the existing display.\
If the xpra server is still running but unresponsive, you should kill it first (and use `kill -9` to prevent the tear down code from also stopping the vfb display)
### Application X creates a new tab or window on an existing display, not the display I want to use
If the application does not provide an option to prevent this behaviour, you may need to use a different user account to launch multiple instances of this application on different displays - this is a common issue with some applications, in particular browsers
### Why are my applications missing their menu bar on Ubuntu?
Always start your applications with `xpra start --start=APP` and not `DISPLAY=:N APP` (see #1419)


***


## Network
### How can I allow multiple users to connect through a single port?
Use the [proxy server](./Usage/Proxy-Server.md).
### How can I use an SSH key with MS Windows clients?
If your SSH key is not detected and used correctly by default, you may want to use `pageant`: [putty FAQ: How do I use public keys](http://www.chiark.greenend.org.uk/~sgtatham/putty/faq.html#faq-options) and tell xpra to use putty: `--ssh=plink`.


***


## Warnings and Messages
### "`cannot create group socket '/run/xpra/USERNAME'`", usually followed by `[Errno 13] Permission denied`
Harmless warning, safe to ignore. Or you can add your user to the `xpra` group.\
The server tries to create a socket in the shared group directory `/run/xpra`. This is only useful for sharing access to sessions via unix group membership, in combination with the `socket-permissions` option.
### `uinput` warnings:
`uinput` is optional, all these warnings are safe to ignore:
* "`Error: cannot query uinput device path`" or "`cannot access python uinput module: No module named uinput`"
* "`cannot use uinput for virtual devices`"
* "`cannot access python uinput module: name 'ABS_MAX' is not defined`" - your python-uinput package is broken, complain to your distributor
* "`Failed to open the uinput device: Permission denied`" - you do not have the permissions required for opening the `/dev/uinput` device
### "`found an existing window manager on screen ...`"
Xpra is a window manager, you cannot run two window managers on the same X11 display at the same time.\
If you want to forward a whole desktop, including its window manager, see [desktop mode](./Usage/Start-Desktop.md), otherwise stop the other window manager.
### "`cannot register our notification forwarder ...`"
The xpra server was started from a GUI session which already had a dbus instance and a notification daemon, notifications forwarding cannot be enabled. 
### "DPI set to NN x NN (wanted MM x MM), you may experience scaling problems, such as huge or small fonts, etc - to fix this issue, try the dpi switch, or use a patched Xorg dummy driver"
The vfb command in use does not preserve DPI settings. You may want to switch to using a patched [Xdummy](./Usage/Xdummy.md).
### "`xpra [errno 2] no such file or directory`" when connecting via ssh.
Xpra is not installed on the remote host.
### X11 keyboard warnings: `Unsupported high keycode XXX for name <INNN> ignored`
These are harmless and unavoidable, see [Bug 1615700 - warning shows up after run "Xvfb :99 &"](https://bugzilla.redhat.com/show_bug.cgi?id=1615700#c1)
* `gtk_window_add_accel_group: assertion 'GTK_IS_WINDOW (window)' failed` - harmless and unavoidable on MacOS
* `gui.py: Warning: invalid cast from 'GtkMenuBar?' to 'GtkWindow?'` - harmless and unavoidable on MacOS
### MacOS complains about "damaged application"
```
sudo xattr -rd com.apple.quarantine /Applications/Xpra.app
```
### `gi/overrides/Gtk.py:1632: Warning: g_object_ref: assertion 'G_IS_OBJECT (object)' failed`
This is a mostly harmless warning coming from the GTK library.
It is completely pointless as it doesn't specify what object is triggering the problem or from where. But unfortunately, we can't silence it either.
