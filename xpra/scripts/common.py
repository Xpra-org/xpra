# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import OSX
from xpra.scripts.config import InitException


no_gtk_bypass = False


def bypass_no_gtk(v=True) -> None:
    global no_gtk_bypass
    no_gtk_bypass = v


def no_gtk() -> None:
    if no_gtk_bypass:
        return
    if OSX:
        # we can't verify on macos because importing GtkosxApplication
        # will import Gtk, and we need GtkosxApplication early to find the paths
        return
    Gtk = sys.modules.get("gi.repository.Gtk")
    if Gtk is None:
        # all good, not loaded
        return
    raise InitException("the Gtk module is already loaded: %s" % Gtk)
