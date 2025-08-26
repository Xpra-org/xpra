# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util.env import envbool
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("screen")

FAKE_X11_INIT_ERROR = envbool("XPRA_FAKE_X11_INIT_ERROR", False)


class X11Init(StubServerMixin):
    PREFIX = "x11"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.display = os.environ.get("DISPLAY", "")
        assert not envbool("XPRA_GTK", False)

    def setup(self) -> None:
        if FAKE_X11_INIT_ERROR:
            raise RuntimeError("fake x11 init error")
        from xpra.x11.bindings.display_source import get_display_ptr, init_display_source
        if not get_display_ptr():
            try:
                init_display_source()
            except ValueError as e:
                from xpra.scripts.config import InitExit
                from xpra.exit_codes import ExitCode
                raise InitExit(ExitCode.VFB_ERROR, str(e)) from None
        main_loop = getattr(self, "main_loop", None)
        if not main_loop:
            raise RuntimeError("no main loop!")
        context = main_loop.get_context()
        log("GLib MainContext=%r", context)
        from xpra.x11.bindings.loop import register_glib_source
        register_glib_source(context)
        from xpra.x11.bindings.core import X11CoreBindings
        X11CoreBindings().show_server_info()
        from xpra.x11.window_filters import init_x11_window_filters
        init_x11_window_filters()
        from xpra.scripts.main import no_gi_gtk_modules
        no_gi_gtk_modules()

    def cleanup(self) -> None:
        from xpra.x11.dispatch import cleanup_all_event_receivers
        cleanup_all_event_receivers()
