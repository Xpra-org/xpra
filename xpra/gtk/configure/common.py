# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import POSIX
from xpra.log import Logger

log = Logger("util")


def sync() -> None:
    if POSIX:
        from subprocess import check_call
        check_call("sync")


def run_gui(gui_class) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    from xpra.gtk.util import gtk_main, quit_on_signals
    with program_context("xpra-configure-gui", "Xpra Configure GUI"):
        enable_color()
        init()
        gui = gui_class()
        quit_on_signals("xpra-configure-gui")
        ready()
        gui.show()
        gtk_main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0
