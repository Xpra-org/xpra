#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
from typing import Any

from xpra.x11.error import xsync
from xpra.x11.prop import prop_get
from xpra.log import Logger

log = Logger("shadow")


def matchre(re_str: str, xid_dict: dict) -> list[int]:
    xids: list[int] = []
    try:
        re_c = re.compile(re_str, re.IGNORECASE)
    except re.error:
        log.error("Error: invalid window regular expression %r", re_str)
    else:
        for wxid, vstr in xid_dict.items():
            if re_c.match(vstr):
                xids.append(wxid)
    return xids


def i(v: str) -> int:
    try:
        if v.startswith("0x"):
            return int(v, 16)
        return int(v)
    except ValueError:
        return 0


def get_pid(xid: int) -> int:
    try:
        from xpra.x11.bindings.res import ResBindings  # pylint: disable=import-outside-toplevel
    except ImportError:
        return 0
    XRes = ResBindings()
    if not XRes.check_xres():
        return 0
    return XRes.get_pid(xid)


def window_matches(wspec, model_class):
    wspec = list(wspec)
    try:
        wspec.remove("skip-children")
    except ValueError:
        skip_children = False
    else:
        skip_children = True
    from xpra.x11.bindings.window import X11WindowBindings
    wb = X11WindowBindings()
    with xsync:
        allw: list[int] = [wxid for wxid in wb.get_all_x11_windows() if
                           not wb.is_inputonly(wxid) and wb.is_mapped(wxid)]
        names: dict[int, str] = {}
        commands: dict[int, str] = {}
        classes: dict[int, str] = {}
        for wxid in allw:
            name = prop_get(wxid, "_NET_WM_NAME", "utf8", True) or prop_get(wxid, "WM_NAME", "latin1", True)
            if name:
                names[wxid] = name
            command = prop_get(wxid, "WM_COMMAND", "latin1", True)
            if command:
                commands[wxid] = command.strip("\0")
            from xpra.x11.bindings.classhint import XClassHintBindings
            class_instance = XClassHintBindings().getClassHint(wxid)
            if class_instance:
                classes[wxid] = class_instance[0].decode("latin1")

        windows: list[int] = []
        skip: list[int] = []
        for m in wspec:
            xids = []
            if m.startswith("xid="):
                m = m[4:]
            xid = i(m)
            if xid:
                xids.append(xid)
            elif m.startswith("pid="):
                pid = i(m[4:])
                if pid:
                    for xid in names:
                        if get_pid(xid) == pid:
                            xids.append(xid)
            elif m.startswith("command="):
                command = m[len("command="):]
                xids += matchre(command, commands)
            elif m.startswith("class="):
                _class = m[len("class="):]
                xids += matchre(_class, classes)
            else:
                # assume this is a window name:
                xids += matchre(m, names)
            for xid in sorted(xids):
                if xid in skip:
                    continue
                # log.info("added %s", hex(xid))
                windows.append(xid)
                if skip_children:
                    children = wb.get_all_children(xid)
                    skip += children
        models = {}
        for xid in windows:
            geom = wb.getGeometry(xid)
            if not geom:
                continue
            x, y, w, h = geom[:4]
            # absp = wb.get_absolute_position(xid)
            if w > 0 and h > 0:
                title = names.get(xid, "unknown window")
                model = model_class(title, (x, y, w, h))
                models[xid] = model
        log("window_matches(%s, %s)=%s", wspec, model_class, models)
        position_models(models)
        return models.values()


def position_models(models: dict[int, Any]) -> None:
    from xpra.x11.bindings.window import X11WindowBindings
    wb = X11WindowBindings()
    # find relative position and 'transient-for':
    for xid, model in models.items():
        model.xid = xid
        model.override_redirect = wb.is_override_redirect(xid)
        model.transient_for = prop_get(xid, "WM_TRANSIENT_FOR", "window", True) or 0
        rel_parent = model.transient_for
        if not rel_parent:
            parent = xid
            rel_parent = None
            while parent > 0:
                parent = wb.getParent(parent)
                rel_parent = models.get(parent)
                if rel_parent:
                    log.warn(f"Warning: {rel_parent} is the parent of {model}")
                    break
        model.parent = rel_parent
        # "class-instance", "client-machine", "window-type",
        if rel_parent:
            parent_g = rel_parent.get_geometry()
            dx = model.geometry[0] - parent_g[0]
            dy = model.geometry[1] - parent_g[1]
            model.relative_position = dx, dy
            log("relative_position=%s", model.relative_position)
