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

## Python stack traces on crashes

Set `XPRA_FAULTHANDLER=1` before starting Xpra to enable Python's fault handler.
It dumps Python stack traces for all threads to standard error when the process
crashes:

```shell
XPRA_FAULTHANDLER=1 xpra start :20 --no-daemon
```

This is equivalent to Python's `-X faulthandler` option and also works with
frozen Windows executables such as `xpra_cmd.exe`, where interpreter flags
cannot be passed directly.

## Crash reports on Windows

Set `XPRA_EXCHNDL=1` to enable Dr. MinGW's crash handler. It writes native stack
traces for every thread to a `.RPT` file when the process crashes. You can
enable it alongside Python's fault handler in PowerShell:

```powershell
$env:XPRA_FAULTHANDLER = "1"
$env:XPRA_EXCHNDL = "1"
.\xpra_cmd.exe attach tcp://SERVER:14500 2> xpra-crash.log
```

Replace `SERVER:14500` with your server address. Python crash traces are
captured in `xpra-crash.log`. Native crash reports are written to the system
temporary directory as `<executable-name>-<PID>.RPT`, for example
`xpra_cmd-1234.RPT`. Xpra prints the report path at startup.

To choose a different report path, set `XPRA_EXCHNDL_REPORT` before launching
Xpra:

```powershell
$env:XPRA_EXCHNDL_REPORT = "$env:TEMP\xpra-crash.RPT"
```

The Windows build includes the required `exchndl.dll` and `mgwhelp.dll` beside
the executable. If Xpra warns that it failed to load `exchndl.dll`, check that
both DLLs are available.

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
