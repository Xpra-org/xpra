# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import zlib
import struct
from typing import Any
from threading import RLock
from collections.abc import Callable

from xpra.net.common import no_packet, Packet
from xpra.clipboard.targets import TEXT_TARGETS
from xpra.net.rfb.protocol import RFBProtocol
from xpra.net.rfb.const import (
    RFBEncoding, RFBClientMessage, RFBServerMessage, RFBAuth,
    CLIENT_INIT, PIXEL_FORMAT, AUTH_STR, SERVER_PACKET_TYPE_STR, ENCODING_STR, RFB_KEYS,
)
from xpra.util.objects import Scheduler
from xpra.util.str_fn import csv, repr_ellipsized, hexstr
from xpra.log import Logger

log = Logger("network", "protocol", "rfb")

WID = 1

# the pixel format we request from the server: 32-bit little-endian BGRX
# (bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, gshift, bshift)
PIXEL_FORMAT_BGRX = (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
# the matching name we tag RAW draw packets with:
RGB_FORMAT = "BGRX"

# tight: data shorter than this many bytes is sent uncompressed (TIGHT_MIN_TO_COMPRESS):
TIGHT_MIN_TO_COMPRESS = 12


def check_wid(wid) -> bool:
    if wid != WID:
        log("ignoring pointer movement outside the VNC window")
        return False
    return True


class RFBClientProtocol(RFBProtocol):

    def __init__(self, conn,
                 process_packet_cb: Callable[[Any, Packet], None],
                 get_packet_cb: Callable[[], tuple[Packet, bool, bool]] = no_packet,
                 scheduler: Scheduler = None):
        self.next_packet = get_packet_cb
        self.rectangles = 0
        self.position = 0, 0
        self.dimensions = 0, 0
        self.cursor_serial = 0
        self.desktop_resized = False
        # the 4 persistent zlib streams used by the tight encoding:
        self.zlib_streams: list = [None, None, None, None]
        # translate xpra packets into rfb packets:
        self._rfb_converters: dict[str, Callable] = {
            "pointer-position": self.send_pointer_position,
            "button-action": self.send_button_action,
            "key-action": self.send_key_action,
            "configure-window": self.track_window,
            "clipboard-token": self.send_clipboard_token,
        }
        self.send_lock = RLock()
        super().__init__(conn, process_packet_cb, scheduler=scheduler)

    def source_has_more(self) -> None:
        log("source_has_more()")
        if not self.send_lock.acquire(False):
            return
        try:
            while True:
                pdata = self.next_packet()
                rfbdata = pdata[0]
                has_more = pdata[2]
                log("packet: %s", rfbdata[0])
                if handler := self._rfb_converters.get(rfbdata[0]):
                    handler(rfbdata)
                if not has_more:
                    break
        finally:
            self.send_lock.release()

    def send_pointer_position(self, packet) -> None:
        log("send_pointer_position(%s)", packet)
        # ['pointer-position', 1, (3348, 582), ['mod2'], []]
        if not check_wid(packet[1]):
            return
        x, y = packet[2][:2]
        buttons = packet[4]
        button_mask = 0
        for i in range(8):
            if i + 1 in buttons:
                button_mask |= 2 ** i
        self.do_send_pointer_event(button_mask, x, y)

    def send_button_action(self, packet) -> None:
        log("send_button_action(%s)", packet)
        if not check_wid(packet[1]):
            return
        # ["button-action", wid, button, pressed, (x, y), modifiers, buttons]
        # ['button-action', 1, 1, False, (2768, 257), ['mod2'], [1]]
        button = packet.get_u8(2)
        pressed = packet.get_bool(3)
        x, y = packet.get_ints(4)[:2]
        button_mask = 0
        if len(packet) >= 7:
            # the full set of currently pressed buttons is authoritative:
            buttons = packet.get_ints(6)
            for i in range(8):
                if i + 1 in buttons:
                    button_mask |= 2 ** i
        elif pressed:
            # no button list: derive from this button (RFB bit 0 == button 1):
            button_mask |= 2 ** (button - 1)
        self.do_send_pointer_event(button_mask, x, y)

    def do_send_pointer_event(self, button_mask, x, y) -> None:
        # adjust for window position:
        wx, wy = self.position
        self.send_struct(b"!BBHH", RFBClientMessage.PointerEvent, button_mask, x - wx, y - wy)

    def send_key_action(self, packet) -> None:
        log("send_key_action(%s)", packet)
        if not check_wid(packet[1]):
            return
        # ["key-action", "wid", "keyname", "pressed", "modifiers", "keyval", "string", "keycode", "group"]
        keyname = packet[2]
        if len(keyname) == 1:
            keysym = ord(keyname[0])
        else:
            keysym = RFB_KEYS.get(keyname.lower())
        if not keysym:
            log("no keysym found for %s", packet[2:])
            return
        pressed = packet[3]
        self.send_struct(b"!BBHI", RFBClientMessage.KeyEvent, pressed, 0, keysym)

    def send_clipboard_token(self, packet) -> None:
        # ["clipboard-token", selection, targets, target, dtype, dformat, wire-encoding, wire-data, claim, greedy]
        if len(packet) < 8:
            # a bare token (just claiming the selection) carries no data to forward
            return
        target = packet[3]
        dformat = packet[5]
        wire_encoding = packet[6]
        wire_data = packet[7]
        if target not in TEXT_TARGETS or dformat != 8 or wire_encoding != "bytes":
            log("ignoring non-text clipboard token (target=%s, format=%s, encoding=%s)",
                target, dformat, wire_encoding)
            return
        # large values are wrapped in a Compressible, which exposes the bytes as `.data`:
        if not isinstance(wire_data, (bytes, bytearray, memoryview)):
            wire_data = getattr(wire_data, "data", b"")
        wire_data = bytes(wire_data)
        try:
            text = wire_data.decode("utf8")
        except UnicodeDecodeError:
            text = wire_data.decode("latin1")
        log("clipboard token -> ClientCutText (%i characters)", len(text))
        self.send_client_cut_text(text)

    def send_client_cut_text(self, text: str) -> None:
        # RFB cut text is latin1 with no carriage returns:
        data = text.replace("\r", "").encode("latin1", "replace")
        header = struct.pack(b"!BBBBI", RFBClientMessage.ClientCutText, 0, 0, 0, len(data))
        self.send(header + data)

    def track_window(self, packet) -> None:
        log("track_window(%s)", packet)
        if not check_wid(packet[1]):
            return
        self.position = packet[2], packet[3]
        log("window offset: %s", self.position)
        # ["configure-window", self.wid, sx, sy, sw, sh, props, self._resize_counter, state, skip_geometry]

    def handshake_complete(self) -> None:
        log.info("RFB connected to %s", self._conn.target)
        self._packet_parser = self._parse_security_handshake
        self.send_protocol_handshake()

    def _parse_security_handshake(self, packet) -> int:
        log("parse_security_handshake(%s)", hexstr(packet))
        if len(packet) < 1:
            return 0
        n = struct.unpack(b"B", packet[:1])[0]
        if n == 0:
            self._internal_error("cannot parse security handshake " + hexstr(packet))
            return 0
        if len(packet) < 1 + n:
            # wait until we have all the security types:
            return 0
        security_types = struct.unpack(b"B" * n, packet[1:1 + n])
        st = []
        for v in security_types:
            try:
                v = RFBAuth(v)
            except ValueError:
                pass
            st.append(v)
        log("parse_security_handshake(%s) security_types=%s", hexstr(packet), [AUTH_STR.get(v, v) for v in st])
        if not st or RFBAuth.NONE in st:
            auth_type = RFBAuth.NONE
            # go straight to the result:
            self._packet_parser = self._parse_security_result
        elif RFBAuth.VNC in st:
            auth_type = RFBAuth.VNC
            self._packet_parser = self._parse_vnc_security_challenge
        else:
            self._internal_error("no supported security types in %r" % csv(AUTH_STR.get(v, v) for v in st))
            return 0
        self.send_struct(b"B", auth_type)
        return 1 + n

    def _parse_vnc_security_challenge(self, packet) -> int:
        if len(packet) < 16:
            return 0
        challenge = packet[:16]
        log("parse_vnc_security_challenge(%s)", packet)
        auth_caps = {}
        # this will end up calling send_challenge_reply() with the response,
        # the password will be obtained from the client's challenge handlers,
        # which may prompt the user.
        # (see client base for details)
        self._process_packet_cb(self, Packet("challenge", challenge, auth_caps, "des", "none"))
        return 16

    def send_challenge_reply(self, challenge_response) -> None:
        log("send_challenge_reply(%s)", challenge_response)
        self._packet_parser = self._parse_security_result
        import binascii  # pylint: disable=import-outside-toplevel
        self.send(binascii.unhexlify(challenge_response))

    def _parse_security_result(self, packet) -> int:
        if len(packet) < 4:
            return 0
        r = struct.unpack(b"I", packet[:4])[0]
        if r != 0:
            self._internal_error(f"authentication denied, server returned {r}")
            return 0
        log("parse_security_result(%s) success", hexstr(packet))
        self._packet_parser = self._parse_client_init
        share = False
        self.send_struct(b"B", bool(share))
        return 4

    def _parse_client_init(self, packet) -> int:
        log("_parse_client_init(%s)", packet)
        ci_size = struct.calcsize(CLIENT_INIT)
        if len(packet) < ci_size:
            return 0
        # the last item in client init is the length of the session name:
        client_init = struct.unpack(CLIENT_INIT, packet[:ci_size])
        name_size = client_init[-1]
        # do we have enough to parse that too?
        if len(packet) < ci_size + name_size:
            return 0
        # we only use the first 6 fields; the colour masks/shifts are pinned via SetPixelFormat:
        w, h, bpp, depth, bigendian, truecolor = client_init[:6]
        self.dimensions = w, h
        sn = packet[ci_size:ci_size + name_size]
        try:
            session_name = sn.decode("utf8")
        except UnicodeDecodeError:
            session_name = sn.decode("latin1")
        log.info(f"RFB server session {session_name!r}: {w}x{h} {depth} bits")
        log(f"bpp={bpp}, bigendian={bool(bigendian)}")
        if not truecolor:
            self.invalid("server is not true color", packet)
            return 0
        # simulate hello:
        self._process_packet_cb(self, Packet("hello", {
            "session-name": session_name,
            "desktop_size": (w, h),
            "protocol": "rfb",
            # advertise a (text-only) clipboard so the client forwards local
            # clipboard changes to us, which we relay as RFB ClientCutText:
            "clipboard": {
                "enabled": True,
                "direction": "both",
                "selections": ("CLIPBOARD", ),
                "greedy": True,
                "want_targets": ("UTF8_STRING", "STRING", "TEXT", "text/plain", "text/plain;charset=utf-8"),
                "preferred-targets": ("UTF8_STRING", "STRING", "TEXT", "text/plain"),
            },
            # we render the cursor locally from the RFB Cursor pseudo-encoding:
            "cursor": {"enabled": True},
        }))
        # simulate an xpra window packet:
        metadata = {
            "title": session_name,
            "size-constraints": {
                "maximum-size": (w, h),
                "minimum-size": (w, h),
            },
            "window-type": ("NORMAL",),
            "has-alpha": False,
            "content-type": "desktop",
        }
        client_properties = {}
        self._process_packet_cb(self, Packet("new-window", WID, 0, 0, w, h, metadata, client_properties))
        self._packet_parser = self._parse_rfb_packet
        self.send_set_pixel_format()
        self.send_set_encodings()
        # request the whole framebuffer once;
        # subsequent (incremental) requests are sent each time we finish an update:
        self.request_screen_update(0)
        return ci_size + name_size

    def send_set_pixel_format(self) -> None:
        # pin a known pixel format so RAW rectangles have an unambiguous layout;
        # servers that honour this will then match what we tag our draw packets with:
        self.send_struct(b"!BBBB" + PIXEL_FORMAT,
                         RFBClientMessage.SetPixelFormat, 0, 0, 0,
                         *PIXEL_FORMAT_BGRX, 0, 0, 0)

    def send_set_encodings(self) -> None:
        # advertise the cursor and desktop-size pseudo-encodings, then TIGHT (JPEG) with RAW as the fallback:
        encodings = (
            RFBEncoding.CURSOR, RFBEncoding.DESKTOPSIZE, RFBEncoding.EXTENDEDDESKTOPSIZE,
            RFBEncoding.TIGHT, RFBEncoding.RAW,
        )
        self.send_struct(b"!BBH" + b"i" * len(encodings),
                         RFBClientMessage.SetEncodings, 0, len(encodings), *encodings)

    def request_screen_update(self, incremental: int) -> None:
        w, h = self.dimensions
        self.send_refresh_request(incremental, 0, 0, w, h)

    def send_refresh_request(self, incremental, x, y, w, h) -> None:
        self.send_struct(b"!BBHHHH", RFBClientMessage.FramebufferUpdateRequest, incremental, x, y, w, h)

    def _parse_rfb_packet(self, packet) -> int:
        log("parse_rfb_packet(%s)", repr_ellipsized(packet))
        if len(packet) < 1:
            return 0
        msgtype = packet[0]
        if msgtype == RFBServerMessage.FRAMEBUFFERUPDATE:
            return self._parse_framebuffer_update(packet)
        if msgtype == RFBServerMessage.SERVERCUTTEXT:
            return self._parse_server_cut_text(packet)
        if msgtype == RFBServerMessage.BELL:
            return self._parse_bell(packet)
        if msgtype == RFBServerMessage.SETCOLORMAPENTRIES:
            return self._parse_set_colourmap(packet)
        # we cannot know the length of an unknown message, so we cannot skip it:
        self.invalid("unsupported RFB server message %s (%r)" % (
            msgtype, SERVER_PACKET_TYPE_STR.get(msgtype, msgtype)), packet)
        return 0

    def _parse_framebuffer_update(self, packet) -> int:
        # message-type (u8), padding (u8), number-of-rectangles (u16)
        if len(packet) < 4:
            return 0
        self.rectangles = struct.unpack(b"!H", packet[2:4])[0]
        log("%i rectangles coming up", self.rectangles)
        if self.rectangles > 0:
            self._packet_parser = self._parse_rectangle
        else:
            # empty update: request the next one straight away
            self.request_screen_update(1)
        return 4

    def _parse_server_cut_text(self, packet) -> int:
        # message-type (u8), padding (3 x u8), length (u32), text (latin1)
        header_size = 8
        if len(packet) < header_size:
            return 0
        length = struct.unpack(b"!I", packet[4:8])[0]
        if len(packet) < header_size + length:
            return 0
        text = packet[header_size:header_size + length].decode("latin1")
        log("server cut text: %i characters", length)
        self.set_client_clipboard(text)
        return header_size + length

    def set_client_clipboard(self, text: str) -> None:
        # deliver the server's clipboard to the local clipboard by synthesizing an
        # incoming clipboard token that carries the text inline (as utf8 bytes);
        # the dispatcher routes this UI packet to the main thread for us:
        data = text.encode("utf8")
        token = Packet("clipboard-token", "CLIPBOARD", ("UTF8_STRING", ),
                       "UTF8_STRING", "UTF8_STRING", 8, "bytes", data, True, False)
        self._process_packet_cb(self, token)

    def _parse_bell(self, _packet) -> int:
        log("bell")
        self._process_packet_cb(self, Packet("bell", WID, 0, 100, 0, 0, 0, 0, ""))
        return 1

    def _parse_set_colourmap(self, packet) -> int:
        # message-type (u8), padding (u8), first-colour (u16), number-of-colours (u16), then 6 bytes per colour
        header_size = 6
        if len(packet) < header_size:
            return 0
        ncolours = struct.unpack(b"!H", packet[4:6])[0]
        size = header_size + ncolours * 6
        if len(packet) < size:
            return 0
        log("ignoring %i colourmap entries (truecolor)", ncolours)
        return size

    def _parse_rectangle(self, packet) -> int:
        header_size = struct.calcsize(b"!HHHHi")
        if len(packet) < header_size:
            return 0
        x, y, w, h, encoding = struct.unpack(b"!HHHHi", packet[:header_size])
        body = packet[header_size:]
        if encoding == RFBEncoding.RAW:
            consumed = self._parse_raw_rectangle(x, y, w, h, body)
        elif encoding == RFBEncoding.TIGHT:
            consumed = self._parse_tight_rectangle(x, y, w, h, body)
        elif encoding == RFBEncoding.CURSOR:
            consumed = self._parse_cursor(x, y, w, h, body)
        elif encoding == RFBEncoding.DESKTOPSIZE:
            consumed = self._parse_desktop_size(x, y, w, h, body)
        elif encoding == RFBEncoding.EXTENDEDDESKTOPSIZE:
            consumed = self._parse_extended_desktop_size(x, y, w, h, body)
        else:
            self.invalid("unsupported encoding: %s" % ENCODING_STR.get(encoding, encoding), packet)
            return 0
        if consumed < 0:
            # the rectangle body is not fully buffered yet:
            return 0
        self.rectangles -= 1
        if self.rectangles == 0:
            self._packet_parser = self._parse_rfb_packet
            # the update is complete: ask for the next changes
            # (a full update if the desktop was just resized, otherwise incremental)
            self.request_screen_update(0 if self.desktop_resized else 1)
            self.desktop_resized = False
        return header_size + consumed

    def _parse_raw_rectangle(self, x: int, y: int, w: int, h: int, body) -> int:
        size = w * h * 4
        if len(body) < size:
            return -1
        log("raw screen update: %s", (x, y, w, h))
        pixels = body[:size]
        draw = Packet("draw", WID, x, y, w, h, "rgb32", pixels, 0, w * 4, {"rgb_format": RGB_FORMAT})
        self._process_packet_cb(self, draw)
        return size

    def _parse_cursor(self, x: int, y: int, w: int, h: int, body) -> int:
        # RFB Cursor pseudo-encoding: x,y are the hotspot; the body is w*h pixels
        # (in our BGRX format) followed by a 1-bpp, byte-aligned transparency mask:
        pixel_size = w * h * 4
        mask_stride = (w + 7) // 8
        total = pixel_size + mask_stride * h
        if len(body) < total:
            return -1
        if w == 0 or h == 0:
            # an empty cursor: nothing to display
            return total
        pixels = body[:pixel_size]
        mask = body[pixel_size:total]
        # combine the BGRX pixels with the mask into a BGRA cursor image:
        bgra = bytearray(pixel_size)
        for row in range(h):
            mask_row = row * mask_stride
            for col in range(w):
                i = (row * w + col) * 4
                bgra[i] = pixels[i]          # B
                bgra[i + 1] = pixels[i + 1]  # G
                bgra[i + 2] = pixels[i + 2]  # R
                opaque = (mask[mask_row + (col >> 3)] >> (7 - (col & 7))) & 1
                bgra[i + 3] = 0xFF if opaque else 0
        self.cursor_serial += 1
        log("cursor update: %ix%i, hotspot=%s", w, h, (x, y))
        cursor = Packet("cursor-data", "raw", w, h, x, y, self.cursor_serial, bytes(bgra), "")
        self._process_packet_cb(self, cursor)
        return total

    def _parse_desktop_size(self, x: int, y: int, w: int, h: int, body) -> int:
        # DesktopSize pseudo-encoding: w,h are the new framebuffer size; no data follows
        self._resize_desktop(w, h)
        return 0

    def _parse_extended_desktop_size(self, x: int, y: int, w: int, h: int, body) -> int:
        # ExtendedDesktopSize: w,h are the new size; the body is a screen layout we skip over:
        # number-of-screens (u8), padding (3 bytes), then 16 bytes per screen
        if len(body) < 4:
            return -1
        screens = body[0]
        size = 4 + screens * 16
        if len(body) < size:
            return -1
        self._resize_desktop(w, h)
        return size

    def _resize_desktop(self, w: int, h: int) -> None:
        if (w, h) == self.dimensions:
            return
        log.info("RFB desktop resized to %ix%i", w, h)
        self.dimensions = w, h
        self.desktop_resized = True
        # lift the fixed size-constraints to the new size, then move/resize the window:
        metadata = {
            "size-constraints": {
                "maximum-size": (w, h),
                "minimum-size": (w, h),
            },
        }
        self._process_packet_cb(self, Packet("window-metadata", WID, metadata))
        self._process_packet_cb(self, Packet("window-move-resize", WID, 0, 0, w, h))

    def _parse_tight_rectangle(self, x: int, y: int, w: int, h: int, body) -> int:
        # the rectangle starts with a compression-control byte:
        #   bits 0-3: which zlib streams to reset
        #   high nibble 0x8 -> fill, 0x9 -> jpeg, bit 7 clear -> basic (zlib) compression
        if len(body) < 1:
            return -1
        control = body[0]
        reset = control & 0x0F
        comp = control >> 4
        if comp == 0x08:
            return self._parse_tight_fill(x, y, w, h, body, 1, reset)
        if comp == 0x09:
            return self._parse_tight_jpeg(x, y, w, h, body, 1, reset)
        if comp & 0x08:
            self.invalid("unsupported tight compression 0x%02x" % control, body)
            return -1
        # basic compression: optional filter-id byte, then (maybe zlib-compressed) pixel data
        # bits 4-5 select the zlib stream, bit 6 signals an explicit filter-id:
        stream_id = comp & 0x03
        pos = 1
        filter_id = 0
        if comp & 0x04:
            if len(body) < pos + 1:
                return -1
            filter_id = body[pos]
            pos += 1
        if filter_id == 0:      # copy
            return self._parse_tight_copy(x, y, w, h, body, pos, stream_id, reset)
        if filter_id == 1:      # palette
            return self._parse_tight_palette(x, y, w, h, body, pos, stream_id, reset)
        if filter_id == 2:      # gradient
            return self._parse_tight_gradient(x, y, w, h, body, pos, stream_id, reset)
        self.invalid("unsupported tight filter %i" % filter_id, body)
        return -1

    def _parse_tight_fill(self, x, y, w, h, body, pos, reset) -> int:
        # a single TPIXEL (3 bytes, R-G-B) that fills the whole rectangle:
        if len(body) < pos + 3:
            return -1
        self._tight_reset_streams(reset)
        rgb = bytes(body[pos:pos + 3]) * (w * h)
        self._draw_rgb(x, y, w, h, rgb)
        return pos + 3

    def _parse_tight_jpeg(self, x, y, w, h, body, pos, reset) -> int:
        length, length_size = self._parse_tight_length(body, pos)
        if length < 0:
            return -1
        start = pos + length_size
        if len(body) < start + length:
            return -1
        self._tight_reset_streams(reset)
        jpeg_data = bytes(body[start:start + length])
        log("tight jpeg update: %i bytes for %s", length, (x, y, w, h))
        draw = Packet("draw", WID, x, y, w, h, "jpeg", jpeg_data, 0, 0, {})
        self._process_packet_cb(self, draw)
        return start + length

    def _parse_tight_copy(self, x, y, w, h, body, pos, stream_id, reset) -> int:
        rgb, newpos = self._tight_read_data(body, pos, stream_id, reset, w * h * 3)
        if rgb is None:
            return -1
        self._draw_rgb(x, y, w, h, rgb)
        return newpos

    def _parse_tight_palette(self, x, y, w, h, body, pos, stream_id, reset) -> int:
        if len(body) < pos + 1:
            return -1
        num_colors = body[pos] + 1
        pos += 1
        palette_size = num_colors * 3
        if len(body) < pos + palette_size:
            return -1
        palette = bytes(body[pos:pos + palette_size])
        pos += palette_size
        # 2 colors -> 1 bit per pixel (rows padded to a byte), otherwise 1 byte per pixel:
        row_size = (w + 7) // 8 if num_colors <= 2 else w
        data, newpos = self._tight_read_data(body, pos, stream_id, reset, row_size * h)
        if data is None:
            return -1
        rgb = self._tight_depalette(data, w, h, num_colors, palette, row_size)
        self._draw_rgb(x, y, w, h, rgb)
        return newpos

    def _parse_tight_gradient(self, x, y, w, h, body, pos, stream_id, reset) -> int:
        data, newpos = self._tight_read_data(body, pos, stream_id, reset, w * h * 3)
        if data is None:
            return -1
        rgb = self._tight_degradient(data, w, h)
        self._draw_rgb(x, y, w, h, rgb)
        return newpos

    def _draw_rgb(self, x, y, w, h, rgb) -> None:
        # tight pixel data is in R,G,B order, 3 bytes per pixel:
        draw = Packet("draw", WID, x, y, w, h, "rgb24", rgb, 0, w * 3, {"rgb_format": "RGB"})
        self._process_packet_cb(self, draw)

    def _tight_reset_streams(self, reset: int) -> None:
        for i in range(4):
            if reset & (1 << i):
                self.zlib_streams[i] = None

    def _tight_read_data(self, body, pos: int, stream_id: int, reset: int, size: int):
        # reads `size` uncompressed bytes; returns (data, new-position), or (None, pos) if incomplete.
        # data below TIGHT_MIN_TO_COMPRESS is sent uncompressed, otherwise it is a
        # compact-length prefix followed by that many bytes from the zlib stream:
        if size < TIGHT_MIN_TO_COMPRESS:
            if len(body) < pos + size:
                return None, pos
            self._tight_reset_streams(reset)
            return bytes(body[pos:pos + size]), pos + size
        length, length_size = self._parse_tight_length(body, pos)
        if length < 0:
            return None, pos
        start = pos + length_size
        if len(body) < start + length:
            return None, pos
        self._tight_reset_streams(reset)
        stream = self.zlib_streams[stream_id]
        if stream is None:
            stream = self.zlib_streams[stream_id] = zlib.decompressobj()
        data = stream.decompress(bytes(body[start:start + length]))
        if len(data) != size:
            log.warn("Warning: tight zlib produced %i bytes, expected %i", len(data), size)
        return data, start + length

    @staticmethod
    def _tight_depalette(data, w, h, num_colors, palette, row_size) -> bytes:
        out = bytearray(w * h * 3)
        o = 0
        if num_colors <= 2:
            for yy in range(h):
                rowstart = yy * row_size
                for xx in range(w):
                    bit = (data[rowstart + (xx >> 3)] >> (7 - (xx & 7))) & 1
                    p = bit * 3
                    out[o] = palette[p]
                    out[o + 1] = palette[p + 1]
                    out[o + 2] = palette[p + 2]
                    o += 3
        else:
            for i in range(w * h):
                p = data[i] * 3
                out[o] = palette[p]
                out[o + 1] = palette[p + 1]
                out[o + 2] = palette[p + 2]
                o += 3
        return bytes(out)

    @staticmethod
    def _tight_degradient(data, w, h) -> bytes:
        # reverse the gradient prediction: actual = (residual + clamp(left + up - upleft)) % 256
        out = bytearray(w * h * 3)
        stride = w * 3
        for yy in range(h):
            for xx in range(w):
                for c in range(3):
                    i = yy * stride + xx * 3 + c
                    left = out[i - 3] if xx > 0 else 0
                    up = out[i - stride] if yy > 0 else 0
                    upleft = out[i - 3 - stride] if (xx > 0 and yy > 0) else 0
                    pred = left + up - upleft
                    if pred < 0:
                        pred = 0
                    elif pred > 255:
                        pred = 255
                    out[i] = (data[i] + pred) & 0xFF
        return bytes(out)

    @staticmethod
    def _parse_tight_length(body, offset: int) -> tuple[int, int]:
        # tight "compact" length: 1 to 3 bytes, 7 bits each, high bit signals continuation;
        # returns (length, number-of-bytes-used), or (-1, 0) if more data is needed
        if len(body) < offset + 1:
            return -1, 0
        b0 = body[offset]
        length = b0 & 0x7F
        if not b0 & 0x80:
            return length, 1
        if len(body) < offset + 2:
            return -1, 0
        b1 = body[offset + 1]
        length |= (b1 & 0x7F) << 7
        if not b1 & 0x80:
            return length, 2
        if len(body) < offset + 3:
            return -1, 0
        b2 = body[offset + 2]
        length |= (b2 & 0x7F) << 14
        return length, 3

    def send_struct(self, fmt: bytes, *args) -> None:
        packet = struct.pack(fmt, *args)
        self.send(packet)
