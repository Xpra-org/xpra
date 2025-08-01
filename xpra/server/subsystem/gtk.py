# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=wrong-import-position

from typing import Any

from xpra.util.version import dict_version_trim
from xpra.common import FULL_INFO
from xpra.gtk.versions import get_gtk_version_info
from xpra.server import features
from xpra.server.subsystem.stub import StubServerMixin


class GTKServer(StubServerMixin):

    def watch_keymap_changes(self) -> None:
        # Set up keymap change notification:
        from xpra.gtk.keymap import get_default_keymap
        keymap = get_default_keymap()
        keymap.connect("keys-changed", self.keymap_changed)

    def setup(self) -> None:
        if features.window:
            from xpra.os_util import gi_import
            Gdk = gi_import("Gdk")
            screen = Gdk.Screen.get_default()
            if screen:
                screen.connect("size-changed", self._screen_size_changed)
                screen.connect("monitors-changed", self._monitors_changed)

    def get_caps(self, source) -> dict[str, Any]:
        if "versions" in source.wants and FULL_INFO >= 2:
            return {"versions": get_gtk_version_info()}
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        return {"versions": dict_version_trim(get_gtk_version_info())}
