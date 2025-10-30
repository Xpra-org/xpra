#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import uuid
import struct
from types import ModuleType
from typing import NoReturn

# only minimal imports go at the top
# so that this file can be included everywhere
# without too many side effects
# pylint: disable=import-outside-toplevel

WIN32: bool = sys.platform.startswith("win")
OSX: bool = sys.platform.startswith("darwin")
LINUX: bool = sys.platform.startswith("linux")
NETBSD: bool = sys.platform.startswith("netbsd")
OPENBSD: bool = sys.platform.startswith("openbsd")
FREEBSD: bool = sys.platform.startswith("freebsd")
POSIX: bool = os.name == "posix"
BITS: int = struct.calcsize(b"P")*8

GI_BLOCK = tuple(x for x in os.environ.get("XPRA_GI_BLOCK", "").split(",") if x)

GIR_VERSIONS: dict[str, str] = {
    "Gtk": "3.0",
    "Gdk": "3.0",
    "GdkX11": "3.0",
    "Pango": "1.0",
    "PangoCairo": "1.0",
    "GLib": "2.0",
    "GObject": "2.0",
    "GdkPixbuf": "2.0",
    "IBus": "1.0",
    "Gio": "2.0",
    "Rsvg": "2.0",
    "Gst": "1.0",
    "NM": "1.0",
    "GtkosxApplication": "1.0",
    "Notify": "0.7",
}


def gi_import(mod="Gtk", version="") -> ModuleType:
    if mod in GI_BLOCK or "*" in GI_BLOCK:
        raise ImportError(f"import of {mod!r} is blocked")
    version = version or GIR_VERSIONS.get(mod, "")
    from xpra.util.env import SilenceWarningsContext
    with SilenceWarningsContext(DeprecationWarning, ImportWarning):
        import gi
        try:
            gi.require_version(mod, version)
        except (ValueError, AssertionError) as e:
            raise ImportError(f"unable to import {mod!r} {version=!r}: {e}") from None
        import importlib
        return importlib.import_module(f"gi.repository.{mod}")


def is_container() -> bool:
    if os.getpid() == 1:
        return True
    from xpra.util.io import load_binary_file
    cg = load_binary_file("/proc/1/cgroup")
    if any(cg.find(pattern) >= 0 for pattern in (b"docker", b"container", )):
        return True
    from xpra.util.env import get_saved_env
    return bool(get_saved_env().get("container"))


def is_admin() -> bool:
    if WIN32:
        from ctypes import windll
        return windll.shell32.IsUserAnAdmin() != 0
    return os.geteuid() == 0


def getuid() -> int:
    if POSIX:
        return os.getuid()
    return 0


def getgid() -> int:
    if POSIX:
        return os.getgid()
    return 0


def get_shell_for_uid(uid: int) -> str:
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_shell
        except KeyError:
            pass
    return ""


def get_username_for_uid(uid: int) -> str:
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_name
        except KeyError:
            pass
    return ""


def get_home_for_uid(uid: int) -> str:
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_dir
        except KeyError:
            pass
    return ""


def get_groups(username: str) -> list[str]:
    if POSIX:
        import grp
        return [gr.gr_name for gr in grp.getgrall() if username in gr.gr_mem]
    return []


def get_group_id(group: str) -> int:
    try:
        import grp
        gr = grp.getgrnam(group)
        return gr.gr_gid
    except (ImportError, KeyError):
        return -1


def find_group(uid: int) -> int:
    # try harder to use a valid group,
    # since we're going to chown files:
    username = get_username_for_uid(uid)
    groups = get_groups(username)
    from xpra.common import GROUP
    if GROUP in groups:
        return get_group_id(GROUP)
    try:
        import pwd
        pw = pwd.getpwuid(uid)
        return pw.pw_gid
    except KeyError:
        if groups:
            return get_group_id(groups[0])
        return os.getgid()


def get_hex_uuid() -> str:
    return uuid.uuid4().hex


def get_int_uuid() -> int:
    return uuid.uuid4().int


def get_machine_id() -> str:
    """
        Try to get uuid string which uniquely identifies this machine.
        Warning: only works on posix!
        (which is ok since we only used it on posix at present)
    """
    v = ""
    if POSIX:
        from xpra.util.io import load_binary_file
        for filename in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            b = load_binary_file(filename)
            if b:
                v = b.decode("latin1")
                break
    elif WIN32:
        v = str(uuid.getnode())
    return v.strip("\n\r")


def get_user_uuid() -> str:
    """
        Try to generate an uuid string which is unique to this user.
        (relies on get_machine_id to uniquely identify a machine)
    """
    user_uuid = os.environ.get("XPRA_USER_UUID", "")
    if user_uuid:
        return user_uuid
    import hashlib
    u = hashlib.sha256()

    def uupdate(val: int | str) -> None:
        u.update(str(val).encode("utf-8"))
    uupdate(get_machine_id())
    if POSIX:
        uupdate("/")
        uupdate(os.getuid())
        uupdate("/")
        uupdate(os.getgid())
        uupdate("/")
        uupdate(os.environ.get("DISPLAY", "") or os.environ.get("WAYLAND_DISPLAY", ""))
    uupdate(os.path.expanduser("~/"))
    return u.hexdigest()


# here so we can override it when needed
def force_quit(status=1) -> NoReturn:
    # noinspection PyProtectedMember
    os._exit(int(status))  # pylint: disable=protected-access


def is_arm() -> bool:
    import platform
    return platform.uname()[4].startswith("arm")


def crash() -> NoReturn:
    import ctypes  # pylint: disable=import-outside-toplevel
    ctypes.string_at(0)
