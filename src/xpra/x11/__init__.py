# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
if sys.platform.startswith("win") or sys.platform=="darwin":
    raise ImportError("no X11 support on %s" % sys.platform)
