# This file is part of Xpra.
# Copyright (C) 2018-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from importlib import import_module

from xpra.gtk.configure.common import get_user_config_file, run_gui
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import LINUX
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label


class ConfigureGUI(BaseGUIWindow):

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
        self.sub("GStreamer", "gstreamer.png", "Configure the GStreamer codecs", "gstreamer")
        self.sub("OpenGL acceleration", "opengl.png", "Test and validate OpenGL renderer", "opengl")

    def sub(self, title="", icon_name="browse.png", tooltip="", configure: str = "") -> None:

        def callback(_btn):
            dialog = self.dialogs.get(configure)
            if dialog is None:
                mod = import_module(f"xpra.gtk.configure.{configure}")
                dialog = mod.ConfigureGUI(self)
                self.dialogs[configure] = dialog
            dialog.show()
        self.ib(title, icon_name, tooltip, callback=callback)


def main(args) -> ExitValue:
    if args:
        conf = get_user_config_file()
        subcommand = args[0]
        if subcommand == "reset":
            import datetime
            now = datetime.datetime.now()
            with open(conf, "w", encoding="utf8") as f:
                f.write("# this file was reset on "+now.strftime("%Y-%m-%d %H:%M:%S"))
            return ExitCode.OK
        elif subcommand == "backup":
            if not os.path.exists(conf):
                print(f"# {conf!r} does not exist yet")
                return ExitCode.FILE_NOT_FOUND
            bak = conf[-5:]+".bak"
            with open(conf, "r", encoding="utf8") as read:
                with open(bak, "w", encoding="utf8") as write:
                    write.write(read.read())
            return ExitCode.OK
        elif subcommand == "show":
            if not os.path.exists(conf):
                print(f"# {conf!r} does not exist yet")
            else:
                with open(conf, "r", encoding="utf8") as f:
                    print(f.read())
            return ExitCode.OK
        else:
            if any(not str.isalnum(x) for x in subcommand):
                raise ValueError("invalid characters found in subcommand")
            mod = import_module(f"xpra.gtk.configure.{subcommand}")
            if not mod:
                raise InitExit(ExitCode.FILE_NOT_FOUND, f"unknown configure subcommand {subcommand!r}")
            return mod.main(args[1:])
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(int(main(sys.argv[1:])))
