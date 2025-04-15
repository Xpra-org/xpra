#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.posix.fd_portal_shadow import PortalShadow
from xpra.log import Logger

log = Logger("shadow")


class ScreenCast(PortalShadow):

    def __init__(self, attrs: dict[str, str]):
        super().__init__(attrs)
        self.session_type = "screencast shadow"

    def on_session_created(self) -> None:
        # skip select_devices() and go straight to sources then start:
        self.select_sources()

    def set_keymap(self, server_source, force=False) -> None:
        """
        no input devices
        """

    def do_process_button_action(self, *args) -> None:
        """
        no input devices
        """
