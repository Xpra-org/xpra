#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal, sys

def main():
    from xpra.platform import program_context
    with program_context("Xpra-Bug-Report", "Xpra Bug Report"):
        from xpra.log import enable_color
        enable_color()

        from xpra.log import Logger, enable_debug_for
        log = Logger("util")
        #logging init:
        if "-v" in sys.argv:
            enable_debug_for("util")

        from xpra.gtk_common.gobject_compat import import_gobject
        gobject = import_gobject()
        gobject.threads_init()

        from xpra.os_util import SIGNAMES
        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        from xpra.client.gtk_base.bug_report import BugReport
        app = BugReport()
        app.close = app.quit
        app.init(True)
        def app_signal(signum, frame):
            print("")
            log.info("got signal %s", SIGNAMES.get(signum, signum))
            app.quit()
        signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)
        try:
            from xpra.platform.gui import ready as gui_ready
            gui_ready()
            app.show()
            app.run()
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
