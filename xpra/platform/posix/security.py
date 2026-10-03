#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import ctypes
import os
import resource
import shutil
import stat
import sys
import sysconfig
import tempfile
from collections.abc import Iterator

from xpra.log import Logger

log = Logger("server")

PR_SET_DUMPABLE = 4

SYSTEM_READ_PATHS: tuple[str, ...] = (
    "/bin", "/sbin", "/lib", "/lib64", "/usr", "/etc", "/opt",
    "/run", "/var", "/proc", "/sys", "/dev",
)


def _get_libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    libc.prctl.restype = ctypes.c_int
    libc.madvise.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.madvise.restype = ctypes.c_int
    return libc


def _raise_oserror(operation: str) -> None:
    errno = ctypes.get_errno()
    raise OSError(errno, f"{operation} failed: {os.strerror(errno)}")


def disable_ptrace(libc=None) -> None:
    """Prevent unprivileged processes from inspecting this process."""
    libc = libc or _get_libc()
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        _raise_oserror("prctl(PR_SET_DUMPABLE)")


def disable_core_dumps() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def writable_private_mappings(maps_path: str = "/proc/self/maps") -> Iterator[tuple[int, int]]:
    """Yield writable private mappings which may contain process secrets."""
    with open(maps_path, encoding="latin1") as maps:
        for line in maps:
            fields = line.split(None, 2)
            if len(fields) < 2:
                continue
            address, permissions = fields[:2]
            if len(permissions) < 4 or permissions[1] != "w" or permissions[3] != "p":
                continue
            try:
                start_text, end_text = address.split("-", 1)
                start = int(start_text, 16)
                end = int(end_text, 16)
            except ValueError:
                continue
            if end > start:
                yield start, end


def mark_memory_nondumpable(libc=None, maps_path: str = "/proc/self/maps") -> tuple[int, int]:
    """Apply MADV_DONTDUMP to the process's writable private mappings."""
    try:
        # mmap may not be available
        import mmap
    except ImportError:
        return 0, 0
    dontdump = getattr(mmap, "MADV_DONTDUMP", 0)
    if not dontdump:
        return 0, 0
    libc = libc or _get_libc()
    marked = failed = 0
    for start, end in writable_private_mappings(maps_path):
        if libc.madvise(start, end - start, dontdump) == 0:
            marked += 1
        else:
            failed += 1
    return marked, failed


def harden_process() -> None:
    """Protect server credentials and encryption keys held in process memory."""
    disable_ptrace()
    disable_core_dumps()
    try:
        marked, failed = mark_memory_nondumpable()
    except OSError as e:
        log.warn("Warning: unable to exclude process memory from core dumps:")
        log.warn(" %s", e)
    else:
        log("marked %i writable private memory mappings MADV_DONTDUMP", marked)
        if failed:
            log.warn("Warning: failed to mark %i memory mappings MADV_DONTDUMP", failed)


def get_landlock_read_paths() -> tuple[str, ...]:
    """Return the system, interpreter and per-user roots Xpra may read."""
    paths: list[str] = list(SYSTEM_READ_PATHS)
    paths += [
        os.getcwd(),
        os.environ.get("HOME", "~"),
        os.environ.get("XDG_CONFIG_HOME", "~/.config"),
        os.environ.get("XDG_CACHE_HOME", "~/.cache"),
        os.environ.get("XDG_DATA_HOME", "~/.local/share"),
        os.environ.get("XDG_STATE_HOME", "~/.local/state"),
        os.environ.get("XDG_RUNTIME_DIR", ""),
        sys.prefix,
        sys.base_prefix,
        os.path.dirname(sys.executable),
    ]
    for name, default in (
        ("XDG_CONFIG_DIRS", "/etc/xdg"),
        ("XDG_DATA_DIRS", "/usr/local/share:/usr/share"),
    ):
        paths += os.environ.get(name, default).split(os.pathsep)
    for path in sys.path:
        paths.append(path or os.getcwd())
    return tuple(paths)


def get_landlock_temp_paths() -> tuple[str, ...]:
    from xpra.platform.paths import get_xpra_tmp_dir
    return tempfile.gettempdir(), get_xpra_tmp_dir()


def get_landlock_device_paths() -> tuple[str, ...]:
    """Return graphics and terminal devices, without granting node creation."""
    return "/dev/dri", "/dev/accel", "/dev/pts", "/dev/ptmx", "/dev/tty"


def check_landlock_directory(path: str) -> None:
    """Refuse directory grants that undo strict confinement."""
    from xpra.platform.posix.landlock import canonical_paths
    canonical, = canonical_paths((path,))
    home, = canonical_paths((os.path.expanduser("~"),))
    forbidden = canonical_paths(("/", home, "/tmp", "/var/tmp", "/dev/shm"))
    if canonical in forbidden or os.path.commonpath((canonical, home)) == canonical:
        raise ValueError(f"strict Landlock requires a dedicated directory, not {path!r}")


