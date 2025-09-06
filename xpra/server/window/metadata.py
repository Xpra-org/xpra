# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
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

    if propname in ("title", "icon-title", "command", "content-type"):
        v = raw()
        if v is None:
            if skip_defaults:
                return {}
            return {propname: ""}
        return {propname: v}
    if propname in (
        "pid", "ppid", "wm-pid",
        "workspace",
        "bypass-compositor", "depth", "opacity",
        "quality", "speed",
    ):
        v = raw()
        assert v is not None, "%s is None!" % propname
        default_value = {
            "pid": 0,
            "ppid": 0,
            "wm-pid": 0,
            "workspace": WORKSPACE_UNSET,
            "bypass-compositor": 0,
            "depth": 24,
            "opacity": 100,
        }.get(propname, -1)
        if (v < 0 or v == default_value) and skip_defaults:
            # unset or default value,
            # so don't bother sending anything:
            return {}
        return {propname: v}
    if propname == "size-hints":
        # just to confuse things, this attribute is renamed,
        # and we have to filter out ratios as floats (already exported as pairs anyway)
        v = dict(raw())
        return {"size-constraints": v}
    if propname == "strut":
        strut = raw()
        if not strut:
            strut = {}
        else:
            strut = strut.todict()
        if not strut and skip_defaults:
            return {}
        return {propname: strut}
    if propname == "class-instance":
        c_i = raw()
        if not c_i:
            return {}
        return {propname: c_i}
    if propname == "client-machine":
        client_machine = raw()
        if client_machine is None:
            client_machine = socket.gethostname()
            if not client_machine:
                return {}
        return {propname: client_machine}
    if propname in ("window-type", "shape", "children", "hwnd", "relative-position", "requested-position"):
        v = raw()
        if not v and skip_defaults:
            return {}
        # always send unchanged:
        return {propname: raw()}
    if propname == "decorations":
        # -1 means unset, don't send it
        v = raw()
        if v < 0:
            return {}
        return {propname: v}
    if propname in (
            "iconic", "fullscreen", "maximized",
            "above", "below",
            "shaded", "sticky",
            "skip-taskbar", "skip-pager",
            "modal", "focused",
    ):
        v = raw()
        if v is False and skip_defaults:
            # we can skip those when the window is first created,
            # but not afterwards when those attributes are toggled
            return {}
        # always send these when requested
        return {propname: bool(raw())}
    if propname in ("has-alpha", "override-redirect", "tray", "shadow", "set-initial-position"):
        v = raw()
        if not v and skip_defaults:
            # save space: all these properties are assumed false if unspecified
            return {}
        return {propname: v}
    if propname in ("role", "fullscreen-monitors"):
        v = raw()
        if v is None or v == "":
            return {}
        return {propname: v}
    if propname == "xid":
        return {propname: raw() or 0}
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
    # the properties below are not all actually exported to the client
    # but `opaque-region` is, and the others are exported via `xpra info`:
    if propname in ("state", "protocols", "opaque-region"):
        return {propname: tuple(raw() or ())}
    if propname == "allowed-actions":
        return {propname: tuple(raw())}
    if propname == "frame":
        frame = raw()
        if not frame:
            return {}
        return {propname: tuple(frame)}
    raise ValueError(f"unhandled property name: {propname}")
