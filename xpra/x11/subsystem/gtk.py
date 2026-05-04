# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from subprocess import Popen

from xpra.util.system import is_X11
from xpra.server.subsystem.gtk import GTKServer
from xpra.log import Logger

log = Logger("server", "x11", "gtk")


def gdk_init() -> None:
    log("gdk_init()")
    try:
        from xpra.x11.gtk.display_source import init_gdk_display_source
    except ImportError as e:
        log.warn(f"Warning: unable to initialize gdk display source: {e}")
        return
    init_gdk_display_source()


class GtkX11Server(GTKServer):
    """
    GTK-based server running on top of an X11 display (typically Xvfb).
    Verifies the display, hooks into the X11 GDK display source and installs
    the X11 event filter.
    """

    def __init__(self):
        super().__init__()
        self.xvfb: Popen | None = None
        self.display = os.environ.get("DISPLAY", "")
        self.x11_filter = False

    def setup(self) -> None:
        if is_X11():
            from xpra.scripts.server import verify_display
            if not verify_display(xvfb=self.xvfb, display_name=self.display):
                from xpra.scripts.config import InitExit
                from xpra.exit_codes import ExitCode
                raise InitExit(ExitCode.NO_DISPLAY, f"unable to access display {self.display!r}")
            gdk_init()
            from xpra.x11.gtk.bindings import init_x11_filter
            self.x11_filter = init_x11_filter()
            assert self.x11_filter
        super().setup()

    def cleanup(self) -> None:
        if not self.x11_filter:
            return
        self.x11_filter = False
        from xpra.x11.gtk.bindings import cleanup_x11_filter
        cleanup_x11_filter()

    def late_cleanup(self, stop=True) -> None:
        super().late_cleanup(stop)
        if is_X11():
            from xpra.x11.gtk.display_source import close_gdk_display_source
            close_gdk_display_source()
