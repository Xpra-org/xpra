# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from queue import SimpleQueue
from threading import Event
from typing import Any
from collections.abc import Sequence

from xpra.net.rfb.const import RFBEncoding, RFBServerMessage
from xpra.net.rfb.encode import (
    make_header, raw_encode_image, tight_encode_image, tight_png_image, rgb222_encode_image, zlib_encode_image,
)
from xpra.net.protocol.socket_handler import PACKET_JOIN_SIZE
from xpra.server.source.stub import PointerSource
from xpra.server.window.compress import free_image_wrapper  # pylint: disable=import-outside-toplevel
from xpra.util.objects import AtomicInteger
from xpra.util.str_fn import csv, memoryview_to_bytes
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("rfb")

counter = AtomicInteger()

RFB_ENCODE_QUEUE_MAX_SIZE = 2


def nocursordata(*_args) -> tuple:
    return ()


def cap_pct(v: int) -> int:
    return max(0, min(100, int(v)))


def rfb_level_to_pct(level: int) -> int:
    if level <= 0:
        return 0
    return cap_pct(round(100 * level / 9))


def rfb_compression_level_to_speed(level: int) -> int:
    if level <= 0:
        return 0
    return cap_pct(round(100 * (10 - level) / 9))


def free_rfb_image(image) -> None:
    if not getattr(image, "free", None):
        return
    if not getattr(image, "is_thread_safe", None):
        image.free()
        return
    free_image_wrapper(image)


