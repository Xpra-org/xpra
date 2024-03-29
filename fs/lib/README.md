# `/lib`

Packages for Posix sytems will install the following files into `/lib` or `/libexec`:
|Path|Purpose|
|----|-----------|
|[`/lib/cups/xpraforwarder`](https://github.com/Xpra-org/xpra/tree/master/fs/lib/cups/xpraforwarder)|virtual printer backend|
|[`/lib/systemd/system/*`](https://github.com/Xpra-org/xpra/tree/master/fs/lib/systemd/system)|systemd service and socket activation files|
|[`/lib/sysusers.d/xpra.conf`](https://github.com/Xpra-org/xpra/tree/master/fs/lib/sysusers.d/xpra.conf)|[sysusers.d](https://www.freedesktop.org/software/systemd/man/sysusers.d.html) declarative allocation of system users and groups|
|[`/lib/tmpfiles.d/xpra.conf`](https://github.com/Xpra-org/xpra/tree/master/fs/lib/tmpfiles.d/xpra.conf)|[tmpfiles.d](https://www.freedesktop.org/software/systemd/man/tmpfiles.d.html) configuration for creation, deletion and cleaning of volatile and temporary files|
|[`/lib/tmpfiles.d/xpra.conf`](https://github.com/Xpra-org/xpra/tree/master/fs/lib/tmpfiles.d/xpra.conf)|[tmpfiles.d](https://www.freedesktop.org/software/systemd/man/tmpfiles.d.html) configuration for creation, deletion and cleaning of volatile and temporary files|
|[`/lib/udev/rules.d/71-xpra-virtual-pointer.rules`](https://github.com/Xpra-org/xpra/tree/master/fs/lib/udev/rules.d/71-xpra-virtual-pointer.rules)|udev rules for xpra's uinput virtual devices|
