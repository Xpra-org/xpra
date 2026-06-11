# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from queue import SimpleQueue
from threading import Event
from typing import Any
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.net.rfb.const import RFBEncoding, RFBServerMessage
from xpra.net.rfb.encode import (
    make_header, raw_encode_image, tight_encode_image, tight_png_image, rgb222_encode_image, zlib_encode_image,
)
from xpra.net.protocol.socket_handler import PACKET_JOIN_SIZE
from xpra.server.source.stub import PointerSource
from xpra.server.window.compress import free_image_wrapper  # pylint: disable=import-outside-toplevel
from xpra.util.rectangle import rectangle, add_rectangle, merge_all
from xpra.util.objects import AtomicInteger
from xpra.util.parsing import str_to_bool
from xpra.util.str_fn import csv, memoryview_to_bytes
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("rfb")

GLib = gi_import("GLib")

counter = AtomicInteger()

RFB_ENCODE_QUEUE_MAX_SIZE = 2
RFB_DAMAGE_DELAY = 20
RFB_DAMAGE_DELAY_MIN = 10
RFB_DAMAGE_DELAY_MAX = 100
RFB_MIN_WINDOW_REGION_SIZE = 1024
RFB_MAX_SMALL_REGIONS = 40
RFB_MAX_BYTES_PERCENT = 60
RFB_SMALL_PACKET_COST = 1024
RFB_TINY_REGION_SIZE = 4096
RFB_LOW_QUALITY = 50

