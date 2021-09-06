# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from threading import Event

from xpra.server.rfb.rfb_const import RFBEncoding
from xpra.server.rfb.rfb_encode import raw_encode
from xpra.os_util import strtobytes
from xpra.util import AtomicInteger, csv
from xpra.log import Logger

log = Logger("rfb")

counter = AtomicInteger()


class RFBSource:
    __slots__ = (
        "protocol", "close_event", "log_disconnect",
        "ui_client", "counter", "share", "uuid", "lock", "keyboard_config",
        "encodings",
    )
    def __init__(self, protocol, share=False):
        self.protocol = protocol
        self.close_event = Event()
        self.log_disconnect = True
        self.ui_client = True
        self.counter = 0
        self.share = share
        self.uuid = "RFB%5i" % counter.increase()
        self.lock = False
        self.keyboard_config = None
        self.encodings = [RFBEncoding.RAW]

    def get_info(self) -> dict:
        return {
            "protocol"  : "rfb",
            "uuid"      : self.uuid,
            "share"     : self.share,
            }

    def set_encodings(self, encodings):
        known_encodings = []
        unknown_encodings = []
        for v in encodings:
            try:
                known_encodings.append(RFBEncoding(v))
            except ValueError:
                unknown_encodings.append(v)
        self.encodings = known_encodings
        log("RFB encodings: %s", csv(self.encodings))
        if unknown_encodings:
            log("RFB %i unknown encodings: %s", len(unknown_encodings), csv(unknown_encodings))

    def get_window_info(self, _wids):
        return {}

    def is_closed(self):
        return self.close_event.isSet()

    def close(self):
        self.close_event.set()

    def ping(self):
        pass

    def keys_changed(self):
        pass

    def set_default_keymap(self):
        log("set_default_keymap() keyboard_config=%s", self.keyboard_config)
        if self.keyboard_config:
            self.keyboard_config.set_default_keymap()
        return self.keyboard_config

    def set_keymap(self, _current_keyboard_config, keys_pressed, _force=False, _translate_only=False):
        kc = self.keyboard_config
        kc.keys_pressed = keys_pressed
        kc.set_keymap(True)
        kc.owner = self.uuid

    def send_server_event(self, *_args):
        pass

    def send_cursor(self):
        pass


    def update_mouse(self, *args):
        log("update_mouse%s", args)

    def damage(self, _wid, window, x, y, w, h, options=None):
        polling = options and options.get("polling", False)
        p = self.protocol
        if polling and p is None or p.queue_size()>=2:
            #very basic RFB update rate control,
            #if there are packets waiting already
            #we'll just process the next polling update instead:
            return
        if self.is_closed():
            return
        for packet in raw_encode(window, x, y, w, h):
            self.send(packet)

    def send_clipboard(self, text):
        nocr = strtobytes(text.replace("\r", ""))
        msg = struct.pack(b"!BBBBI", 3, 0, 0, 0, len(nocr))+nocr
        self.send(msg)

    def bell(self, *_args):
        msg = struct.pack(b"!B", 2)
        self.send(msg)

    def send(self, msg):
        p = self.protocol
        if p:
            p.send(msg)
