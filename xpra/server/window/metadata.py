# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable

from xpra.util.io import get_util_logger
from xpra.common import WORKSPACE_UNSET

SKIP_METADATA = os.environ.get("XPRA_SKIP_METADATA", "").split(",")


def make_window_metadata(window,
                         propname: str,
                         get_window_id: Callable[[Any], int] | None = None,
                         skip_defaults=False,
                         ) -> dict[str, Any]:
    try:
        return _make_window_metadata(window, propname, get_window_id, skip_defaults)
    except (ValueError, TypeError) as e:
        log = get_util_logger()
        log("make_window_metadata%s",
            (window, propname, get_window_id, skip_defaults), exc_info=True)
        log.error("Error: failed to make window metadata")
        log.error(" for attribute '%s' of window %s", propname, window)
        log.error(" with value '%s':", getattr(window, propname, None))
        log.estr(e)
        return {}


DEFAULT_VALUES: dict[str: int | str | bool | tuple | dict] = {
    "title": "",
    "icon-title": "",
    "command": "",
    "content-type": "",
    "pid": 0,
    "ppid": 0,
    "wm-pid": 0,
    "workspace": WORKSPACE_UNSET,
    "bypass-compositor": 0,
    "depth": 24,
    "opacity": 100,
    "quality": -1,
    "speed": -1,
    "decorations": -1,
    "role": "",
    "client-machine": "",
    "window-type": "",
    "hwnd": 0,
    "xid": 0,
    "iconic": False,
    "fullscreen": False,
    "maximized": False,
    "above": False,
    "below": False,
    "shaded": False,
    "sticky": False,
    "skip-taskbar": False,
    "skip-pager": False,
    "modal": False,
    "focused": False,
    "has-alpha": False,
    "override-redirect": False,
    "tray": False,
    "shadow": False,
    "set-initial-position": False,
    "allowed-actions": (),
    "protocols": (),
    "state": (),
    "fullscreen-monitors": (),
    "opaque-region": (),
    "class-instance": (),
    "requested-position": (),
    "relative-position": (),
    "children": (),
    "frame": (),
    "shape": {},
    "size-constraints": {},
    "strut": {},
}


def _make_window_metadata(window,
                          propname: str,
                          get_window_id: Callable[[Any], int] | None = None,
                          skip_defaults=False,
                          ) -> dict[str, Any]:
    if propname in SKIP_METADATA:
        return {}

    # note: some of the properties handled here aren't exported to the clients,
    # but we do expose them via xpra info

    def raw():
        return window.get_property(propname)

    if propname in DEFAULT_VALUES:
        v = raw()
        if skip_defaults and v in (DEFAULT_VALUES[propname], None):
            return {}
        return {propname: v}
    if propname == "strut":
        strut = raw()
        if not strut:
            strut = {}
        else:
            strut = strut.todict()
        if not strut and skip_defaults:
            return {}
        return {propname: strut}
    if propname in ("group-leader", "transient-for", "parent"):
        ref_window = raw()
        if not ref_window:
            return {}
        p = {}
        if hasattr(ref_window, "get_xid"):
            # for Gdk X11 windows:
            p["%s-xid" % propname] = ref_window.get_xid()
        if get_window_id:
            wid = get_window_id(ref_window)
            if wid:
                if propname == "group-leader":
                    p["%s-wid" % propname] = wid
                else:
                    p[propname] = wid
        return p
    raise ValueError(f"unhandled property name: {propname}")
