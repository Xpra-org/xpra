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

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        """ setup and initialize the window """

    def cleanup(self) -> None:
        """ free any resources """

    def get_window_event_mask(self) -> Gdk.EventMask:
        return 0

    def init_widget_events(self, widget) -> None:
        """ register events on the widget shown in the window """

    def set_icon(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        """ set the window icon to the given pixbuf """

    def get_map_client_properties(self) -> dict[str, Any]:
        """ client properties to send to the server during a `map` event """
        return {}

    def get_configure_client_properties(self) -> dict[str, Any]:
        """ client properties to send to the server during a `configure` event """
        return {}

    def get_info(self) -> dict[str, Any]:
        """ information for this subsystem """
        return {}