def get_strict_landlock_read_paths() -> tuple[str, ...]:
    from xpra import __file__ as xpra_file
    from xpra.platform.paths import get_resources_dir, get_user_conf_dirs
    paths = list(SYSTEM_READ_PATHS[:7]) + [
        "/sys", "/proc/self", "/proc/version", "/proc/sys/kernel/osrelease", "/proc/driver/nvidia/version",
        "/var/cache/xpra/menu-icons", sys.executable, os.path.dirname(xpra_file),
    ]
    if sys.argv and os.path.isfile(sys.argv[0]):
        paths.append(sys.argv[0])
    # Use the actual runtime directories, not sys.prefix or sys.path (which may
    # be HOME, CWD or the filesystem root).
    paths += [sysconfig.get_path(name) for name in ("stdlib", "platstdlib", "purelib", "platlib")]
    resources = get_resources_dir()
    # The resource finder falls back to CWD if no installation is found.
    if os.path.realpath(resources) != os.path.realpath(os.getcwd()):
        paths.append(resources)
    paths += get_user_conf_dirs()
    for name, default, leaves in (
        ("XDG_CONFIG_HOME", "~/.config", ("gtk-3.0", "gtk-4.0", "fontconfig", "pulse")),
        ("XDG_DATA_HOME", "~/.local/share", ("fonts", "icons", "themes")),
    ):
        paths += [os.path.join(os.environ.get(name, default), leaf) for leaf in leaves]
    paths += ["~/.fonts", "~/.icons", "~/.themes", os.environ.get("XAUTHORITY", "~/.Xauthority")]
    return tuple(paths)


def get_landlock_auth_paths(opts) -> tuple[str, ...]:
    """Return authentication files explicitly configured in the options."""
    required: list[str] = []
    for path in (opts.ssl_cert, opts.ssl_key, opts.ssl_ca_certs, opts.encryption_keyfile,
                 opts.tcp_encryption_keyfile, opts.clipboard_filter_file):
        if path and path not in ("auto", "default"):
            required.append(path)
    required += list(opts.password_file or ())
    return tuple(required)


def get_landlock_mmap_paths(mmap: str) -> tuple[str, ...]:
    """Return writable resources for explicitly configured shared mmap paths."""
    from xpra.net.mmap.common import split_paths
    paths = []
    for path in split_paths(mmap):
        if os.path.isabs(path):
            # Existing files receive file rules; new files need their parent.
            paths.append(path if os.path.exists(path) else os.path.dirname(path))
    return tuple(paths)


