# `/etc`

Packages for Posix sytems will install the following files into `/etc`:
|Path|Purpose|
|----|-----------|
|[`/etc/X11/xorg.conf.d/90-xpra-virtual.conf`](https://github.com/Xpra-org/xpra/tree/master/fs/etc/X11/xorg.conf.d/90-xpra-virtual.conf)|used to ensure that regular X11 servers will ignore all xpra virtual devices by default|
|[`/etc/dbus-1/system.d/xpra.conf`](https://github.com/Xpra-org/xpra/tree/master/fs/etc/dbus-1/system.d/xpra.conf)|configures permissions for the server's `dbus` interface|
|[`/etc/init.d/xpra`](https://github.com/Xpra-org/xpra/tree/master/fs/etc/init.d/xpra)|system V service init file - unused on systems packaged for `systemd`|
|[`/etc/pam.d/xpra`](https://github.com/Xpra-org/xpra/tree/master/fs/etc/pam.d)|configuration file for xpra's pam authentication module|
|[`/etc/sysconfig/xpra`](https://github.com/Xpra-org/xpra/tree/master/fs/etc/sysconfig/xpra)|system service configuration file (installed in `/etc/default/` on some systems)|
|[`/etc/xpra/*`](https://github.com/Xpra-org/xpra/tree/master/fs/etc/xpra)|xpra's own configuration files|
