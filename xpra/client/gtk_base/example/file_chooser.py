#!/usr/bin/env python
# Copyright (C) 2020-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.gtk_common.gtk_util import choose_file

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk    #pylint: disable=wrong-import-position


def main():
    with program_context("file-chooser", "File Chooser"):
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Xpra")
        file_filter.add_pattern("*.xpra")
        window = None
        from xpra.gtk_common.gobject_compat import register_os_signals
        def signal_handler(*_args):
            Gtk.main_quit()
        register_os_signals(signal_handler)
        choose_file(window, "test", Gtk.FileChooserAction.OPEN, Gtk.STOCK_OPEN, None)
        return 0


if __name__ == "__main__":
    main()
