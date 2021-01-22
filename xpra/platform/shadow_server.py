# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import

def ShadowServer(): # pragma: no cover
    raise NotImplementedError()

platform_import(globals(), "shadow_server", True, "ShadowServer")
