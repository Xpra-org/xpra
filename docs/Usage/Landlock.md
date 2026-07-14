# Landlock filesystem confinement

Xpra has an experimental Linux-only Landlock policy which confines filesystem
access for the whole client or server process. It is disabled by default.

Enable it for one process with:

```shell
XPRA_LANDLOCK=1 xpra attach :100
```

Landlock ABI 9 or newer is required. Xpra uses ABI 9 thread synchronization so
that the policy applies to threads which were created during initialization as
well as threads created later. If Landlock was explicitly enabled and cannot be
installed, startup fails rather than continuing with incomplete confinement.

## Policies

Both policies allow reads from standard system roots, the active Python
installation, the current directory, `HOME`, and the XDG configuration, data,
cache, state and runtime directories.

The client may write only to its configured download directory and temporary
directories. It may create pathname Unix sockets only below those writable
directories. In particular, the normal client listener below
`XDG_RUNTIME_DIR` is expected to fail while the initial policy is being tested.

The server may write only to `XPRA_SESSION_DIR` and temporary directories.
Pathname Unix socket creation is denied after the server has created its network,
display and session sockets and launched its session D-Bus. Existing sockets
remain usable.

Both policies grant device access below `/dev/dri` and `/dev/accel`. This allows
graphics APIs and hardware codecs to open render nodes read/write and use
`ioctl`, without granting permission to create, remove or rename device nodes.

## Subprocesses and limitations

Landlock restrictions are inherited across `fork` and `exec`. Applications and
helpers started after confinement therefore receive the same policy. This
currently includes late server commands, audio helpers, printing helpers and
commands used to open downloaded files or URLs.

The socket restriction uses `LANDLOCK_ACCESS_FS_MAKE_SOCK`. It denies creation
of pathname Unix sockets, not the general `socket()` system call, TCP or UDP
sockets, or abstract Unix sockets. Network-port and IPC-scope restrictions are
not enabled.

Denied operations normally fail with `EACCES`. On kernels with Landlock audit
support, additional details may be available through the system audit log or
kernel journal. A file-focused trace can identify the denied operation and path:

```shell
strace -f -e trace=%file -o /tmp/xpra-landlock.strace env XPRA_LANDLOCK=1 xpra start :100
rg 'EACCES|EPERM' /tmp/xpra-landlock.strace
```

Add `network` to the trace expression when investigating socket failures.
