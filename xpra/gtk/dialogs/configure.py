# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label
from xpra.log import Logger

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

log = Logger("client", "util")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self):
        super().__init__(
            "Configure Xpra",
            "toolbox.png",
            wm_class=("xpra-configure-gui", "Xpra Configure GUI"),
            default_size=(640, 300),
            header_bar=(True, False),
        )

    def populate(self):
        self.vbox.add(label("Configure Xpra", font="sans 20"))
        self.ib("GStreamer", "gstreamer.png","Configure the GStreamer codecs", self.gstreamer)
        self.ib("Picture compression", "encoding.png","Encodings, speed and quality", self.encodings)

    def gstreamer(self, btn):
        self.button_command(btn, "configure", "gstreamer")

    def encodings(self, btn):
        self.button_command(btn, "configure", "encodings")


def main(): # pragma: no cover
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    from xpra.gtk.signals import register_os_signals
    with program_context("xpra-configure-gui", "Xpra Configure GUI"):
        enable_color()
        init()
        gui = ConfigureGUI()
        register_os_signals(gui.app_signal)
        ready()
        gui.show()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    r = main()
    sys.exit(r)
