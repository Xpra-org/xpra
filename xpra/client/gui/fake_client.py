# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.util.glib_scheduler import GLibScheduler
from xpra.util.objects import typedict
from xpra.client.gui.window_title import get_window_title
from xpra.log import Logger

log = Logger("client")


class FakePointerSubsystem:
    def __init__(self):
        self.wheel_smooth = False
        self.server_pointer = True
        self.middle_click = True
        self.button_transform: dict[tuple[str, int], int] = {}

    def get_mouse_position(self) -> tuple[int, int]:
        return 0, 0

    def split_pointer_position(self, position) -> tuple[tuple[int, ...], dict]:
        return tuple(position[:2]), {}

    def send_button(self, *_args) -> None:
        log("send_button ignored")

    def wheel_event(self, *_args) -> None:
        log("wheel_event ignored")


class FakeWindowSubsystem(GLibScheduler):
    def __init__(self, client=None):
        self.client = client
        if client:
            # like `StubClientSubsystem`, use the client's own scheduler:
            self.idle_add = client.idle_add
            self.timeout_add = client.timeout_add
            self.source_remove = client.source_remove
        self.modal_windows = False
        self.server_window_states: Sequence[str] = ()
        self.server_window_frame_extents = False
        self._id_to_window = {}
        self._focused = None
        self._window_with_grab = None
        self.pointer_grabbed = None

    @property
    def focused_wid(self) -> int:
        return self._focused or 0

    def is_grabbed(self, wid: int) -> bool:
        return bool(wid) and self._window_with_grab == wid

    def grab_lost(self) -> None:
        self._window_with_grab = None

    def window_grab(self, wid: int, _window) -> None:
        self._window_with_grab = wid

    def window_ungrab(self, _window=None) -> None:
        self._window_with_grab = None

    def get_window(self, wid: int):
        return self._id_to_window.get(wid)

    def has_focus(self, *_args) -> bool:
        return False

    def update_focus(self, *_args) -> bool:
        return False

    def control_refresh(self, *_args) -> None:
        log("control_refresh ignored")

    def send_refresh(self, *_args) -> None:
        log("send_refresh ignored")

    def window_close_event(self, *_args) -> None:
        log("window_close_event ignored")

    def send(self, *args) -> None:
        log("send%s", args)

    def get_window_title(self, wid: int, metadata: dict) -> str:
        return get_window_title(self.client, wid, metadata) if self.client else ""


class FakeWindowHost(GLibScheduler):
    """
    What windows are created with when there is no client (opengl probing, examples and tests):
    a subsystem lookup and the read-only flag, the main loop is GLib's.
    """

    def __init__(self, title="", readonly=False):
        # the window title template, see `get_window_title`:
        self.title = title
        self.readonly = readonly
        self.subsystems: dict[str, Any] = {
            "window": FakeWindowSubsystem(self),
            "pointer": FakePointerSubsystem(),
        }

    def get_subsystem(self, name: str):
        return self.subsystems.get(name)

    def is_readonly(self) -> bool:
        return self.readonly

    def make_window(self, window_class: type, wid: int, geometry: tuple[int, int, int, int], metadata: dict,
                    border=None, max_window_size=(0, 0), pixel_depth=0, headerbar="no"):
        """ create a window which is not a transient for any other, and register it with the window subsystem """
        from xpra.client.gui.window_border import WindowBorder
        window = window_class(self.get_subsystem, self.is_readonly, None, wid,
                              geometry, geometry[2:4],
                              typedict(metadata), False, typedict(),
                              border or WindowBorder(False), max_window_size, pixel_depth, headerbar)
        if wid:
            self.subsystems["window"]._id_to_window[wid] = window
        return window

    def __repr__(self):
        return f"<{type(self).__name__} {self.subsystems!r}>"


class FakeClient(FakeWindowHost):
    """ the client surface used by the menu and tray examples """

    def __init__(self):
        super().__init__()
        self._remote_server_mode = "seamless"
        self.server_readonly = False

    def is_readonly(self) -> bool:
        return bool(self.readonly or self.server_readonly)

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
