# Landlock filesystem confinement

Xpra has experimental Linux-only Landlock policies for the whole client or
server process. Confinement is disabled by default.

```shell
xpra attach :100 --landlock=default
xpra start :100 --landlock=strict
```

| `--landlock=` | Filesystem policy |
|---|---|
| `no` | Do not install an Xpra Landlock policy. |
| `default` | Broad system and user reads; writes limited to application directories. |
| `strict` | Reads limited to required resources; writes limited to dedicated application directories. |

The option also works as `landlock = MODE` in configuration. Command line
settings override configuration. Values are case insensitive.
`no`, `false`, `0` and `off` select `no`; `yes`, `true`, `1` and `on` select `default`.
The mode is not exported to the environment: the commands started by the server inherit
the Landlock policy itself, but xpra commands run from the session do not try to install their own.
Server upgrades use the current Landlock option rather than reloading the
previous server's saved mode.
Selecting `no` cannot remove restrictions inherited from a parent process.

Both enabled modes require Landlock ABI 9 or newer and fail startup on Linux if
confinement cannot be installed. The option has no effect on other platforms.
Thread synchronization, introduced in ABI 8, confines existing initialization
threads as well as future threads. ABI 9 adds pathname Unix-socket resolution
restrictions. Xpra requires both facilities.

The client `LandLock` subsystem parses its options in `init()`. The listener
subsystem creates its sockets in `load()`, before confinement. LandLock installs
the policy in `run()`, before the main loop starts connection work, including
remote starts and listen mode. Its `setup_connection()` hook also ensures that
confinement is installed before Xpra protocol processing. Failed enforcement
raises `InitExit` and aborts startup; repeated hooks do not install additional
policy layers. Both LandLock subsystems report the mode, enforcement state, ABI
and private temporary directory through `get_info()`.

Qt, Pyglet and Tk clients do not support Landlock and require `--landlock=no`.
They connect synchronously and do not use the client subsystem lifecycle.

The server `LandLock` subsystem installs its policy in `setup()`, before the
remaining subsystems and listeners start. It prepares session D-Bus and starts
the PulseAudio server before confinement, so PulseAudio itself is not confined.
Both client and server subsystems remove their owned private
temporary directories during lifecycle cleanup, including failed enforcement.
Each subsystem stores its temporary path and owner PID; cleanup only removes
storage owned by the current process.

<div class="docs-section-heading" markdown="1">

## Policies

</div>

`default` allows reads from standard system roots, the active Python installation,
the current directory, `HOME`, and the XDG configuration, data, cache, state and
runtime directories. It does **not** protect unrelated home files from being read.
Clients can write to their configured download directory and temporary directories.
Servers can write to their session, menu-icon cache and temporary directories.

`strict` removes blanket access to `HOME`, the current directory, arbitrary Python
search paths and entire user XDG directories. It allows system code and resources,
the actual Python runtime and Xpra package, Xpra configuration, fonts/themes,
desktop configuration, and individual authentication files. Explicitly configured
certificate, key and password files must exist before startup. For SSH, default
identity files, known-hosts files and host-configured identities are readable;
the rest of the SSH directory remains outside the policy.

Strict writes are limited to the client's download directory or the server's
session and menu-icon cache directories, plus explicitly configured mmap resources.
Grants for `/`, the whole home directory, `/tmp`, `/var/tmp` or `/dev/shm` are
rejected. Configure a dedicated download directory before using strict if your
normal download directory falls back to `/tmp`, for example in `xpra.conf`:

```ini
download-path = ~/Downloads
landlock = strict
```

Required writable directories are prepared before enforcement. Private temporary
storage is created with mode `0700` inside the download/session directory, and
temporary files and automatically allocated mmap files use it. It is reused on
exec and removed during normal client/server cleanup; helpers do not remove their parent's
temporary files. An abrupt termination may leave it behind.
Reconnect after cleanup creates fresh private temporary storage.

Client listener sockets, including listen-mode sockets, are created before confinement. Separate directory rules
permit socket lookup and cleanup without granting general file writes. In strict
mode, new pathname sockets are denied afterward. Server display, network and
session sockets and session D-Bus are also created before enforcement.
Strict grants socket lookup for Xpra connections, the display, session/system D-Bus,
PulseAudio and SSH agents using their known paths, rather than broad runtime roots.
The PulseAudio server started by Xpra is granted socket lookup in its whole directory,
because its socket does not exist yet when the policy is installed.

Both modes allow graphics devices below `/dev/dri` and `/dev/accel`, and standard
devices such as `/dev/null`, `/dev/urandom` and pseudo-terminals. Device entries cannot be created,
removed or renamed. Strict permits the process's own procfs directory and public
kernel and graphics-driver version files.
Unless explicitly configured otherwise, strict uses the in-memory GSettings
backend so desktop settings do not require shared dconf writes. Directory rules
also permit removing the emptied server session directory.

For local mmap connections involving strict confinement, configure the same
dedicated shared directory explicitly on both peers, for example
`--mmap=/run/user/1000/xpra/mmap`. Create it before startup so it is recognized as
a directory. Automatic private mmap storage is not accessible to another confined
process; without a shared location, negotiation can fall back to network encoding.

<div class="docs-section-heading" markdown="1">

## Subprocesses and limitations

</div>

Restrictions are inherited across `fork` and `exec`. Applications and helpers
started after confinement receive the same policy, including late server
commands, audio and printing helpers, and commands used to open files or URLs.
Strict mode can limit uploads, credential updates, desktop helpers and applications
which need other paths. There is no file-access broker or runtime permission prompt.
File descriptors opened before confinement retain their existing access.

Landlock denies disallowed operations; `strict` does not kill the process like
`--seccomp=strict`. Filesystem rules govern pathname Unix sockets, not the general
`socket()` syscall, TCP/UDP ports or abstract Unix sockets. Network-port and
IPC-scope restrictions are not enabled. Landlock can be combined with seccomp.

Add `-d landlock` to log the selected mode, ABI and filesystem grants. Denials
normally produce `EACCES`; audit details may be available in the system audit log
or kernel journal. A trace can identify the denied operation and path:

```shell
strace -f -e trace=%file,network -o /tmp/xpra-landlock.strace xpra attach :100 --landlock=strict
rg 'EACCES|EPERM' /tmp/xpra-landlock.strace
```
