# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.os_util import gi_import
from xpra.util.str_fn import repr_ellipsized, bytestostr
from xpra.util.system import is_X11
from xpra.net.bytestreams import set_socket_timeout
from xpra.net.rfb.const import RFB_KEYNAMES
from xpra.server.rfb.protocol import RFBServerProtocol
from xpra.server.rfb.source import RFBSource
from xpra.server import features
from xpra.scripts.config import str_to_bool, parse_number
from xpra.log import Logger


GLib = gi_import("GLib")

log = Logger("rfb")
pointerlog = Logger("rfb", "pointer")
keylog = Logger("rfb", "keyboard")


class RFBServer:
    """
        Adds RFB packet handler to a server.
    """

    def __init__(self):
        self._window_to_id = {}
        self._rfb_upgrade = 0
        self.readonly = False
        self.rfb_buttons = 0
        self.x11_keycodes_for_keysym = {}
        self.X11Keyboard = None

    def init(self, opts):
        if not str_to_bool(opts.rfb_upgrade):
            self._rfb_upgrade = 0
        else:
            self._rfb_upgrade = parse_number(int, "rfb-upgrade", opts.rfb_upgrade, 0)
        log("init(..) rfb-upgrade=%i", self._rfb_upgrade)

    def setup(self) -> None:
        if is_X11():
            try:
                from xpra.x11.bindings.keyboard import X11KeyboardBindings
                self.X11Keyboard = X11KeyboardBindings()
            except ImportError:
                log("RFBServer", exc_info=True)
                log.warn("Warning: no x11 bindings")
                log.warn(" some RFB keyboard events may be missing")

    def _get_rfb_desktop_model(self):
        models = tuple(self._window_to_id.keys())
        if not models:
            log.error("RFB: no window models to export, dropping connection")
            return None
        if len(models) != 1:
            log.error("RFB can only handle a single desktop window, found %i", len(self._window_to_id))
            return None
        return models[0]

    def _get_rfb_desktop_wid(self):
        ids = tuple(self._window_to_id.values())
        if len(ids) != 1:
            log.error("RFB can only handle a single desktop window, found %i", len(self._window_to_id))
            return None
        return ids[0]

    def handle_rfb_connection(self, conn, data=b"") -> None:
        if data and data[:4] != b"RFB ":
            raise ValueError("packet is not a valid RFB connection")

        model = self._get_rfb_desktop_model()
        log("handle_rfb_connection(%s) model=%s", conn, model)
        if not model:
            log("no desktop model, closing RFB connection")
            conn.close()
            return

        def rfb_protocol_class(conn):
            auths = self.make_authenticators("rfb", {}, conn)
            assert len(auths) <= 1, "rfb does not support multiple authentication modules"
            auth = None
            if len(auths) == 1:
                auth = auths[0]
            log("creating RFB protocol with authentication=%s", auth)
            return RFBServerProtocol(conn, auth,
                                     self.process_rfb_packet, self.get_rfb_pixelformat,
                                     self.session_name or "Xpra Server",
                                     data)

        p = self.do_make_protocol("rfb", conn, {}, rfb_protocol_class)
        log("handle_rfb_connection(%s) protocol=%s", conn, p)
        p.send_protocol_handshake()

    def process_rfb_packet(self, proto, packet):
        # log("RFB packet: '%s'", packet)
        fn_name = "_process_rfb_%s" % bytestostr(packet[0]).replace("-", "_")
        fn = getattr(self, fn_name, None)
        if not fn:
            log.warn("Warning: no RFB handler for %s", fn_name)
            return
        fn(proto, packet)

    def get_rfb_pixelformat(self) -> tuple[int, int, int, int, bool, bool, int, int, int, int, int, int]:
        model = self._get_rfb_desktop_model()
        w, h = model.get_dimensions()
        # w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift
        return w, h, 32, 24, False, True, 255, 255, 255, 16, 8, 0

    def _process_rfb_invalid(self, proto, packet):
        self.disconnect_protocol(proto, "invalid packet: %s" % repr_ellipsized(packet[1:]))

    def _process_rfb_connection_lost(self, proto, packet):
        self._process_connection_lost(proto, packet)

    def _process_rfb_authenticated(self, proto, _packet):
        model = self._get_rfb_desktop_model()
        if not model:
            proto.close()
            return
        self.accept_protocol(proto)
        # use blocking sockets from now on:
        set_socket_timeout(proto._conn, None)
        accepted, share_count, disconnected = self.handle_sharing(proto, share=proto.share)
        log("RFB handle sharing: accepted=%s, share count=%s, disconnected=%s", accepted, share_count, disconnected)
        if not accepted:
            return
        source = RFBSource(proto, proto.share)
        self._server_sources[proto] = source
        # continue in the UI thread:
        GLib.idle_add(self._accept_rfb_source, source)

    def _accept_rfb_source(self, source):
        if features.keyboard:
            source.keyboard_config = self.get_keyboard_config()
            self.set_keymap(source)
        model = self._get_rfb_desktop_model()
        w, h = model.get_dimensions()
        source.damage(self._window_to_id[model], model, 0, 0, w, h)
        # ugly weak dependency,
        # shadow servers need to be told to start the refresh timer:
        start_refresh = getattr(self, "start_refresh", None)
        if start_refresh:
            for wid in tuple(self._window_to_id.values()):
                start_refresh(wid)  # pylint: disable=not-callable

    def _process_rfb_PointerEvent(self, _proto, packet):
        if not features.pointer or self.readonly:
            return
        buttons, x, y = packet[1:4]
        wid = self._get_rfb_desktop_wid()

        def process_pointer_event() -> None:
            pointerlog("RFB PointerEvent(%#x, %s, %s) desktop wid=%s", buttons, x, y, wid)
            device_id = -1
            self._move_pointer(device_id, wid, (x, y))
            if buttons != self.rfb_buttons:
                # figure out which buttons have changed:
                for button in range(8):
                    mask = 2 ** button
                    if buttons & mask != self.rfb_buttons & mask:
                        pressed = bool(buttons & mask)
                        pointerlog(" %spressing button %i", ["un", ""][pressed], 1 + button)
                        self.button_action(device_id, 0, (x, y), 1 + button, pressed)
                self.rfb_buttons = buttons

        GLib.idle_add(process_pointer_event)

    def _process_rfb_KeyEvent(self, proto, packet):
        if not features.keyboard or self.readonly:
            return
        source = self.get_server_source(proto)
        if not source:
            return
        pressed, p1, p2, key = packet[1:5]
        GLib.idle_add(self.process_rfb_key_event, source, pressed, p1, p2, key)

    def process_rfb_key_event(self, source, pressed, p1, p2, key):
        wid = self._get_rfb_desktop_wid()
        keyname = RFB_KEYNAMES.get(key)
        keylog("RFB KeyEvent(%s, %s, %s, %s) keyname=%s, desktop wid=%s", pressed, p1, p2, key, keyname, wid)
        if not keyname:
            if 0 < key < 255:
                keyname = chr(key)
            elif self.X11Keyboard:
                keyname = self.X11Keyboard.keysym_str(key)
        if not keyname:
            keylog.warn("Warning: unknown rfb KeyEvent: %s, %i, %i, %#x", pressed, p1, p2, key)
            return
        modifiers = []
        keyval = 0
        keycode, group = source.keyboard_config.get_keycode(0, keyname, pressed, modifiers, 0, keyname, 0)
        keylog("RFB keycode(%s)=%s, %s", keyname, keycode, group)
        if keycode:
            is_mod = source.keyboard_config.is_modifier(keycode)
            self._handle_key(wid, bool(pressed), keyname, keyval, keycode, modifiers, is_mod, True)

    def _process_rfb_SetEncodings(self, proto, packet):
        encodings = packet[3]
        self._server_sources[proto].set_encodings(encodings)

    def _process_rfb_SetPixelFormat(self, proto, packet):
        pixel_format = packet[4:14]
        self._server_sources[proto].set_pixel_format(pixel_format)

    def _process_rfb_FramebufferUpdateRequest(self, _proto, packet):
        # pressed, _, _, keycode = packet[1:5]
        inc, x, y, w, h = packet[1:6]
        log("RFB: FramebufferUpdateRequest inc=%s, geometry=%s", inc, (x, y, w, h))
        if not inc:
            model = self._get_rfb_desktop_model()
            GLib.idle_add(self.refresh_window_area, model, x, y, w, h)

    def _process_rfb_ClientCutText(self, _proto, packet):
        # l = packet[4]
        text = packet[5]
        log("RFB got clipboard text: %r", text)
