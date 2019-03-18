#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012-2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()
from xpra.net.file_transfer import FileTransferHandler


class FakeClient(FileTransferHandler):
    def __init__(self):
        FileTransferHandler.__init__(self)
        self.supports_mmap = False
        self.mmap = None
        self.mmap_enabled = False
        self.session_name = ""
        self._focused = None
        self.readonly = False
        self.windows_enabled = True
        self.can_scale = True
        self.start_new_commands = True
        self.server_bell = True
        self.client_supports_bell = True
        self.notifications_enabled = True
        self.client_supports_notifications = True
        self.cursors_enabled = True
        self.server_cursors = True
        self.client_supports_cursors = True
        self.server_clipboard = True
        self.client_supports_clipboard = True
        self.client_clipboard_direction = "both"
        self.quality = 80
        self.speed = 80
        self.encoding = "png"
        self.server_encodings_with_quality = []
        self.server_encodings_with_speed = []
        self.speaker_allowed = True
        self.speaker_enabled = True
        self.microphone_allowed = True
        self.microphone_enabled = True
        self.server_sound_send = True
        self.server_sound_receive = True
        self.server_readonly = False
        self.bell_enabled = True
        self.webcam_forwarding = True
        self.webcam_device = None
        self.server_virtual_video_devices = 0
        self.client_supports_opengl = False
        self.title = "test"
        self.keyboard_helper = None
        self.clipboard_helper = None
        self._id_to_window = {}
        self._window_to_id = {}
        self.server_window_decorations = False
        self.server_window_frame_extents = False
        self.encoding_defaults = {}
        self.xscale = 1
        self.yscale = 1
        self.log_events = True
        self.handshake_callbacks = []

    def log(self, *args):
        if self.log_events:
            log.info(*args)

    def connect(self, *args):
        pass

    def get_image(self, *_args):
        return None

    def get_encodings(self):
        return ["png"]

    def show_start_new_command(self):
        pass
    def show_file_upload(self):
        pass

    def after_handshake(self, cb):
        self.handshake_callbacks.append(cb)

    def fire_handshake_callbacks(self):
        cbs = self.handshake_callbacks
        self.handshake_callbacks = []
        for x in cbs:
            x()

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

    def mask_to_names(self, *_args):
        return []

    def get_current_modifiers(self, *_args):
        return []

    def get_mouse_position(self):
        return 0, 0

    def request_frame_extents(self, window):
        pass
    def get_window_frame_sizes(self):
        return None

    def fsx(self, v):
        return v
    def fsy(self, v):
        return v
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
