# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.common import  noop
from xpra.util import AdHocStruct
from xpra.log import Logger

log = Logger("client")


class FakeClient(AdHocStruct):
    def __init__(self):
        self.sp = self.sx = self.sy = self.srect = self.no_scaling
        self.cx = self.cy = self.no_scaling
        self.xscale = self.yscale = 1
        self.server_window_decorations = True
        self.mmap_enabled = False
        self.mmap = None
        self.readonly = False
        self.encoding_defaults = {}
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
        self.handle_key_action = noop
        self.window_ungrab = noop
        self.keyboard_grabbed = False
        self.window_with_grab = None
        self.keyboard_helper = None
        from gi.repository import GLib
        self.idle_add = GLib.idle_add
        self.timeout_add = GLib.timeout_add
        self.source_remove = GLib.source_remove

    def get_window_frame_sizes(self, *args):
        return None

    def no_scaling(self, *args):
        return args

    def signal_disconnect_and_quit(self, *args):
        log.info("signal_disconnect_and_quit")

    def suspend(self):
        log.info("suspend event")

    def resume(self):
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
