# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.gtk.prop import prop_set, prop_get, prop_del
from xpra.gtk.util import get_default_root_window


def root_xid() -> int:
    root = get_default_root_window()
    if not root:
        return 0
    return root.get_xid()


def save_uuid(uuid: str) -> None:
    prop_set(root_xid(), "XPRA_SERVER_UUID", "latin1", uuid)


def get_uuid() -> str:
    return prop_get(root_xid(), "XPRA_SERVER_UUID", "latin1", ignore_errors=True) or ""


def del_uuid() -> None:
    prop_del(root_xid(), "XPRA_SERVER_UUID")


def save_mode(mode: str) -> None:
    prop_set(root_xid(), "XPRA_SERVER_MODE", "latin1", mode)


def get_mode() -> str:
    return prop_get(root_xid(), "XPRA_SERVER_MODE", "latin1", ignore_errors=True) or ""


def del_mode() -> None:
    prop_del(root_xid(), "XPRA_SERVER_MODE")
