# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import WORKSPACE_UNSET, get_util_logger

SKIP_METADATA = os.environ.get("XPRA_SKIP_METADATA", "").split(",")


def make_window_metadata(window, propname, get_transient_for=None, get_window_id=None, skip_defaults=False) -> dict:
    try:
        return do_make_window_metadata(window, propname, get_transient_for, get_window_id, skip_defaults)
    except (ValueError, TypeError) as e:
        log = get_util_logger()
        log("make_window_metadata%s",
            (window, propname, get_transient_for, get_window_id, skip_defaults), exc_info=True)
        log.error("Error: failed to make window metadata")
        log.error(" for attribute '%s' of window %s", propname, window)
        log.error(" with value '%s':", getattr(window, propname, None))
        log.error(" %s", e)
        return {}


def do_make_window_metadata(window, propname, get_transient_for=None, get_window_id=None, skip_defaults=False) -> dict:
    if propname in SKIP_METADATA:
        return {}
    #note: some of the properties handled here aren't exported to the clients,
    #but we do expose them via xpra info
    def raw():
        return window.get_property(propname)
    if propname in ("title", "icon-title", "command", "content-type"):
        v = raw()
        if v is None:
            if skip_defaults:
                return {}
            return {propname: ""}
        return {propname: v.encode("utf-8")}
    if propname in ("pid", "workspace", "bypass-compositor", "depth", "opacity", "quality", "speed"):
        v = raw()
        assert v is not None, "%s is None!" % propname
        default_value = {
            "pid"               : 0,
            "workspace"         : WORKSPACE_UNSET,
            "bypass-compositor" : 0,
            "depth"             : 24,
            "opacity"           : 100,
            }.get(propname, -1)
        if (v<0 or v==default_value) and skip_defaults:
            #unset or default value,
            #so don't bother sending anything:
            return {}
        return {propname : v}
    if propname == "size-hints":
        #just to confuse things, this is renamed
        #and we have to filter out ratios as floats (already exported as pairs anyway)
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
        return {"strut": strut}
    if propname == "class-instance":
        c_i = raw()
        if c_i is None:
            return {}
        return {"class-instance": [x.encode("utf-8") for x in c_i]}
    if propname == "client-machine":
        client_machine = raw()
        if client_machine is None:
            import socket
            client_machine = socket.gethostname()
            if client_machine is None:
                return {}
        return {"client-machine": client_machine.encode("utf-8")}
    if propname == "transient-for":
        wid = None
        if get_transient_for:
            wid = get_transient_for(window)
        if wid:
            return {"transient-for" : wid}
        return {}
    if propname in ("window-type", "shape", "children"):
        v = raw()
        if not v and skip_defaults:
            return {}
        #always send unchanged:
        return {propname : raw()}
    if propname=="decorations":
        #-1 means unset, don't send it
        v = raw()
        if v<0:
            return {}
        return {propname : v}
    if propname in ("iconic", "fullscreen", "maximized",
                      "above", "below",
                      "shaded", "sticky",
                      "skip-taskbar", "skip-pager",
                      "modal", "focused",
                      ):
        v = raw()
        if v is False and skip_defaults:
            #we can skip those when the window is first created,
            #but not afterwards when those attributes are toggled
            return {}
        #always send these when requested
        return {propname : bool(raw())}
    if propname in ("has-alpha", "override-redirect", "tray", "shadow", "set-initial-position"):
        v = raw()
        if v is False and skip_defaults:
            #save space: all these properties are assumed false if unspecified
            return {}
        return {propname : v}
    if propname in ("role", "fullscreen-monitors"):
        v = raw()
        if v is None or v=="":
            return {}
        return {propname : v}
    if propname == "xid":
        return {"xid" : hex(raw() or 0)}
    if propname == "group-leader":
        gl = raw()
        if not gl or not get_window_id:
            return  {}
        xid, gdkwin = gl
        p = {}
        if xid:
            p["group-leader-xid"] = xid
        if gdkwin and get_window_id:
            glwid = get_window_id(gdkwin)
            if glwid:
                p["group-leader-wid"] = glwid
        return p
    #the properties below are not actually exported to the client (yet?)
    #it was just easier to handle them here
    #(convert to a type that can be encoded for xpra info):
    if propname in ("state", "protocols"):
        return {"state" : tuple(raw() or [])}
    if propname == "allowed-actions":
        return {"allowed-actions" : tuple(raw())}
    if propname == "frame":
        frame = raw()
        if not frame:
            return {}
        return {"frame" : tuple(frame)}
    raise Exception("unhandled property name: %s" % propname)
