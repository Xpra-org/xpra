# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.platform.win32.common import SetPhysicalCursorPos
from xpra.platform.win32.pointer import move_pointer
from xpra.server.shadow.pointer import ShadowPointerManager
from xpra.log import Logger

log = Logger("shadow", "win32")


class Win32ShadowPointerManager(ShadowPointerManager):
    """
    Win32 pointer subsystem for shadow servers.
    """

    def __init__(self, server=None):
        super().__init__(server)
        self.cursor_errors = [0.0, 0]

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        x, y = pos[:2]
        move_pointer(x, y)

    def do_process_mouse_common(self, proto, device_id, wid: int, pointer, props) -> bool:
        ss = self.get_server_source(proto)
        if not ss:
            return False
        try:
            x, y = pointer[:2]
            if SetPhysicalCursorPos(x, y):
                return True
            start, count = self.cursor_errors
            now = monotonic()
            elapsed = now - start
            if count == 0 or (count > 1 and elapsed > 10):
                log.warn("Warning: cannot move cursor")
                log.warn(" (%i events)", count + 1)
                self.cursor_errors = [now, 1]
            else:
                self.cursor_errors[1] = count + 1
        except Exception as e:
            log("SetPhysicalCursorPos%s failed", pointer, exc_info=True)
            log.error("Error: failed to move the cursor:")
            log.estr(e)
        return False

    def do_process_button_action(self, proto, device_id, wid: int, button: int, pressed: bool, pointer, props) -> None:
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        did = -1
        if self.process_mouse_common(proto, did, wid, pointer):
            self.get_server_source(proto).user_event("button-action")
            self.button_action(did, wid, button, pressed, props)

    def button_action(self, device_id, wid: int, button: int, pressed: bool, props: dict) -> None:
        self.pointer_device.click(button, pressed, props)
