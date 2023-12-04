# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label
from xpra.log import Logger

Gtk = gi_import("Gtk")

log = Logger("opengl", "util")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        super().__init__(
            "Configure Xpra's OpenGL Renderer",
            "opengl.png",
            wm_class=("xpra-configure-opengl-gui", "Xpra Configure OpenGL GUI"),
            header_bar=None,
            parent=parent,
        )

    def populate(self):
        self.add_widget(label("Configure Xpra's OpenGL Renderer", font="sans 20"))
        text = "".join((
            "This tool can cause your system to crash",
            "if your GPU drivers are buggy.",
            "Use with caution.",
            "\n",
            "A window will be painted using various picture encodings.",
            "You will be asked to confirm that the rendering was correct",
        ))
        lbl = label(text, font="Sans 14")
        lbl.set_line_wrap(True)
        self.add_widget(lbl)
        hbox = Gtk.HBox()
        self.add_widget(hbox)
        proceed = Gtk.Button.new_with_label("Proceed")
        proceed.connect("clicked", self.run_test)
        hbox.pack_start(proceed, True, True)
        cancel = Gtk.Button.new_with_label("Exit")
        cancel.connect("clicked", self.dismiss)
        hbox.pack_start(cancel, True, True)

    def run_test(self, *args):
        pass


def main(_args) -> int:
    from xpra.gtk.configure.main import run_gui
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
