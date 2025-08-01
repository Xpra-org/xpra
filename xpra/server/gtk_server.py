# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=wrong-import-position

from time import monotonic
from typing import Any

from xpra.os_util import gi_import
from xpra.util.version import dict_version_trim
from xpra.common import FULL_INFO
from xpra.gtk.versions import get_gtk_version_info
from xpra.server import features
from xpra.server.base import ServerBase
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "gtk")
screenlog = Logger("server", "screen")


def get_default_display():
    Gdk = gi_import("Gdk")
    return Gdk.Display.get_default()


class GTKServerBase(ServerBase):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See X11ServerBase, XpraServer and XpraX11ShadowServer
    """

    def __init__(self):
        log("GTKServerBase.__init__()")
        super().__init__()

    def watch_keymap_changes(self) -> None:
        # Set up keymap change notification:
        from xpra.gtk.keymap import get_default_keymap
        keymap = get_default_keymap()
        keymap.connect("keys-changed", self.keymap_changed)

    def do_quit(self) -> None:
        log("do_quit: calling Gtk.main_quit")
        Gtk = gi_import("Gtk")
        Gtk.main_quit()
        log("do_quit: Gtk.main_quit done")

    def do_run(self) -> None:
        if features.window:
            display = get_default_display()
            if display:
                # n = display.get_n_screens()
                # assert n==1, "unsupported number of screens: %i" % n
                screen = display.get_default_screen()
                screen.connect("size-changed", self._screen_size_changed)
                screen.connect("monitors-changed", self._monitors_changed)
        Gtk = gi_import("Gtk")
        log("do_run() calling %s", Gtk.main)
        Gtk.main()
        log("do_run() end of gtk.main()")

    def make_hello(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = super().make_hello(source)
        if "versions" in source.wants and FULL_INFO >= 2:
            caps.setdefault("versions", {}).update(get_gtk_version_info())
        return caps

    def get_ui_info(self, proto, *args) -> dict[str, Any]:
        info = super().get_ui_info(proto, *args)
        display = get_default_display()
        if display:
            info.setdefault("server", {}).update(
                {
                    "root_window_size": self.get_root_window_size(),
                }
            )
        return info

    def do_get_info(self, proto, *args) -> dict[str, Any]:
        start = monotonic()
        info = super().do_get_info(proto, *args)
        vi = dict_version_trim(get_gtk_version_info())
        vi["type"] = "Python/gtk"
        info.setdefault("server", {}).update(vi)
        log("GTKServerBase.do_get_info took %ims", (monotonic() - start) * 1000)
        return info

    def get_root_window_size(self) -> tuple[int, int]:
        from xpra.gtk.util import get_root_size
        return get_root_size(None)

    def get_max_screen_size(self) -> tuple[int, int]:
        return self.get_root_window_size()

    def configure_best_screen_size(self) -> tuple[int, int]:
        return self.get_root_window_size()

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        x, y = pos
        display = get_default_display()
        display.warp_pointer(display.get_default_screen(), x, y)
