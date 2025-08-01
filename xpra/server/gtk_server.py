# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=wrong-import-position

from typing import Any

from xpra.os_util import gi_import
from xpra.util.version import dict_version_trim
from xpra.common import FULL_INFO
from xpra.gtk.versions import get_gtk_version_info
from xpra.server import features
from xpra.server.base import ServerBase
from xpra.log import Logger

log = Logger("server", "gtk")


class GTKServerBase(ServerBase):

    def watch_keymap_changes(self) -> None:
        # Set up keymap change notification:
        from xpra.gtk.keymap import get_default_keymap
        keymap = get_default_keymap()
        keymap.connect("keys-changed", self.keymap_changed)

    def do_run(self) -> None:
        if features.window:
            Gdk = gi_import("Gdk")
            screen = Gdk.Screen.get_default()
            if screen:
                screen.connect("size-changed", self._screen_size_changed)
                screen.connect("monitors-changed", self._monitors_changed)
        super().do_run()

    def make_hello(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = super().make_hello(source)
        if "versions" in source.wants and FULL_INFO >= 2:
            caps.setdefault("versions", {}).update(get_gtk_version_info())
        return caps

    def do_get_info(self, proto, *args) -> dict[str, Any]:
        info = super().do_get_info(proto, *args)
        vi = dict_version_trim(get_gtk_version_info())
        info.setdefault("server", {}).update(vi)
        return info

    def get_max_screen_size(self) -> tuple[int, int]:
        return self.get_root_window_size()

    def configure_best_screen_size(self) -> tuple[int, int]:
        return self.get_root_window_size()
