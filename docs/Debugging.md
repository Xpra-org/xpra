# Debugging Xpra

> Practical steps for collecting diagnostics, isolating problems, and
> investigating crashes.

## Start here

The built-in bug reporting tool is available from most dialog screens and the
system tray menu. It collects much of the information needed when
[filing a bug report](https://github.com/Xpra-org/xpra/issues/new/choose). The
**Session Info** dialog is also useful for diagnostics.

Before reporting a problem:

1. Disable optional features such as clipboard, audio, and OpenGL to narrow
   down the cause.
2. Try different [picture encodings](Usage/Encodings.md).
3. If possible, try another
   [operating system](https://github.com/Xpra-org/xpra/wiki/Platforms),
   client—such as the
   [built-in HTML5 client](https://github.com/Xpra-org/xpra-html5)—or Xpra
   version.
4. Capture the output of `xpra info`.

The `xpra toolbox`, also available from the main launch screen, can run either
natively on the client or through an Xpra session on the server. Comparing the
test results from both sides can reveal where a problem originates.

> [!TIP]
> [Debug logging](Usage/Logging.md) is the most common diagnostic technique.
> Enable the categories related to the affected subsystem.

## Topic-specific guides

- [Keyboard debugging](Features/Keyboard.md)
- [Picture encodings](Usage/Encodings.md)

## Debugging crashes with GDB

When an Xpra process crashes with “core dumped,” use GDB to obtain a backtrace.

### Attach to a running process

Find the Xpra process ID:

```shell
ps -ef | grep xpra
```

Attach GDB to it:

```shell
gdb python $PID_OF_XPRA_PROCESS_TO_DEBUG
```

After the debug symbols have loaded, resume the process:

```gdb
(gdb) continue
```

### Start Xpra in GDB

```gdb
gdb /usr/bin/python3
run /usr/bin/xpra start ...
```

Alternatively:

```gdb
gdb --args /usr/bin/python /usr/bin/xpra start ...
run
```

### Capture the backtrace

When the crash returns control to GDB, capture both the Python stack trace with
`py-bt` and the full stack trace with `bt`.

Debug symbol packages must be installed separately. Consult your distribution's
instructions, such as
[Debian's backtrace guide](https://wiki.debian.org/HowToGetABacktrace) or your
package manager's debuginfo support.

### Signal handling

Xpra handles `SIGINT`, `SIGTERM`, `SIGUSR1`, and `SIGUSR2`. To prevent GDB from
intercepting `SIGINT`, use `handle SIGINT nostop pass`:

```shell
gdb -ex "handle SIGINT nostop pass" \
  --args /usr/bin/python3 /usr/bin/xpra start :20 --no-daemon --start=xterm
```

---

[Documentation home](README.md) ·
[Reporting bugs](https://github.com/Xpra-org/xpra/wiki/Reporting-Bugs)
