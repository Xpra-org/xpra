# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen

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
    __slots__ = ("x11_filter", "xvfb")

    def __init__(self, server=None):
        super().__init__(server)
        self.xvfb: Popen | None = None
        self.x11_filter = False

    def setup(self) -> None:
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
        from xpra.x11.gtk.display_source import close_gdk_display_source
        close_gdk_display_source()
