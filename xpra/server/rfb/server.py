# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from weakref import WeakKeyDictionary

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import repr_ellipsized, bytestostr
from xpra.util.system import is_X11
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.net.rfb.const import RFBEncoding, RFB_KEYNAMES
from xpra.server.rfb.protocol import RFBServerProtocol
from xpra.server.rfb.source import RFBSource
from xpra.server.subsystem.stub import StubSubsystem
from xpra.server import features
from xpra.util.parsing import str_to_bool, parse_number
from xpra.log import Logger


GLib = gi_import("GLib")

log = Logger("rfb")
pointerlog = Logger("rfb", "pointer")
keylog = Logger("rfb", "keyboard")


class RFBServer(StubSubsystem):
    """
        Adds RFB packet handling and the RFB upgrade timer to a server.
    """
    __slots__ = ("X11Keyboard", "_rfb_upgrade", "rfb_buttons", "socket_rfb_upgrade_timer")
    PREFIX = "rfb"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self._rfb_upgrade = 0
        self.rfb_buttons = 0
        self.X11Keyboard = None
        self.socket_rfb_upgrade_timer: WeakKeyDictionary[SocketProtocol, int] = WeakKeyDictionary()

    def init(self, opts) -> None:
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
        if display := self.get_subsystem("display"):
            display.connect("display-geometry-changed", self._on_display_geometry_changed)

    def _on_display_geometry_changed(self, _display) -> None:
        display = self.get_subsystem("display")
        size = display.get_display_size() if display else None
        if not size:
            return
        w, h = size
        for source in self.server._server_sources.values():
            if isinstance(source, RFBSource):
                source.updated_desktop_size(w, h)

    def cleanup_protocol(self, protocol) -> None:
        self.cancel_upgrade_to_rfb_timer(protocol)

    def _get_window_models(self) -> dict:
        window = self.server.get_subsystem("window")
        return window.get_models() if window else {}

    def _get_rfb_desktop_model(self):
        models = tuple(self._get_window_models().keys())
        if not models:
            log.error("RFB: no window models to export, dropping connection")
            return None
        if len(models) != 1:
            log.error("RFB can only handle a single desktop window, found %i", len(models))
        return models[0]

    def _get_rfb_desktop_wid(self):
        ids = tuple(self._get_window_models().values())
        if len(ids) != 1:
            log.error("RFB can only handle a single desktop window, found %i", len(ids))
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
        auth_subsystem = self.get_subsystem("auth")

        def rfb_protocol_class(conn):
            auths = auth_subsystem.make_authenticators("rfb", {}, conn) if auth_subsystem else ()
            assert len(auths) <= 1, "rfb does not support multiple authentication modules"
            auth = None
            if len(auths) == 1:
                auth = auths[0]
            get_ssl_socket_options = getattr(self.server, "get_ssl_socket_options", None)
            ssl_options = get_ssl_socket_options(conn.options) if get_ssl_socket_options else {}
            log("creating RFB protocol with authentication=%s", auth)
            return RFBServerProtocol(conn, auth,
                                     self.process_rfb_packet, self.get_rfb_pixelformat,
                                     self.server.session_name or "Xpra Server",
                                     data, ssl_options)

        p = self.server.do_make_protocol("rfb", conn, {}, rfb_protocol_class)
        log("handle_rfb_connection(%s) protocol=%s", conn, p)
        p.send_protocol_handshake()

    def try_upgrade_to_rfb(self, proto) -> bool:
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto.is_closed():
            log("try_upgrade_to_rfb() protocol is already closed")
            return False
        conn = proto._conn
        log("try_upgrade_to_rfb() input_bytecount=%i", conn.input_bytecount)
        if conn.input_bytecount == 0:
            self.upgrade_protocol_to_rfb(proto)
        return False

    def upgrade_protocol_to_rfb(self, proto: SocketProtocol, data: bytes = b"") -> None:
        conn = proto.steal_connection()
        log("upgrade_protocol_to_rfb(%s) connection=%s", proto, conn)
        self.server._potential_protocols.remove(proto)
        proto.wait_for_io_threads_exit(1)
        conn.set_active(True)
        self.handle_rfb_connection(conn, data)

    def cancel_upgrade_to_rfb_timer(self, protocol) -> None:
        if t := self.socket_rfb_upgrade_timer.pop(protocol, None):
            GLib.source_remove(t)

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
        self.server.disconnect_protocol(proto, "invalid packet: %s" % repr_ellipsized(packet[1:]))

    def _process_rfb_connection_lost(self, proto, packet):
        self.server._process_connection_lost(proto, packet)

    def _process_rfb_authenticated(self, proto, _packet):
        model = self._get_rfb_desktop_model()
        if not model:
            proto.close()
            return
        source = RFBSource(proto, proto.share)
        if sharing := self.get_subsystem("sharing"):
            if err := sharing.parse_hello(source, typedict({"share": proto.share})):
                source.close()
                self.server.disconnect_client(proto, *err.split(":"))
                return
        self.server.accept_connection(proto)
        self.server._server_sources[proto] = source
        # continue in the UI thread:
        GLib.idle_add(self._accept_rfb_source, source)

    def _accept_rfb_source(self, source):
        if display := self.get_subsystem("display"):
            default_refresh_rate = display.DEFAULT_REFRESH_RATE // 1000
            refresh_rate = display.get_refresh_rate_for_value(default_refresh_rate or 50)
            source.set_refresh_rate(refresh_rate)
        if cursor := self.get_subsystem("cursor"):
            source.get_cursor_data_cb = cursor.get_cursor_data
        source.send_cursor()
        if features.keyboard:
            keyboard = self.get_subsystem("keyboard")
            if keyboard:
                source.keyboard_config = keyboard.get_keyboard_config()
                keyboard.set_keymap(source)
        # ugly weak dependency,
        # shadow servers need to be told to start the refresh timer:
        start_refresh = getattr(self.server, "start_refresh", None)
        if start_refresh:
            window = self.server.get_subsystem("window")
            for wid in tuple(window.get_models().values()):
                start_refresh(wid)  # pylint: disable=not-callable

    def _process_rfb_PointerEvent(self, _proto, packet):
        source = self.get_server_source(_proto)
        readonly = self.server.readonly or bool(source and source.effective_readonly())
        if not features.pointer or readonly:
            return
        buttons, x, y = packet[1:4]
        wid = self._get_rfb_desktop_wid()

        def process_pointer_event() -> None:
            pointerlog("RFB PointerEvent(%#x, %s, %s) desktop wid=%#x", buttons, x, y, wid)
            pointer = self.get_subsystem("pointer")
            if not pointer:
                return
            device_id = -1
            pointer._move_pointer(device_id, wid, (x, y))
            if buttons != self.rfb_buttons:
                # figure out which buttons have changed:
                for button in range(8):
                    mask = 2 ** button
                    if buttons & mask != self.rfb_buttons & mask:
                        pressed = bool(buttons & mask)
                        pointerlog(" %spressing button %i", ["un", ""][pressed], 1 + button)
                        pointer.button_action(device_id, 0, 1 + button, pressed, {})
                self.rfb_buttons = buttons

        GLib.idle_add(process_pointer_event)

    def _process_rfb_KeyEvent(self, proto, packet):
        source = self.get_server_source(proto)
        readonly = self.server.readonly or bool(source and source.effective_readonly())
        if not features.keyboard or readonly:
            return
        if not source:
            return
        pressed, p1, p2, key = packet[1:5]
        GLib.idle_add(self.process_rfb_key_event, source, pressed, p1, p2, key)

    def process_rfb_key_event(self, source, pressed, p1, p2, key):
        wid = self._get_rfb_desktop_wid()
        keyname = RFB_KEYNAMES.get(key)
        keylog("RFB KeyEvent(%s, %s, %s, %s) keyname=%s, desktop wid=%#x", pressed, p1, p2, key, keyname, wid)
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
            if keyboard := self.get_subsystem("keyboard"):
                keyboard._handle_key(wid, bool(pressed), keyname, keyval, keycode, modifiers, is_mod, True)

    def _process_rfb_SetEncodings(self, proto, packet):
        encodings = packet[3]
        source = self.get_server_source(proto)
        if not source:
            return
        source.set_encodings(encodings)
        if RFBEncoding.CURSOR in source.encodings:
            GLib.idle_add(source.send_cursor)

    def _process_rfb_SetPixelFormat(self, proto, packet):
        pixel_format = packet[4:14]
        source = self.get_server_source(proto)
        if not source:
            return
        source.set_pixel_format(pixel_format)
        source.last_cursor_sent = ()
        if RFBEncoding.CURSOR in source.encodings:
            GLib.idle_add(source.send_cursor)

    def _process_rfb_FramebufferUpdateRequest(self, proto, packet):
        inc, x, y, w, h = packet[1:6]
        log("RFB: FramebufferUpdateRequest inc=%s, geometry=%s", inc, (x, y, w, h))
        model = self._get_rfb_desktop_model()
        window = self.server.get_subsystem("window")
        source = self.get_server_source(proto)
        if not (window and source and model):
            return
        wid = window.get_wid(model)
        if not inc:
            # full refresh: serve immediately and discard any pending incremental request
            source.pending_request = None
            GLib.idle_add(source.damage, wid, model, x, y, w, h)
            return
        # incremental request: record the rect; the next polling damage
        # event will flush it. If continuous updates are enabled, the
        # polling damage path may already be pushing updates.
        source.request_update(x, y, w, h)

    def _process_rfb_EnableContinuousUpdates(self, proto, packet):
        enable, x, y, w, h = packet[1:6]
        source = self.get_server_source(proto)
        if not source:
            return
        source.set_continuous_updates(bool(enable), x, y, w, h)

    def _process_rfb_ClientCutText(self, _proto, packet):
        # l = packet[4]
        text = packet[5]
        log("RFB got clipboard text: %r", text)
