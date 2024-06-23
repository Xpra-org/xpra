This pseudo filesystem layout contains files that will be installed with xpra:

| Directory      | Contents                                                                |
|----------------|-------------------------------------------------------------------------|
| `bin`          | the main entry point scripts and some helper tools                      |
| `etc`          | Xpra's own configuration files, `dbus`, `X11` and system service files` |
| `lib`          | support files for printing, `udev` and `systemd` integration            |
| `libexec/xpra` | client signal listener, uinput udev integration, file open capture      |
| `share`        | man page, icons, package metadata, `SELinux` modules, etc               |

In most cases, the installation path will be identical, but on platforms with monolithic builds (MS Windows and MacOS) the paths will be relative to the installation location and may change slightly.
