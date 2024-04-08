# This file is part of Xpra.
# Copyright (C) 2018-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from importlib import import_module

from xpra.gtk.configure.common import run_gui
from xpra.os_util import LINUX
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label


class HomeGUI(BaseGUIWindow):

    def __init__(self):
        super().__init__(
            "Configure Xpra",
            "toolbox.png",
            wm_class=("xpra-configure-gui", "Xpra Configure GUI"),
            default_size=(480, 300),
            header_bar=(False, False),
        )
        self.dialogs: dict[str, BaseGUIWindow] = {}

    def populate(self):
        self.vbox.add(label("Configure Xpra", font="sans 20"))
        self.vbox.add(label("Tune your xpra configuration:", font="sans 14"))
        if LINUX:
            self.sub("Packages", "package.png", "Install or remove xpra packages", "packages")
        self.sub("Features", "features.png", "Enable or disable feature groups", "features")
        self.sub("Picture compression", "encoding.png", "Encodings, speed and quality", "encodings")
        # self.sub("GStreamer", "gstreamer.png", "Configure the GStreamer codecs", "gstreamer")
        self.sub("Shadow Server", "shadow.png", "Configure the Shadow Server", "shadow")
        # self.sub("OpenGL acceleration", "opengl.png", "Test and validate OpenGL renderer", "opengl")

    def sub(self, title="", icon_name="browse.png", tooltip="", configure: str = "") -> None:

        def callback(_btn):
            dialog = self.dialogs.get(configure)
            if dialog is None:
                mod = import_module(f"xpra.gtk.configure.{configure}")
                dialog = mod.ConfigureGUI(self)
                self.dialogs[configure] = dialog
            dialog.show()
        self.ib(title, icon_name, tooltip, callback=callback)


def main(_args) -> int:
    return run_gui(HomeGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
