# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from threading import Event

from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger
log = Logger("rfb")


class RFBSource(object):

    def __init__(self, protocol, desktop, share=False):
        self.protocol = protocol
        self.desktop = desktop
        self.close_event = Event()
        self.log_disconnect = True
        self.ui_client = True
        self.counter = 0
        self.share = share
        self.uuid = "todo: use protocol?"

    def get_info(self):
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


    def send_server_event(self, *_args):
        pass

    def send_cursor(self):
        pass


    def damage(self, _wid, window, x, y, w, h, _options=None):
        from xpra.net.protocol import PACKET_JOIN_SIZE
        img = window.get_image(x, y, w, h)
        window.acknowledge_changes()
        log("damage: %s", img)
        fbupdate = struct.pack("!BBH", 0, 0, 1)
        encoding = 0    #Raw
        rect = struct.pack("!HHHHi", x, y, w, h, encoding)
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
        nocr = text.replace("\r", "")
        msg = struct.pack("!BBBBI", 3, 0, 0, 0, len(nocr))+nocr
        self.send(msg)

    def bell(self, *_args):
        msg = struct.pack("!B", 2)
        self.send(msg)

    def send(self, msg):
        p = self.protocol
        if p:
            p.send(msg)
