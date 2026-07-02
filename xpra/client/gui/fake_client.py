# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.common import noop
from xpra.util.glib_scheduler import GLibScheduler
from xpra.log import Logger

log = Logger("client")


class FakeWindowSubsystem:
    def __init__(self):
        self.wheel_smooth = False
        self.modal_windows = False
        self._id_to_window = {}

    def has_focus(self, *_args) -> bool:
        return False

    def window_close_event(self, *_args) -> None:
        log("window_close_event ignored")


class FakeClient(GLibScheduler):
    def __init__(self):
        self.title = ""
        self.readonly = False
        self._remote_server_mode = "seamless"
        self.pointer_grabbed = None
        self.find_window = noop
        self.request_frame_extents = noop
        self.server_readonly = False
        self.window_ungrab = noop
        self.subsystems = {
            "window": FakeWindowSubsystem(),
        }

    def get_subsystem(self, name: str):
        return self.subsystems.get(name)

    def get_window_frame_sizes(self, *_args) -> dict[str, Any]:
        return {}

    def signal_disconnect_and_quit(self, *_args):
        log.info("signal_disconnect_and_quit")

    def send(self, *args):
        log("send%s", args)

    def get_current_modifiers(self) -> Sequence[str]:
        return ()

    def get_raw_mouse_position(self) -> tuple[int, int]:
        return 0, 0

    def get_mouse_position(self) -> tuple[int, int]:
        return 0, 0

    def __repr__(self):
        return f"<FakeClient {self.subsystems!r}>"
