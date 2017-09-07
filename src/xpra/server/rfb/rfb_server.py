# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util import nonl, csv
from xpra.os_util import POSIX, OSX
from xpra.server.rfb.rfb_const import RFBEncoding, RFB_KEYNAMES
from xpra.server.rfb.rfb_protocol import RFBProtocol
from xpra.server.rfb.rfb_source import RFBSource
 
from xpra.log import Logger
log = Logger("rfb")


"""
    Adds RFB packet handler to a server.
"""
class RFBServer(object):

    def init(self):
        self.rfb_buttons = 0
        self.x11_keycodes_for_keysym = {}
        if POSIX and not OSX:
            from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
            self.X11Keyboard = X11KeyboardBindings()


    def _get_rfb_desktop_model(self):
        models = self._window_to_id.keys()
        if len(models)!=1:
            log.error("RFB can only handle a single desktop window, found %i", len(self._window_to_id))
            return None
        return models[0]

    def _get_rfb_desktop_wid(self):
        ids = self._window_to_id.values()
        if len(ids)!=1:
            log.error("RFB can only handle a single desktop window, found %i", len(self._window_to_id))
            return None
        return ids[0]


    def handle_rfb_connection(self, conn):
        model = self._get_rfb_desktop_model()
        if not model:
            conn.close()
            return
        def rfb_protocol_class(conn):
            auth = self.make_authenticator("rfb", "rfb", conn)
            return RFBProtocol(self, conn, auth, self.process_rfb_packet, self.get_rfb_pixelformat, self.session_name or "Xpra Server")
        p = self.do_make_protocol("rfb", conn, rfb_protocol_class)
        p.send_protocol_handshake()

    def process_rfb_packet(self, proto, packet):
        #log("RFB packet: '%s'", nonl(packet))
        fn_name = "_process_rfb_%s" % packet[0]
        fn = getattr(self, fn_name, None)
        if not fn:
            log.warn("Warning: no RFB handler for %s", fn_name)
            return
        self.idle_add(fn, proto, packet)


    def get_rfb_pixelformat(self):
        model = self._get_rfb_desktop_model()
        w, h = model.get_dimensions()
        #w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift
        return w, h, 32, 32, False, True, 255, 255, 255, 16, 8, 0

    def _process_rfb_invalid(self, proto, packet):
        self.disconnect_protocol(proto, "invalid packet: %s" % (packet[1:]))

    def _process_rfb_authenticated(self, proto, _packet):
        model = self._get_rfb_desktop_model()
        if not model:
            proto.close()
            return
        self.accept_protocol(proto)
        #use blocking sockets from now on:
        from xpra.net.bytestreams import set_socket_timeout
        set_socket_timeout(proto._conn, None)
        server_exit, share_count, disconnected = self.handle_sharing(proto, share=proto.share)
        log("rfb handle sharing: server exit=%s, share count=%s, disconnected=%s", server_exit, share_count, disconnected)
        if server_exit:
            return
        source = RFBSource(proto, self._get_rfb_desktop_model(), proto.share)
        source.keyboard_config = self.get_keyboard_config({})
        self._server_sources[proto] = source
        w, h = model.get_dimensions()
        source.damage(self._window_to_id[model], model, 0, 0, w, h)
        #ugly weak dependency,
        #shadow servers need to be told to start the refresh timer:
        start_refresh = getattr(self, "start_refresh", None)
        if start_refresh:
            start_refresh()

    def _process_rfb_PointerEvent(self, _proto, packet):
        buttons, x, y = packet[1:4]
        wid = self._get_rfb_desktop_wid()
        self._move_pointer(wid, (x, y))
        if buttons!=self.rfb_buttons:
            #figure out which buttons have changed:
            for button in range(8):
                mask = 2**button
                if buttons & mask != self.rfb_buttons & mask:
                    pressed = bool(buttons & mask)
                    self.button_action((x, y), 1+button, pressed, -1)
            self.rfb_buttons = buttons

    def _process_rfb_KeyEvent(self, proto, packet):
        source = self._server_sources.get(proto)
        if not source:
            return
        pressed, p1, p2, key = packet[1:5]
        wid = self._get_rfb_desktop_wid()
        keyname = RFB_KEYNAMES.get(key)
        if not keyname:
            if 0<key<255:
                keyname = chr(key)
            elif self.X11Keyboard:
                keyname = self.X11Keyboard.keysym_str(key)
        if not keyname:
            log.warn("rfb unknown KeyEvent: %s, %i, %i, %#x", pressed, p1, p2, key)
            return
        modifiers = []
        keyval = 0
        keycode = source.keyboard_config.get_keycode(0, keyname, modifiers)
        log("rfb keycode(%s)=%s", keyname, keycode)
        if keycode:
            self._handle_key(wid, bool(pressed), keyname, keyval, keycode, modifiers)

    def _process_rfb_SetEncodings(self, _proto, packet):
        n, encodings = packet[2:4]
        known_encodings = [RFBEncoding.ENCODING_STR.get(x) for x in encodings if x in RFBEncoding.ENCODING_STR]
        log("%i encodings: %s", n, csv(known_encodings))
        unknown_encodings = [x for x in encodings if x not in RFBEncoding.ENCODING_STR]
        if unknown_encodings:
            log("%i unknown encodings: %s", len(unknown_encodings), csv(unknown_encodings))

    def _process_rfb_SetPixelFormat(self, _proto, packet):
        log("RFB: SetPixelFormat %s", packet)
        #w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = packet

    def _process_rfb_FramebufferUpdateRequest(self, _proto, packet):
        #pressed, _, _, keycode = packet[1:5]
        inc, x, y, w, h = packet[1:6]
        if not inc:
            model = self._get_rfb_desktop_model()
            self._damage(model, x, y, w, h)

    def _process_rfb_ClientCutText(self, _proto, packet):
        #l = packet[4]
        text = packet[5]
        log("got rfb clipboard text: %s", nonl(text))
