#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.posix.fd_portal_shadow import PortalShadow
from xpra.log import Logger

log = Logger("shadow")


class RemoteDesktop(PortalShadow):
    def __init__(self, attrs: dict[str, str]):
        super().__init__(attrs)
        self.session_type = "remote desktop shadow"

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.platform.posix.portal_keyboard import RemoteDesktopKeyboardManager
        return RemoteDesktopKeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.platform.posix.portal_pointer import RemoteDesktopPointerManager
        return RemoteDesktopPointerManager
