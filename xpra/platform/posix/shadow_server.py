# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Optional, Type

from xpra.util import envbool
from xpra.log import Logger

def warn(*messages) -> None:
    log = Logger("server")
    log("warning loading backend", exc_info=True)
    for m in messages:
        log.warn(m)

def load_screencast() -> Optional[Type]:
    if envbool("XPRA_SHADOW_SCREENCAST", True):
        try:
            from xpra.platform.posix import screencast
            return screencast.ScreenCast
        except ImportError as e:
            warn("Warning: unable to load the screencast backend",
                 f" {e}")
    return None

def load_remotedesktop() -> Optional[Type]:
    if envbool("XPRA_SHADOW_REMOTEDESKTOP", True):
        try:
            from xpra.platform.posix import remotedesktop
            return remotedesktop.RemoteDesktop
        except ImportError as e:
            warn("Warning: unable to load the remotedesktop backend",
                 f" {e}")
    return None

def load_shadow_wayland(display_name=None) -> Optional[Type]:
    c = load_remotedesktop() or load_screencast()
    if c:
        os.environ["GDK_BACKEND"] = "wayland"
        if display_name:
            os.environ["WAYLAND_DISPLAY"] = display_name
        if os.environ.get("XPRA_NOX11") is None:
            os.environ["XPRA_NOX11"] = "1"
    return c

def load_shadow_x11() -> Optional[Type]:
    if envbool("XPRA_SHADOW_X11", True):
        try:
            os.environ["GDK_BACKEND"] = "x11"
            from xpra.x11 import shadow_x11_server
            return shadow_x11_server.ShadowX11Server
        except ImportError as e:
            warn("Warning: unable to load x11 shadow server",
                 f" {e}")
    return None


def ShadowServer(display_name:str="", multi_window:bool=True):
    c  : Optional[Type] = None
    if display_name.startswith("wayland-") or os.path.isabs(display_name):
        c = load_shadow_wayland(display_name)
    elif display_name.startswith(":"):
        c = load_shadow_x11()
    c = c or load_remotedesktop() or load_screencast() or load_shadow_x11()
    assert c
    return c(multi_window)
