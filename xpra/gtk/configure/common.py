# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import POSIX
from xpra.gtk.css_overrides import add_screen_css
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.log import Logger

log = Logger("util")

CSS = b"""
.configure-window .xpra-body {
    padding: 20px 24px;
}

.configure-window .configure-intro {
    margin-bottom: 4px;
}

.configure-window .configure-grid {
    padding: 12px 16px;
}

.configure-window .configure-label {
    padding: 7px 6px;
    font-weight: 600;
}

.configure-window .configure-description,
.configure-window .configure-detail {
    padding: 7px 6px;
    color: alpha(@theme_fg_color, 0.68);
}

.configure-window .configure-icon {
    padding: 5px 8px 5px 2px;
}

.configure-window button.xpra-nav-button {
    min-height: 48px;
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 1.05em;
}

.configure-window .configure-section-title {
    margin-top: 4px;
    font-size: 1.1em;
    font-weight: 600;
}

.configure-window separator {
    margin: 7px 0;
    background-color: alpha(@theme_fg_color, 0.10);
}

.configure-window scale {
    margin: 2px 12px 8px 12px;
}

.configure-window .configure-option {
    margin-top: 4px;
    padding: 8px 10px;
    border-radius: 8px;
    background-color: alpha(@theme_fg_color, 0.035);
    font-weight: 600;
}

.configure-window .xpra-actions {
    margin-top: 8px;
}
"""

_css_loaded = False


def load_configure_style() -> None:
    global _css_loaded
    if not _css_loaded:
        add_screen_css(CSS)
        _css_loaded = True


class ConfigureGUIWindow(BaseGUIWindow):

    def __init__(self, *args, **kwargs):
        kwargs["style_class"] = "configure-window"
        super().__init__(*args, **kwargs)
        load_configure_style()


def sync() -> None:
    if POSIX:
        from subprocess import check_call
        check_call("sync")


def run_gui(gui_class) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready, force_focus
    from xpra.gtk.util import gtk_main, quit_on_signals
    with program_context("xpra-configure-gui", "Xpra Configure GUI"):
        enable_color()
        init()
        gui = gui_class()
        quit_on_signals("xpra-configure-gui")
        ready()
        force_focus()
        gui.show()
        gtk_main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0
