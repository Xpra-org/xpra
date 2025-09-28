#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.shadow.root_window_model import CaptureWindowModel


class X11ShadowModel(CaptureWindowModel):
    __slots__ = ("xid", "override_redirect", "transient_for", "parent", "relative_position")

    def __init__(self, capture=None, title="", geometry=None):
        super().__init__(capture, title, geometry)
        self.property_names += ["transient-for", "parent", "relative-position"]
        self.dynamic_property_names += ["transient-for", "parent", "relative-position"]
        self.override_redirect: bool = False
        self.transient_for = None
        self.parent = None
        self.relative_position = ()
        try:
            from xpra.x11.bindings.core import X11CoreBindings
            self.xid = X11CoreBindings().get_root_xid()
            self.property_names.append("xid")
        except Exception:
            self.xid = 0

    def get_id(self) -> int:
        return self.xid

    def __repr__(self) -> str:
        info = ", OR" if self.override_redirect else ""
        return f"X11ShadowModel({self.capture} : {self.geometry} : {self.xid:x}{info})"
