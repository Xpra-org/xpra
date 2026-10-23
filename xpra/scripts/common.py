# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from importlib.util import find_spec

from xpra.os_util import OSX, WIN32
from xpra.exit_codes import ExitCode
from xpra.config import InitException, InitExit


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


def reqx11(mode: str) -> None:
    if OSX:
        # need to import gtk module early, not sure why!
        import xpra.gtk.util
        if not xpra.gtk.util:
            # cythonized code can bind None for missing imports
            raise ImportError("xpra.gtk.util")
    if find_spec("xpra.x11"):
        return
    if OSX or WIN32:
        raise InitExit(ExitCode.UNSUPPORTED, f"{mode} requires a build with the X11 bindings")
    raise InitExit(ExitCode.UNSUPPORTED, f"you must install `xpra-x11` to use {mode!r}")
