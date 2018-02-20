# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("server")
metalog = Logger("metadata")

from xpra.util import WORKSPACE_UNSET

SKIP_METADATA = os.environ.get("XPRA_SKIP_METADATA", "").split(",")


def make_window_metadata(window, propname, get_transient_for=None, get_window_id=None):
    if propname in SKIP_METADATA:
        return {}
    #note: some of the properties handled here aren't exported to the clients,
    #but we do expose them via xpra info
    def raw():
        return window.get_property(propname)
    if propname in ("title", "icon-title", "command", "content-type"):
        v = raw()
        if v is None:
            return {propname: ""}
        return {propname: v.encode("utf-8")}
    elif propname in ("pid", "workspace", "bypass-compositor", "depth"):
        v = raw()
        assert v is not None, "%s is None!" % propname
        if v<0 or (v==WORKSPACE_UNSET and propname=="workspace"):
            #meaningless
            return {}
        return {propname : v}
    elif propname == "size-hints":
        #just to confuse things, this is renamed
        #and we have to filter out ratios as floats (already exported as pairs anyway)
        v = dict((k,v) for k,v in raw().items() if k not in("max_aspect", "min_aspect"))
        return {"size-constraints": v}
    elif propname == "strut":
        strut = raw()
        if not strut:
            strut = {}
        else:
            strut = strut.todict()
        return {"strut": strut}
    elif propname == "class-instance":
        c_i = raw()
        if c_i is None:
            return {}
        return {"class-instance": [x.encode("utf-8") for x in c_i]}
    elif propname == "client-machine":
        client_machine = raw()
        if client_machine is None:
            import socket
            client_machine = socket.gethostname()
            if client_machine is None:
                return {}
        return {"client-machine": client_machine.encode("utf-8")}
    elif propname == "transient-for":
        wid = None
        if get_transient_for:
            wid = get_transient_for(window)
        if wid:
            return {"transient-for" : wid}
        return {}
    elif propname in ("window-type", "shape", "menu"):
        #always send unchanged:
        return {propname : raw()}
    elif propname in ("decorations", ):
        #-1 means unset, don't send it
        v = raw()
        if v<0:
            return {}
        return {propname : v}
    elif propname in ("iconic", "fullscreen", "maximized", "above", "below", "shaded", "sticky", "skip-taskbar", "skip-pager", "modal", "focused"):
        #always send these when requested
        return {propname : bool(raw())}
    elif propname in ("has-alpha", "override-redirect", "tray", "shadow", "set-initial-position"):
        v = raw()
        if v is False:
            #save space: all these properties are assumed false if unspecified
            return {}
        return {propname : v}
    elif propname in ("role", "opacity", "fullscreen-monitors"):
        v = raw()
        if v is None or v=="":
            return {}
        return {propname : v}
    elif propname == "xid":
        return {"xid" : hex(raw() or 0)}
    elif propname == "group-leader":
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
    elif propname in ("state", "protocols"):
        return {"state" : tuple(raw() or [])}
    elif propname == "allowed-actions":
        return {"allowed-actions" : tuple(raw())}
    elif propname == "frame":
        frame = raw()
        if not frame:
            return {}
        return {"frame" : tuple(frame)}
    raise Exception("unhandled property name: %s" % propname)
