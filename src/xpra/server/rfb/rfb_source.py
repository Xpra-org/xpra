# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from threading import Event

from xpra.net.protocol import PACKET_JOIN_SIZE
from xpra.os_util import memoryview_to_bytes, strtobytes
from xpra.util import AtomicInteger
from xpra.log import Logger

log = Logger("rfb")

counter = AtomicInteger()


class RFBSource:

    def __init__(self, protocol, desktop, share=False):
        self.protocol = protocol
        self.desktop = desktop
        self.close_event = Event()
        self.log_disconnect = True
        self.ui_client = True
        self.counter = 0
        self.share = share
        self.uuid = "RFB%5i" % counter.increase()
        self.lock = False
        self.keyboard_config = None

    def get_info(self) -> dict:
        return {
            "protocol"  : "rfb",
            "uuid"      : self.uuid,
            "share"     : self.share,
            }

    def get_window_info(self, _wids):
        return {}

    def is_closed(self):
        return self.close_event.isSet()

    def close(self):
        pass

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
        img = window.get_image(x, y, w, h)
        window.acknowledge_changes()
        log("damage: %s", img)
        if not img or self.is_closed():
            return
        fbupdate = struct.pack(b"!BBH", 0, 0, 1)
        encoding = 0    #Raw
        rect = struct.pack(b"!HHHHi", x, y, w, h, encoding)
        if img.get_rowstride()!=w*4:
            img.restride(w*4)
        pixels = img.get_pixels()
        assert len(pixels)>=4*w*h
        pixels = pixels[:4*w*h]
        if len(pixels)<=PACKET_JOIN_SIZE:
            self.send(fbupdate+rect+memoryview_to_bytes(pixels))
        else:
            self.send(fbupdate+rect)
            self.send(pixels)

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
