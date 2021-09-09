# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from threading import Event

from xpra.net.rfb.rfb_const import RFBEncoding
from xpra.net.rfb.rfb_encode import (
    raw_encode, tight_encode, tight_png, rgb222_encode, #zlib_encode,
    )
from xpra.net.protocol import PACKET_JOIN_SIZE
from xpra.os_util import memoryview_to_bytes
from xpra.os_util import strtobytes
from xpra.util import AtomicInteger, csv
from xpra.log import Logger

log = Logger("rfb")

counter = AtomicInteger()


class RFBSource:
    __slots__ = (
        "protocol", "close_event", "log_disconnect",
        "ui_client", "counter", "share", "uuid", "lock", "keyboard_config",
        "encodings", "quality", "pixel_format"
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
        self.pixel_format = (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.quality = 0

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

    def set_pixel_format(self, pixel_format):
        #bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift
        self.pixel_format = tuple(pixel_format)
        bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = pixel_format
        log(" pixel depth %i, %i bits per pixel", depth, bpp)
        log(" bigendian=%s, truecolor=%s", bool(bigendian), bool(truecolor))
        if truecolor:
            log(" RGB max: %s, shift: %s", (rmax, gmax, bmax), (rshift, bshift, gshift))


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
        encode = raw_encode
        kwargs = {}
        if self.pixel_format[:2]!=(32, 24):
            if self.pixel_format[:3]==(8, 6, 0):
                #crappy initial format chosen by realvnc
                encode = rgb222_encode
            else:
                log("damage: unsupported client pixel format: %s", self.pixel_format)
                return
        elif RFBEncoding.TIGHT_PNG in self.encodings:
            encode = tight_png
        elif RFBEncoding.TIGHT in self.encodings:
            encode = tight_encode
            kwargs = {"quality" : self.quality}
        #doesn't work
        #elif RFBEncoding.ZLIB in self.encodings:
        #    encode = zlib_encode
        packets = encode(window, x, y, w, h, **kwargs)
        if not packets:
            return
        self.send_many(*packets)

    def send_many(self, *packets):
        #merge small packets together:
        joined = []
        def send_joined():
            if joined:
                self.send(b"".join(memoryview_to_bytes(p) for p in joined))
                joined[:] = []
        for packet in packets:
            joined.append(packet)
            if sum(len(p) for p in joined) > PACKET_JOIN_SIZE:
                #too much, can't be joined
                joined.pop()
                send_joined()
                self.send(packet)
        send_joined()

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