class RFBSource(PointerSource):
    __slots__ = (
        "protocol", "close_event",
        "counter", "share", "uuid", "lock", "keyboard_config",
        "encodings", "quality", "speed", "pixel_format",
        "get_cursor_data_cb", "last_cursor_sent",
        "zlib_compressor",
        "continuous_updates", "cu_rect", "pending_request",
        "last_pointer_pos",
        "encode_queue", "encode_thread", "pixel_format_generation",
    )

    def __init__(self, protocol, share=False):
        self.protocol = protocol
        self.close_event = Event()
        self.counter = 0
        self.share = share
        self.uuid = "RFB%5i" % counter.increase()
        self.lock = False
        self.keyboard_config = None
        self.encodings = [RFBEncoding.RAW]
        self.pixel_format = (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.pixel_format_generation = 0
        self.quality = 0
        self.speed = 0
        self.get_cursor_data_cb = nocursordata
        self.last_cursor_sent = ()
        self.zlib_compressor = None
        # default to push-mode: preserves prior behaviour for viewers that
        # never send EnableContinuousUpdates. A viewer that opts out (by
        # sending message 150 with enable=0) switches us to request-driven.
        self.continuous_updates = True
        self.cu_rect: tuple[int, int, int, int] | None = None
        self.pending_request: tuple[int, int, int, int] | None = None
        self.last_pointer_pos: tuple[int, int] | None = None
        self.encode_queue: SimpleQueue[None | tuple[int, int, Any, int, int, int, int]] = SimpleQueue()
        self.encode_thread = start_thread(self.encode_loop, f"rfb-encode-{self.uuid}", daemon=True)

    def get_info(self) -> dict[str, Any]:
        return {
            "protocol": "rfb",
            "uuid": self.uuid,
            "share": self.share,
            "quality": self.quality,
            "speed": self.speed,
            "encode-queue": self.encode_queue.qsize(),
        }

    def set_encodings(self, encodings: Sequence) -> None:
        known_encodings = []
        unknown_encodings = []
        for v in encodings:
            if -32 <= v <= -23:
                # JPEG Quality Level pseudo-encoding: 0 means automatic, 9 means best quality.
                self.quality = rfb_level_to_pct(v + 32)
                continue
            if -512 <= v <= -412:
                # JPEG Fine-Grained Quality Level pseudo-encoding: direct 0..100 quality.
                self.quality = cap_pct(v + 512)
                continue
            if -256 <= v <= -247:
                # Compression Level pseudo-encoding: 0 means automatic, 9 means most compression / lowest speed.
                self.speed = rfb_compression_level_to_speed(v + 256)
                continue
            try:
                known_encodings.append(RFBEncoding(v))
            except ValueError:
                unknown_encodings.append(v)
        self.encodings = known_encodings
        log("RFB encodings: %s, quality=%i, speed=%i", csv(self.encodings), self.quality, self.speed)
        if unknown_encodings:
            log("RFB %i unknown encodings: %s", len(unknown_encodings), csv(unknown_encodings))

    def set_pixel_format(self, pixel_format: Sequence[int]) -> None:
        # bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift
        new_format = tuple(pixel_format)
        if new_format != self.pixel_format:
            # the byte layout of pixels fed into the zlib stream is about to change;
            # the inflater on the client side won't benefit from history bytes
            # produced from a different format, so start a fresh compressor.
            self.zlib_compressor = None
            self.pixel_format_generation += 1
        self.pixel_format = new_format
        bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = pixel_format
        log(" pixel depth %i, %i bits per pixel", depth, bpp)
        log(" bigendian=%s, truecolor=%s", bool(bigendian), bool(truecolor))
        if truecolor:
            log(" RGB max: %s, shift: %s", (rmax, gmax, bmax), (rshift, bshift, gshift))

    def set_continuous_updates(self, enabled: bool, x: int, y: int, w: int, h: int) -> None:
        # RFB EnableContinuousUpdates (msg 150). When enabled, the server may push
        # FramebufferUpdates inside the given rect without waiting for requests.
        # When disabled, the server must reply with EndOfContinuousUpdates and
        # revert to request-driven mode.
        was_enabled = self.continuous_updates
        if enabled:
            self.continuous_updates = True
            self.cu_rect = (x, y, w, h)
            log("continuous updates enabled rect=%s", self.cu_rect)
        else:
            self.continuous_updates = False
            self.cu_rect = None
            log("continuous updates disabled")
            if was_enabled and not self.is_closed():
                self.send(struct.pack(b"!B", RFBServerMessage.ENDOFCONTINOUSUPDATES))

    def request_update(self, x: int, y: int, w: int, h: int) -> None:
        # incremental FramebufferUpdateRequest: record the rect so the next
        # damage event can satisfy it. Union with any prior outstanding rect.
        if self.pending_request is None:
            self.pending_request = (x, y, w, h)
            return
        px, py, pw, ph = self.pending_request
        nx, ny = min(px, x), min(py, y)
        nw = max(px + pw, x + w) - nx
        nh = max(py + ph, y + h) - ny
        self.pending_request = (nx, ny, nw, nh)

    def is_closed(self) -> bool:
        return self.close_event.is_set()

    def requires_sharing(self) -> bool:
        return True

    def close(self) -> None:
        if self.close_event.is_set():
            return
        self.close_event.set()
        self.encode_queue.put(None)

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

    def send_cursor(self) -> None:
        if RFBEncoding.CURSOR not in self.encodings:
            return
        if not self.get_cursor_data_cb:
            return
        cursor_info = self.get_cursor_data_cb(False)
        if not cursor_info:
            return
        cursor_data = cursor_info[0]
        if not cursor_data:
            return
        w, h, xhot, yhot, serial, pixels, name = cursor_data[2:9]
        cursor_key = tuple(cursor_data[2:9])
        if self.last_cursor_sent == cursor_key:
            return
        log("send_cursor() %sx%s hotspot=%s,%s serial=%s name=%r", w, h, xhot, yhot, serial, name)
        cursor = self.make_rfb_cursor(w, h, pixels)
        if not cursor:
            return
        self.last_cursor_sent = cursor_key
        # In RFB cursor pseudo-encoding, x/y carry the cursor hotspot.
        self.send(make_header(RFBEncoding.CURSOR, xhot, yhot, w, h) + cursor)

    def make_rfb_cursor(self, w: int, h: int, pixels) -> bytes:
        bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = self.pixel_format
        if (bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift) != (
                32, 24, 0, 1, 255, 255, 255, 16, 8, 0):
            log("cursor: unsupported client pixel format: %s", self.pixel_format)
            return b""
        rgba = memoryview_to_bytes(pixels)
        if len(rgba) < w * h * 4:
            log.warn("Warning: not enough cursor pixels: expected %i bytes, got %i", w * h * 4, len(rgba))
            return b""
        cursor_pixels = bytearray(w * h * 4)
        mask = bytearray(((w + 7) // 8) * h)
        for i in range(w * h):
            si = i * 4
            r = rgba[si]
            g = rgba[si + 1]
            b = rgba[si + 2]
            a = rgba[si + 3]
            # Default RFB server pixel format is little-endian 32-bit RGB:
            # memory order is B, G, R, unused.
            cursor_pixels[si:si + 4] = bytes((b, g, r, 0))
            if a:
                row = i // w
                col = i % w
                mask[row * ((w + 7) // 8) + col // 8] |= 0x80 >> (col % 8)
        return bytes(cursor_pixels) + bytes(mask)

    def damage(self, _wid: int, window, x: int, y: int, w: int, h: int, options=None) -> None:
        polling = options and options.get("polling", False)
        p = self.protocol
        if polling and (p is None or p.queue_size() >= 2 or self.encode_queue.qsize() >= RFB_ENCODE_QUEUE_MAX_SIZE):
            # very basic RFB update rate control,
            # if there are packets waiting already
            # we'll just process the next polling update instead:
            return
        if self.is_closed():
            return
        # gating for clients that opted out of continuous updates: only
        # service unsolicited (polling) damage when a FramebufferUpdateRequest
        # is outstanding. Direct calls from FramebufferUpdateRequest(inc=0)
        # arrive without options.polling and always go through.
        if polling and not self.continuous_updates:
            if self.pending_request is None:
                return
            self.pending_request = None
        image = window.get_image(x, y, w, h)
        window.acknowledge_changes()
        if image is None:
            return
        self.encode_queue.put((self.pixel_format_generation, _wid, image, x, y, w, h))

    def encode_loop(self) -> None:
        while True:
            item = self.encode_queue.get(True)
            if item is None:
                return
            try:
                generation, wid, image, x, y, w, h = item
                if not self.is_closed() and generation == self.pixel_format_generation:
                    self.encode_damage(wid, image, x, y, w, h)
            except Exception as e:
                if self.is_closed():
                    log("ignoring RFB encoding error calling %s because the source is already closed:", item)
                    log(" %s", e)
                else:
                    log.error("Error during RFB encoding:", exc_info=True)
                del e
            finally:
                free_rfb_image(item[2])

    def encode_damage(self, _wid: int, image, x: int, y: int, w: int, h: int) -> None:
        if self.is_closed():
            return
        encode = raw_encode_image
        kwargs = {}
        if self.pixel_format[:2] != (32, 24):
            if self.pixel_format[:3] == (8, 6, 0):
                # crappy initial format chosen by realvnc
                encode = rgb222_encode_image
            else:
                log("damage: unsupported client pixel format: %s", self.pixel_format)
                return
        elif RFBEncoding.TIGHT_PNG in self.encodings:
            encode = tight_png_image
            kwargs = {"speed": self.speed}
        elif RFBEncoding.TIGHT in self.encodings:
            encode = tight_encode_image
            kwargs = {"quality": self.quality, "speed": self.speed}
        elif RFBEncoding.ZLIB in self.encodings:
            encode = zlib_encode_image
            if self.zlib_compressor is None:
                import zlib  # pylint: disable=import-outside-toplevel
                self.zlib_compressor = zlib.compressobj(1)
            kwargs = {"compressor": self.zlib_compressor}
        packets = encode(image, x, y, w, h, **kwargs)
        if not packets:
            return
        self.send_many(*packets)

    def send_many(self, *packets: bytes):
        # merge small packets together:
        joined = []

        def send_joined() -> None:
            if joined:
                self.send(b"".join(joined))
                joined[:] = []

        for packet in packets:
            joined.append(packet)
            if sum(len(p) for p in joined) > PACKET_JOIN_SIZE:
                # too much, can't be joined
                joined.pop()
                send_joined()
                self.send(packet)
        send_joined()

    def send_clipboard(self, text: str) -> None:
        nocr = text.replace("\r", "").encode("latin1")
        msg = struct.pack(b"!BBBBI", 3, 0, 0, 0, len(nocr)) + nocr
        self.send(msg)

    def bell(self, *_args) -> None:
        msg = struct.pack(b"!B", 2)
        self.send(msg)

    def update_mouse(self, _wid: int, x: int, y: int, _rx: int = 0, _ry: int = 0) -> bool:
        # RFB Cursor Position pseudo-encoding (-232): the rect's x,y carry the
        # server-side pointer position; no payload follows. Used to "warp" the
        # viewer's local cursor when something other than this viewer moves it.
        if RFBEncoding.POINTER_POS not in self.encodings:
            return False
        if self.is_closed():
            return False
        if self.last_pointer_pos == (x, y):
            return False
        self.last_pointer_pos = (x, y)
        self.send(make_header(RFBEncoding.POINTER_POS, x, y, 0, 0))
        return True

    def updated_desktop_size(self, root_w: int, root_h: int, _max_w: int = 0, _max_h: int = 0) -> bool:
        if RFBEncoding.DESKTOPSIZE not in self.encodings:
            return False
        if self.is_closed():
            return False
        log("send DesktopSize %ix%i", root_w, root_h)
        self.send(make_header(RFBEncoding.DESKTOPSIZE, 0, 0, root_w, root_h))
        return True

    def send(self, msg: bytes) -> None:
        if p := self.protocol:
            p.send(msg)
