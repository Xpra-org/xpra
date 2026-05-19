# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.darwin.pointer import move_pointer
from xpra.server.shadow.pointer import ShadowPointerManager


class DarwinShadowPointerManager(ShadowPointerManager):
    """
    macOS pointer subsystem for shadow servers.
    """

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        if not self.get_server_source(proto):
            return False
        x, y = pointer[:2]
        move_pointer(x, y)
        return True

    def do_process_button_action(self, proto, device_id: int, wid: int, button: int, pressed: bool, pointer, props):
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        if self.process_mouse_common(proto, device_id, wid, pointer):
            self.button_action(device_id, wid, button, pressed, props)
