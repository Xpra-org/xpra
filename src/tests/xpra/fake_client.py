#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.log import Logger
log = Logger()

class FakeClient(object):
    def __init__(self):
        self.supports_mmap = False
        self.mmap = None
        self.window_configure = True
        self._focused = None
        self.readonly = False
        self.title = "test"
        self._id_to_window = {}
        self._window_to_id = {}

    def send_refresh(self, *args):
        log.info("send_refresh(%s)", args)

    def send_refresh_all(self, *args):
        log.info("send_refresh_all(%s)", args)

    def send(self, *args):
        log.info("send(%s)", args)

    def send_positional(self, *args):
        log.info("send_positional(%s)", args)

    def update_focus(self, *args):
        log.info("update_focus(%s)", args)

    def quit(self, *args):
        log.info("quit(%s)", args)

    def handle_key_action(self, *args):
        log.info("handle_key_action(%s)", args)

    def send_mouse_position(self, *args):
        log.info("send_mouse_position(%s)", args)

    def mask_to_names(self, *args):
        return []