ENCODE_REGION = tuple[Any, int, int, int, int, RFBEncoding]
ENCODE_ITEM = None | tuple[int, int, tuple[ENCODE_REGION, ...]]


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
        "connection_readonly", "control_readonly", "client_readonly",
        "encodings", "quality", "speed", "pixel_format",
        "get_cursor_data_cb", "last_cursor_sent",
        "zlib_compressor",
        "continuous_updates", "cu_rect", "pending_request",
        "last_pointer_pos",
        "damage_delay", "damage_timer", "damage_rectangles", "damage_clip", "damage_wid", "damage_window",
        "encode_queue", "encode_thread", "pixel_format_generation",
    )

    def __init__(self, protocol, share=False):
        self.protocol = protocol
        self.close_event = Event()
        self.counter = 0
        self.share = share
        self.uuid = "RFB%5i" % counter.increase()
        self.lock = False
        conn = getattr(protocol, "_conn", None)
        options = getattr(conn, "options", None) or {}
        self.connection_readonly = bool(str_to_bool(options.get("readonly", False)))
        self.control_readonly = False
        self.client_readonly = False
        self.keyboard_config = None
        self.encodings = [RFBEncoding.RAW]
        self.pixel_format = (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.pixel_format_generation = 0
        self.quality = 0
        self.speed = 0
        self.get_cursor_data_cb = nocursordata
        self.last_cursor_sent = ()
        self.zlib_compressor = None
        # default to request-driven mode. Clients that support the continuous
        # updates extension can opt into push updates with message 150.
        self.continuous_updates = False
        self.cu_rect: tuple[int, int, int, int] | None = None
        self.pending_request: tuple[int, int, int, int] | None = None
        self.last_pointer_pos: tuple[int, int] | None = None
        self.damage_delay = RFB_DAMAGE_DELAY
        self.damage_timer = 0
        self.damage_rectangles: list[rectangle] = []
        self.damage_clip: rectangle | None = None
        self.damage_wid = 0
        self.damage_window = None
        self.encode_queue: SimpleQueue[ENCODE_ITEM] = SimpleQueue()
        self.encode_thread = start_thread(self.encode_loop, f"rfb-encode-{self.uuid}", daemon=True)

    def get_info(self) -> dict[str, Any]:
        return {
            "protocol": "rfb",
            "uuid": self.uuid,
            "share": self.share,
            "readonly": self.effective_readonly(),
            "quality": self.quality,
            "speed": self.speed,
            "damage-delay": self.damage_delay,
            "damage-timer": self.damage_timer,
            "damage-rectangles": len(self.damage_rectangles),
            "encode-queue": self.encode_queue.qsize(),
        }

    def effective_readonly(self) -> bool:
        return self.connection_readonly or self.control_readonly or self.client_readonly

    def server_enforced_readonly(self) -> bool:
        return self.connection_readonly or self.control_readonly

    def set_control_readonly(self, readonly: bool) -> None:
        self.control_readonly = bool(readonly)

    def send_setting_change(self, *_args) -> None:
        # RFB clients do not understand Xpra setting-change packets.
        return None

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

    def set_refresh_rate(self, refresh_rate: int) -> None:
        if refresh_rate <= 0:
            self.damage_delay = RFB_DAMAGE_DELAY
        else:
            self.damage_delay = max(RFB_DAMAGE_DELAY_MIN, min(RFB_DAMAGE_DELAY_MAX, 1000 // refresh_rate))
        log("RFB damage delay set to %ims for refresh rate %s", self.damage_delay, refresh_rate)

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
        self.cancel_damage_timer()
        self.damage_rectangles = []
        self.damage_clip = None
        self.damage_window = None
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
        region = rectangle(x, y, w, h)
        if polling and not self.continuous_updates:
            if self.pending_request is None and not self.damage_rectangles:
                return
            if self.pending_request:
                self.add_damage_clip(rectangle(*self.pending_request))
                self.pending_request = None
            if self.damage_clip:
                if not (region := region.intersection_rect(self.damage_clip)):
                    return
        elif polling and self.continuous_updates and self.cu_rect:
            if not (region := region.intersection(*self.cu_rect)):
                return
        elif not polling and not self.continuous_updates and not self.damage_rectangles:
            # A non-incremental FramebufferUpdateRequest is already limited to
            # the requested rect. Use it as the batch clip so any polling damage
            # that arrives before the timer fires cannot expand the reply.
            self.damage_clip = region
        self.add_damage_rectangle(_wid, window, region)

    def add_damage_clip(self, clip: rectangle) -> None:
        if not self.damage_clip:
            self.damage_clip = clip
            return
        self.damage_clip = merge_all((self.damage_clip, clip))

    def add_damage_rectangle(self, wid: int, window, region: rectangle) -> None:
        if region.width <= 0 or region.height <= 0:
            return
        schedule = not self.damage_rectangles
        add_rectangle(self.damage_rectangles, region)
        self.damage_wid = wid
        self.damage_window = window
        if schedule:
            self.schedule_damage()

    def schedule_damage(self, delay: int = 0) -> None:
        if self.damage_timer or self.is_closed():
            return
        if delay <= 0:
            delay = self.damage_delay
        self.damage_timer = GLib.timeout_add(max(1, delay), self.process_damage_timer)

    def cancel_damage_timer(self) -> None:
        if timer := self.damage_timer:
            self.damage_timer = 0
            GLib.source_remove(timer)

    def process_damage_timer(self) -> bool:
        self.damage_timer = 0
        self.process_damage()
        return False

    def process_damage(self) -> None:
        if self.is_closed():
            return
        damage = self.damage_rectangles
        if not damage:
            return
        p = self.protocol
        if p is None:
            self.damage_rectangles = []
            self.damage_clip = None
            self.damage_window = None
            return
        if p.queue_size() >= 2 or self.encode_queue.qsize() >= RFB_ENCODE_QUEUE_MAX_SIZE:
            self.schedule_damage()
            return
        wid = self.damage_wid
        window = self.damage_window
        self.damage_rectangles = []
        self.damage_clip = None
        self.damage_window = None
        self.send_regions(wid, window, damage)

    def get_window_dimensions(self, window, regions: Sequence[rectangle]) -> tuple[int, int]:
        if get_dimensions := getattr(window, "get_dimensions", None):
            return get_dimensions()
        full = merge_all(regions)
        return full.x + full.width, full.y + full.height

    def send_regions(self, wid: int, window, regions: Sequence[rectangle]) -> None:
        ww, wh = self.get_window_dimensions(window, regions)
        if ww <= 0 or wh <= 0:
            return
        unique_regions = []
        for region in regions:
            if region not in unique_regions:
                unique_regions.append(region)
        regions = tuple(unique_regions)

        def full_window_update(cause: str) -> tuple[rectangle, ...]:
            log("send_regions: using full window update %sx%s: %s", ww, wh, cause)
            return (rectangle(0, 0, ww, wh),)

        if len(regions) > RFB_MAX_SMALL_REGIONS:
            regions = full_window_update(f"too many regions: {len(regions)}")
        elif ww * wh <= RFB_MIN_WINDOW_REGION_SIZE:
            regions = full_window_update(f"small window: {ww}x{wh}")
        elif len(regions) > 1:
            merge_threshold = ww * wh * RFB_MAX_BYTES_PERCENT // 100
            pixel_count = sum(r.width * r.height for r in regions)
            packet_cost = pixel_count + RFB_SMALL_PACKET_COST * len(regions)
            if packet_cost >= merge_threshold:
                regions = full_window_update(f"bytes cost ({packet_cost}) too high (max {merge_threshold})")
            else:
                merged = merge_all(regions)
                merged_pixel_count = merged.width * merged.height
                merged_packet_cost = merged_pixel_count + RFB_SMALL_PACKET_COST
                log("send_regions: merged=%s, merged_cost=%s, packet_cost=%s, pixels=%s",
                    merged, merged_packet_cost, packet_cost, pixel_count)
                if merged_packet_cost < packet_cost or merged_pixel_count < pixel_count:
                    regions = (merged,)

        if not regions:
            return
        if len(regions) == 1:
            merged = regions[0]
            if merged.x <= 1 and merged.y <= 1 and abs(ww - merged.width) < 2 and abs(wh - merged.height) < 2:
                regions = full_window_update("merged region covers almost the whole window")

        encode_regions = []
        window.acknowledge_changes()
        for region in regions:
            image = window.get_image(region.x, region.y, region.width, region.height)
            if image is None:
                continue
            encoding = self.get_region_encoding(region.width, region.height)
            encode_regions.append((image, region.x, region.y, region.width, region.height, encoding))
        if not encode_regions:
            return
        self.encode_queue.put((self.pixel_format_generation, wid, tuple(encode_regions)))

    def encode_loop(self) -> None:
        while True:
            item = self.encode_queue.get(True)
            if item is None:
                return
            try:
                generation, wid, regions = item
                if not self.is_closed() and generation == self.pixel_format_generation:
                    self.encode_regions(wid, regions)
            except Exception as e:
                if self.is_closed():
                    log("ignoring RFB encoding error calling %s because the source is already closed:", item)
                    log(" %s", e)
                else:
                    log.error("Error during RFB encoding:", exc_info=True)
                del e
            finally:
                for region in item[2]:
                    free_rfb_image(region[0])

    def get_region_encoding(self, w: int, h: int) -> RFBEncoding:
        if self.pixel_format[:2] != (32, 24):
            return RFBEncoding.RAW
        pixels = w * h
        encodings = self.encodings
        if pixels <= RFB_TINY_REGION_SIZE and RFBEncoding.ZLIB in encodings:
            return RFBEncoding.ZLIB
        if RFBEncoding.TIGHT in encodings and 0 < self.quality <= RFB_LOW_QUALITY:
            return RFBEncoding.TIGHT
        if RFBEncoding.TIGHT_PNG in encodings:
            return RFBEncoding.TIGHT_PNG
        if RFBEncoding.TIGHT in encodings:
            return RFBEncoding.TIGHT
        if RFBEncoding.ZLIB in encodings:
            return RFBEncoding.ZLIB
        return RFBEncoding.RAW

    def encode_regions(self, _wid: int, regions: Sequence[ENCODE_REGION]) -> None:
        if self.is_closed():
            return
        encoded_regions: list[tuple[bytes, ...]] = []
        for image, x, y, w, h, encoding in regions:
            packets = self.encode_region(image, x, y, w, h, encoding)
            if packets:
                encoded_regions.append((packets[0][4:],) + tuple(packets[1:]))
        if not encoded_regions:
            return
        packets = [struct.pack(b"!BBH", RFBServerMessage.FRAMEBUFFERUPDATE, 0, len(encoded_regions))]
        for encoded in encoded_regions:
            packets.extend(encoded)
        self.send_many(*packets)

    def encode_region(self, image, x: int, y: int, w: int, h: int,
                      encoding: RFBEncoding = RFBEncoding.RAW) -> Sequence[bytes]:
        if self.is_closed():
            return ()
        encode = raw_encode_image
        kwargs = {}
        if self.pixel_format[:2] != (32, 24):
            if self.pixel_format[:3] == (8, 6, 0):
                # crappy initial format chosen by realvnc
                encode = rgb222_encode_image
            else:
                log("damage: unsupported client pixel format: %s", self.pixel_format)
                return ()
        elif encoding == RFBEncoding.TIGHT_PNG:
            encode = tight_png_image
            kwargs = {"speed": self.speed}
        elif encoding == RFBEncoding.TIGHT:
            encode = tight_encode_image
            kwargs = {"quality": self.quality, "speed": self.speed}
        elif encoding == RFBEncoding.ZLIB:
            encode = zlib_encode_image
            if self.zlib_compressor is None:
                import zlib  # pylint: disable=import-outside-toplevel
                self.zlib_compressor = zlib.compressobj(1)
            kwargs = {"compressor": self.zlib_compressor}
        return encode(image, x, y, w, h, **kwargs)

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
