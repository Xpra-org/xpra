# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.os_util import gi_import

Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")


class StubWindow:
    __gsignals__: dict[str, Any] = {}

    def init_window(self, client, metadata: typedict) -> None:
        pass

    def cleanup(self) -> None:
        pass

    def get_window_event_mask(self) -> Gdk.EventMask:
        return 0

    def init_widget_events(self, widget) -> None:
        pass

    def set_icon(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        pass

    def get_map_client_properties(self) -> dict[str, Any]:
        return {}

    def get_configure_client_properties(self) -> dict[str, Any]:
        return {}
