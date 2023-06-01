#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys


def main(argv=()):
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.platform.gui import init, set_default_icon
    from xpra.gtk_common.gtk_util import init_display_source
    with program_context("Xpra-Bug-Report", "Xpra Bug Report"):
        from xpra.log import enable_color
        enable_color()
        init_display_source()
        set_default_icon("bugs.png")
        init()

        from xpra.log import enable_debug_for
        #logging init:
        if "-v" in argv:
            enable_debug_for("util")

        from xpra.client.gtk3.bug_report import BugReport
        from xpra.gtk_common.gobject_compat import register_os_signals
        app = BugReport()
        app.close = app.quit
        app.init(True)
        register_os_signals(app.quit, "Bug Report")
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
