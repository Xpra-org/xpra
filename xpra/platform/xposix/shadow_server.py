# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import envbool
from xpra.os_util import is_Wayland

if envbool("XPRA_SHADOW_SCREENCAST", is_Wayland()):
    #try screen casting
    from xpra.platform.xposix.screencast import ScreenCast
    ShadowServer = ScreenCast
else:
    from xpra.x11.shadow_x11_server import ShadowX11Server
    ShadowServer = ShadowX11Server
