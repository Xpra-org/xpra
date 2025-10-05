#!/usr/bin/env python3

from typing import Any

from xpra.wayland.compositor import WaylandCompositor
from xpra.server.core import ServerCore


class WaylandSeamlessServer(ServerCore):

    def __init__(self):
        super().__init__()
        self.compositor = WaylandCompositor()

    def init_virtual_devices(self, devices: dict[str, Any]):
        pass
