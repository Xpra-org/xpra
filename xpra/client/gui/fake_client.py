# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import noop
from xpra.util.objects import AdHocStruct
from xpra.log import Logger

log = Logger("client")


class FakeClient(AdHocStruct):
    def __init__(self):
        self.sp = self.sx = self.sy = self.srect = self.no_scaling
        self.cx = self.cy = self.no_scaling
        self.xscale = self.yscale = 1
        self.server_window_decorations = True
        self.mmap = None
        self.readonly = False
        self.encoding_defaults = {}
        self.modal_windows = []
        self._focused = None
        self._remote_server_mode = "seamless"
        self.wheel_smooth = False
        self.pointer_grabbed = None
        self.find_window = noop
        self.request_frame_extents = noop
        self.server_window_states = ()
        self.server_window_frame_extents = False
        self.server_readonly = False
        self.server_pointer = False
        self.update_focus = noop
        self.has_focus = noop
        self.suspended = False

        self._id_to_window = {}
        self._window_to_id = {}

        self.handle_key_action = noop
        self.window_ungrab = noop
        self.keyboard_grabbed = False
        self.window_with_grab = None
        self.keyboard_helper = None

    def get_window_frame_sizes(self, *_args) -> dict[str, Any]:
        return {}

    def no_scaling(self, *args):
        if len(args) == 1:
            return args[0]
        return args

    def signal_disconnect_and_quit(self, *_args):
        log.info("signal_disconnect_and_quit")

    def suspend(self) -> None:
        log.info("suspend event")

    def resume(self) -> None:
        log.info("resume event")

    def send(self, *args):
        log("send%s", args)

    def get_current_modifiers(self):
        return ()

    def get_raw_mouse_position(self):
        return 0, 0

    def get_mouse_position(self):
        return 0, 0

    def server_ok(self):
        return True

    def mask_to_names(self, *_args):
        return ()

    def window_close_event(self, *_args):
        log("window_close_event ignored")

    def control_refresh(self, *_args, **_kwargs):
        log("send_control_refresh ignored")

    def fsx(self, v):
        return v

    def fsy(self, v):
        return v

    def sx(self, v):
        return v

    def sy(self, v):
        return v
