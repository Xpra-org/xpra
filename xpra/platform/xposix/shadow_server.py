# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import envbool
from xpra.os_util import is_Wayland
from xpra.exit_codes import ExitCode
from xpra.scripts.config import InitExit

def load_screencast():
    try:
        from xpra.platform.xposix import screencast
    except ImportError as e:
        raise InitExit(ExitCode.UNSUPPORTED, str(e))
    return screencast.ScreenCast

def load_shadow_x11():
    try:
        from xpra.x11 import shadow_x11_server
    except ImportError as e:
        raise InitExit(ExitCode.UNSUPPORTED, str(e))
    return shadow_x11_server.ShadowX11Server

def warn(*messages):
    from xpra.log import Logger
    log = Logger("server")
    for m in messages:
        log.warn(m)

ShadowServer = None
if envbool("XPRA_SHADOW_SCREENCAST", is_Wayland()):
    if is_Wayland() and not os.environ.get("XPRA_NOX11"):
        os.environ["XPRA_NOX11"] = "1"
    try:
        ShadowServer = load_screencast()
    except InitExit as e:
        warn("Warning: unable to load the screencast backend",
             f" {e}")
if ShadowServer is None:
    try:
        ShadowServer = load_shadow_x11()
    except InitExit:
        warn("Warning: unable to load the xpra-x11 bindings for the shadow server",
             " attempting to use the screencast interface instead")
        ShadowServer = load_screencast()
