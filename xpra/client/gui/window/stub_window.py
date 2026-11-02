# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict


class StubWindow:

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        """ setup and initialize the window """

    def cleanup(self) -> None:
        """ free any resources """

    def get_map_client_properties(self) -> dict[str, Any]:
        """ client properties to send to the server during a `map` event """
        return {}

    def get_configure_client_properties(self) -> dict[str, Any]:
        """ client properties to send to the server during a `configure` event """
        return {}

    def get_info(self) -> dict[str, Any]:
        """ information for this subsystem """
        return {}
