#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.gtk.widget import choose_file
from xpra.os_util import gi_import

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")


def main():
    with program_context("file-chooser", "File Chooser"):
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Xpra")
        file_filter.add_pattern("*.xpra")
        window = None
        from xpra.gtk.signals import quit_on_signals
        quit_on_signals("file chooser test window")
        choose_file(window, "test", Gtk.FileChooserAction.OPEN, Gtk.STOCK_OPEN)
        return 0


if __name__ == "__main__":
    main()
