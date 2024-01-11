#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import uuid
import struct

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


GIR_VERSIONS : dict[str, str] = {
    "Gtk": "3.0",
    "Gdk": "3.0",
    "GdkX11" : "3.0",
    "Pango": "1.0",
    "PangoCairo" : "1.0",
    "GLib": "2.0",
    "GObject": "2.0",
    "GdkPixbuf": "2.0",
    "Gio": "2.0",
    "Rsvg": "2.0",
    "Gst": "1.0",
}


def gi_import(mod="Gtk", version=""):
    version = version or GIR_VERSIONS.get(mod, "")
    from xpra.util.env import SilenceWarningsContext
    with SilenceWarningsContext(DeprecationWarning, ImportWarning):
        import gi
        gi.require_version(mod, version)
        import importlib
        return importlib.import_module(f"gi.repository.{mod}")


def getuid() -> int:
    if POSIX:
        return os.getuid()
    return 0


def getgid() -> int:
    if POSIX:
        return os.getgid()
    return 0


def get_shell_for_uid(uid) -> str:
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_shell
        except KeyError:
            pass
    return ""


def get_username_for_uid(uid) -> str:
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_name
        except KeyError:
            pass
    return ""


def get_home_for_uid(uid) -> str:
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_dir
        except KeyError:
            pass
    return ""


def get_groups(username) -> list[str]:
    if POSIX:
        import grp
        return [gr.gr_name for gr in grp.getgrall() if username in gr.gr_mem]
    return []


def get_group_id(group) -> int:
    try:
        import grp
        gr = grp.getgrnam(group)
        return gr.gr_gid
    except (ImportError, KeyError):
        return -1


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
            if b is not None:
                from xpra.util.str_fn import bytestostr
                v = bytestostr(b)
                break
    elif WIN32:
        v = str(uuid.getnode())
    return v.strip("\n\r")


def get_user_uuid() -> str:
    """
        Try to generate an uuid string which is unique to this user.
        (relies on get_machine_id to uniquely identify a machine)
    """
    user_uuid = os.environ.get("XPRA_USER_UUID")
    if user_uuid:
        return user_uuid
    import hashlib
    u = hashlib.sha256()

    def uupdate(ustr):
        u.update(ustr.encode("utf-8"))
    uupdate(get_machine_id())
    if POSIX:
        uupdate("/")
        uupdate(str(os.getuid()))
        uupdate("/")
        uupdate(str(os.getgid()))
    uupdate(os.path.expanduser("~/"))
    return u.hexdigest()


# here so we can override it when needed
def force_quit(status=1) -> None:
    os._exit(int(status))  # pylint: disable=protected-access


def no_idle(fn, *args, **kwargs):
    fn(*args, **kwargs)
