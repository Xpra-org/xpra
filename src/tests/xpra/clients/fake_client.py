#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()


class FakeClient(object):
    def __init__(self):
        self.supports_mmap = False
        self.mmap = None
        self.mmap_enabled = False
        self._focused = None
        self.readonly = False
        self.title = "test"
        self._id_to_window = {}
        self._window_to_id = {}
        self.server_window_decorations = False
        self.server_window_frame_extents = False
        self.encoding_defaults = {}
        self.window_configure_skip_geometry = True
        self.window_configure_pointer = True
        self.xscale = 1
        self.yscale = 1
        self.log_events = True

    def log(self, *args):
        if self.log_events:
            log.info(*args)

    def send_refresh(self, *args):
        self.log("send_refresh(%s)", args)

    def send_refresh_all(self, *args):
        self.log("send_refresh_all(%s)", args)

    def send(self, *args):
        self.log("send(%s)", args)

    def send_positional(self, *args):
        self.log("send_positional(%s)", args)

    def update_focus(self, *args):
        self.log("update_focus(%s)", args)

    def quit(self, *args):
        self.log("quit(%s)", args)

    def handle_key_action(self, *args):
        self.log("handle_key_action(%s)", args)

    def send_mouse_position(self, *args):
        self.log("send_mouse_position(%s)", args)

    def send_button(self, *args):
        self.log("send_button%s", args)

    def send_configure_event(self, skip_geometry):
        self.log("send_configure_event(%s)", skip_geometry)

    def window_close_event(self, *args):
        self.log("window_close_event%s", args)

    def mask_to_names(self, *args):
        return []

    def get_current_modifiers(self, *args):
        return []

    def get_mouse_position(self):
        return 0, 0

    def request_frame_extents(self, window):
        pass
    def get_window_frame_sizes(self):
        return None

    def sx(self, v):
        return v
    def sy(self, v):
        return v
    def srect(self, x, y, w, h):
        return x, y, w, h
    def sp(self, x, y):
        return x, y
    def cx(self, v):
        return v
    def cy(self, v):
        return v
    def crect(self, x, y, w, h):
        return x, y, w, h
    def cp(self, x, y):
        return x, y
