#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys


def main(argv=()):
    from xpra.os_util import POSIX, OSX
    from xpra.platform import program_context
    with program_context("Xpra-Bug-Report", "Xpra Bug Report"):
        from xpra.log import enable_color
        enable_color()

        if POSIX and not OSX:
            from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
            init_gdk_display_source()

        from xpra.log import enable_debug_for
        #logging init:
        if "-v" in argv:
            enable_debug_for("util")

        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        from xpra.client.gtk_base.bug_report import BugReport
        from xpra.gtk_common.gobject_compat import register_os_signals
        app = BugReport()
        app.close = app.quit
        app.init(True)
        register_os_signals(app.quit)
        try:
            from xpra.platform.gui import ready as gui_ready
            gui_ready()
            app.show()
            app.run()
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    v = main(sys.argv)
    sys.exit(v)