def get_connection_landlock_auth_paths(display_desc) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return optional default and required target-specific authentication files."""
    optional: list[str] = []
    required: list[str] = []
    desc = display_desc or {}
    for name in ("cert", "key", "ca-certs"):
        path = desc.get("ssl-options", {}).get(name, "")
        if path and path not in ("auto", "default"):
            required.append(path)
    if desc.get("type") == "ssh":
        from xpra.net.ssh.util import get_default_keyfiles
        from xpra.platform.paths import get_ssh_conf_dirs, get_ssh_known_hosts_files
        optional += get_default_keyfiles() + get_ssh_known_hosts_files()
        optional += [os.path.join(path, "config") for path in get_ssh_conf_dirs()]
        config = dict(desc)
        config.update(desc.get("paramiko-config", {}))
        for name in ("key", "proxy_key"):
            if config.get(name):
                required.append(config[name])
        # Resolve host-specific identities before confinement; grant files, not
        # the SSH directory containing other credentials.
        try:
            from xpra.net.ssh.paramiko.client import load_ssh_config, safe_lookup
        except ImportError:
            # External OpenSSH can be used without the optional Paramiko dependency.
            pass
        else:
            ssh_config = load_ssh_config()
            for host in (desc.get("host"), desc.get("proxy_host")):
                if host:
                    optional += safe_lookup(ssh_config, host).get("identityfile", [])
        args = list(desc.get("full_ssh", ()))
        for index, arg in enumerate(args):
            if arg in ("-i", "-F") and index + 1 < len(args):
                required.append(args[index + 1])
            elif arg.startswith(("-i", "-F")) and len(arg) > 2:
                required.append(arg[2:])
    return tuple(optional), tuple(required)


def get_landlock_socket_paths() -> tuple[str, ...]:
    paths = [os.environ.get("SSH_AUTH_SOCK", ""), os.environ.get("XPRA_SERVER_SOCKET", ""),
             "/run/dbus/system_bus_socket"]
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime:
        paths += [os.path.join(runtime, "bus"), os.path.join(runtime, "pulse", "native")]
        if wayland := os.environ.get("WAYLAND_DISPLAY", ""):
            paths.append(os.path.join(runtime, wayland))
    addresses = ";".join(os.environ.get(name, "") for name in ("DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS"))
    for address in addresses.split(";"):
        if address.startswith("unix:"):
            from urllib.parse import unquote
            for item in address[5:].split(","):
                if item.startswith("path="):
                    paths.append(unquote(item[5:]))
    display = os.environ.get("DISPLAY", "")
    if display.startswith(":"):
        paths.append("/tmp/.X11-unix/X" + display[1:].split(".")[0])
    return tuple(paths)


def cleanup_landlock_temp_dir(path: str, owner: int) -> None:
    """Release one subsystem's temp storage, leaving its parent's storage alone."""
    if not path or owner != os.getpid():
        return
    shutil.rmtree(path, ignore_errors=True)
    if os.environ.get("XPRA_LANDLOCK_TMP_DIR") == path:
        os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
        os.environ.pop("XPRA_LANDLOCK_TMP_OWNER", None)
        for name in ("XPRA_TMP_DIR", "TMPDIR", "TMP", "TEMP"):
            if os.environ.get(name) == path:
                os.environ.pop(name)
    if tempfile.tempdir == path:
        tempfile.tempdir = None


def _check_landlock_temp_dir(parent: str, path: str) -> None:
    if os.path.commonpath((parent, path)) != parent or path == parent:
        raise ValueError("Landlock temporary directory must be inside the application write directory")
    info = os.stat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Landlock temporary directory must be an owned directory with mode 0700")


def prepare_landlock_temp_dir(parent: str) -> tuple[str, int]:
    """Create private temp storage inside an already writable application root."""
    from xpra.platform.posix.landlock import canonical_paths
    parent, = canonical_paths((parent,))
    check_landlock_directory(parent)
    path = os.environ.get("XPRA_LANDLOCK_TMP_DIR", "")
    owner = int(os.environ.get("XPRA_LANDLOCK_TMP_OWNER", "0") or "0")
    if path:
        path, = canonical_paths((path,))
        _check_landlock_temp_dir(parent, path)
    else:
        os.makedirs(parent, mode=0o700, exist_ok=True)
        path = tempfile.mkdtemp(prefix=".xpra-tmp-", dir=parent)
        owner = os.getpid()
    # Helpers inherit these paths but do not own their parent's storage.
    os.environ.update({"XPRA_LANDLOCK_TMP_DIR": path, "XPRA_LANDLOCK_TMP_OWNER": str(owner),
                       "XPRA_TMP_DIR": path, "TMPDIR": path, "TMP": path, "TEMP": path})
    tempfile.tempdir = path
    return path, owner


def enforce_landlock(mode: str, write_paths=(), *, read_paths=(), socket_paths=(), socket_dirs=(),
                     cleanup_dirs=(), required_paths=(), temp_dir: str = "", allow_socket_creation: bool) -> int:
    """Install Xpra's opt-in process-wide Landlock filesystem policy."""
    if mode == "no":
        return 0
    if mode not in ("default", "strict"):
        raise ValueError(f"invalid Landlock mode {mode!r}")
    from xpra.platform.posix.landlock import FSAccess, READ_ACCESS, canonical_paths, restrict_paths
    write_paths = canonical_paths(write_paths)
    read_paths = tuple(read_paths)
    required_paths = tuple(required_paths)
    access = READ_ACCESS
    if mode == "strict":
        read_paths += get_strict_landlock_read_paths()
        for path in canonical_paths(read_paths):
            check_landlock_directory(path)
        for path in canonical_paths(tuple(write_paths) + tuple(socket_dirs) + tuple(cleanup_dirs)):
            check_landlock_directory(path)
        for path in canonical_paths(required_paths):
            if not os.path.exists(path):
                raise FileNotFoundError(f"required Landlock resource does not exist: {path}")
        if not write_paths:
            raise ValueError("strict Landlock requires a dedicated application write directory")
        for path in write_paths:
            if not os.path.isfile(path):
                os.makedirs(path, mode=0o700, exist_ok=True)
        if not temp_dir:
            raise ValueError("strict Landlock requires prepared private temporary storage")
        temp_paths = canonical_paths((temp_dir,))
        _check_landlock_temp_dir(write_paths[0], temp_paths[0])
        socket_paths = tuple(socket_paths) + get_landlock_socket_paths()
        access = FSAccess.EXECUTE | FSAccess.READ_FILE | FSAccess.READ_DIR
    else:
        read_paths += get_landlock_read_paths()
        temp_paths = get_landlock_temp_paths()
        for path in write_paths + temp_paths:
            if not os.path.isfile(path):
                os.makedirs(path, mode=0o700, exist_ok=True)
    Logger("landlock")("installing %s Landlock policy", mode)
    return restrict_paths(
        read_paths, write_paths + temp_paths,
        device_paths=get_landlock_device_paths() + ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"),
        socket_paths=socket_paths, socket_dirs=socket_dirs, cleanup_dirs=cleanup_dirs,
        required_paths=required_paths + write_paths + temp_paths + tuple(socket_dirs), read_access=access,
        allow_socket_creation=allow_socket_creation,
        sync_threads=True,
    )
