# Notifications

This feature allows server side applications to send system notifications (aka notifications bubbles) to the client.

It is supported on all platforms and controlled by the `notifications` [configuration option](../Usage/Configuration.md).

## Platform support
* MS Windows use system _bubbles_ - you may need to [configure your system](http://www.howtogeek.com/75510/beginner-how-to-customize-and-tweak-your-system-tray-icons-in-windows-7/) to show the xpra system tray icon and / or the bubbles
* MacOS clients use a custom GTK window since there was no system API until OSX 10.8.x (this should be replaced with native code at some point)
* posix clients can use `python-notify` or `python-dbus` (the exact name of the packages required vary)

## Screenshots
MS Windows XP: \
![MS Windows Notification](../images/win2-notification.png)

MacOS 10.10.x: \
![MacOS Notification](../images/osx-notification.png)

Gnome-shell: \
![Gnome-Shell Notification](../images/gnome-shell-notification.png)

***

## Debugging
* start both the client and server with the debug command line flags: `-d notify,dbus`
* you can also test notifications forwarding using the dbus interface or xpra control, ie:
  ```shell
  xpra control :100 send-notification "hello" "world" "*"
  ```
  will send the message to all clients.
