# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from importlib import import_module
from importlib.util import find_spec

from xpra.gtk.configure.common import run_gui
from xpra.os_util import LINUX, POSIX, OSX
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.css_overrides import add_screen_css
from xpra.gtk.widget import label


CSS = b"""
button {
    border-radius: 10px;
}
"""


class HomeGUI(BaseGUIWindow):

    def __init__(self):
        add_screen_css(CSS)
        super().__init__(
            "Configure Xpra",
            "toolbox.png",
            wm_class=("xpra-configure-gui", "Xpra Configure GUI"),
            default_size=(480, 300),
            header_bar=(False, False),
        )
        self.dialogs: dict[str, BaseGUIWindow] = {}

    def populate(self) -> None:
        self.vbox.add(label("Configure Xpra", font="sans 20"))
        self.vbox.add(label("Tune your xpra configuration:", font="sans 14"))
        if LINUX:
            self.sub("Packages", "package.png", "Install or remove xpra packages", "packages")
        self.sub("Features", "features.png", "Enable or disable feature groups", "features")
        self.sub("Settings", "gears.png", "Configure specific settings", "settings")
        self.sub("Picture compression", "encoding.png", "Encodings, speed and quality", "encodings", "xpra.codecs")
        # self.sub("GStreamer", "gstreamer.png", "Configure the GStreamer codecs", "gstreamer")
        self.sub("Debugging", "bugs.png", "Configure debug logging", "debug")

        self.sub("Shadow Server", "shadow.png", "Configure the Shadow Server", "shadow", "xpra.server")
        if POSIX and not OSX:
            self.sub("Virtual Framebuffer", "monitor.png", "Configure the vfb command", "vfb", "xpra.x11")
        # self.sub("OpenGL acceleration", "opengl.png", "Test and validate OpenGL renderer", "opengl")

    def sub(self, title="", icon_name="browse.png", tooltip="", configure: str = "", req_module="xpra") -> None:

        def callback(_btn) -> None:
            dialog = self.dialogs.get(configure)
            if dialog is None:
                mod = import_module(f"xpra.gtk.configure.{configure}")
                dialog = mod.ConfigureGUI(self)
                self.dialogs[configure] = dialog
            dialog.show()

        sensitive = not req_module or bool(find_spec(req_module))
        if not sensitive:
            tooltip = f"not available in this build:\n'{tooltip}'"
        self.ib(title, icon_name, tooltip, callback=callback, sensitive=sensitive)


def main(_args) -> int:
    return run_gui(HomeGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
