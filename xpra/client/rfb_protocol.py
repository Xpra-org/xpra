# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from xpra.net.rfb.rfb_protocol import RFBProtocol
from xpra.net.rfb.rfb_const import RFBEncoding, RFBClientMessage, RFBAuth, CLIENT_INIT, AUTH_STR
from xpra.os_util import hexstr, bytestostr
from xpra.util import repr_ellipsized, csv
from xpra.log import Logger

log = Logger("network", "protocol", "rfb")

WID = 1


class RFBClientProtocol(RFBProtocol):

    def __init__(self, scheduler, conn, process_packet_cb, next_packet):
        #TODO: start a thread to process this:
        self.next_packet = next_packet
        self.rectangles = 0
        super().__init__(scheduler, conn, process_packet_cb)

    def source_has_more(self):
        log("source_has_more()")
        while True:
            pdata = self.next_packet()
            packet = pdata[0]
            start_send_cb = pdata[1]
            end_send_cb = pdata[2]
            has_more = pdata[5]
            if start_send_cb:
                start_send_cb()
            log("packet: %s", packet[0])
            if end_send_cb:
                end_send_cb()
            if not has_more:
                break
            #packet, start_send_cb=None, end_send_cb=None, fail_cb=None, synchronous=True, has_more=False, wait_for_more=False)

    def handshake_complete(self):
        log.info("RFB connected to %s", self._conn.target)
        self._packet_parser = self._parse_security_handshake
        self.send_protocol_handshake()

    def _parse_security_handshake(self, packet):
        log("parse_security_handshake(%s)", hexstr(packet))
        n = struct.unpack(b"B", packet[:1])[0]
        if n==0:
            self._internal_error("cannot parse security handshake '%s'" % hexstr(packet))
            return 0
        security_types = struct.unpack(b"B"*n, packet[1:])
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
            #go straight to the result:
            self._packet_parser = self._parse_security_result
        elif RFBAuth.VNC in st:
            auth_type = RFBAuth.VNC
            self._packet_parser = self._parse_vnc_security_challenge
        else:
            self._internal_error("no supported security types in %r" % csv(AUTH_STR.get(v, v) for v in st))
            return 0
        packet = struct.pack(b"B", auth_type)
        self.send(packet)
        return 1+n

    def _parse_vnc_security_challenge(self, packet):
        if len(packet)<16:
            return 0
        challenge = packet[:16]
        password = b"vnc123"
        from xpra.net.d3des import generate_response
        password = password.ljust(8, b"\x00")[:8]
        challenge = challenge.ljust(16, b"\x00")[:16]
        data = generate_response(password, challenge)
        self._packet_parser = self._parse_security_result
        self.send(data)
        return 16

    def _parse_security_result(self, packet):
        if len(packet)<4:
            return 0
        r = struct.unpack(b"I", packet[:4])[0]
        if r!=0:
            self._internal_error("authentication denied, server returned %i" % r)
            return 0
        log("parse_security_result(%s) success", hexstr(packet))
        self._packet_parser = self._parse_client_init
        share = False
        packet = struct.pack(b"B", bool(share))
        self.send(packet)
        return 4

    def _parse_client_init(self, packet):
        log("_parse_client_init(%s)", packet)
        ci_size = struct.calcsize(CLIENT_INIT)
        if len(packet)<ci_size:
            return 0
        #the last item in client init is the length of the session name:
        client_init = struct.unpack(CLIENT_INIT, packet[:ci_size])
        name_size =  client_init[-1]
        #do we have enough to parse that too?
        if len(packet)<ci_size+name_size:
            return 0
        w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = client_init[:12]
        session_name = bytestostr(packet[ci_size:ci_size+name_size])
        log.info("RFB server session '%s': %ix%i %i bits", session_name, w, h, depth)
        if not truecolor:
            self.invalid("server is not true color", packet)
            return 0
        #simulate hello:
        self._process_packet_cb(self, ["hello", {
            "session-name"  : session_name,
            "desktop_size"  : (w, h),
            "protocol"      : "rfb",
            }])
        #simulate an xpra window packet:
        metadata = {
            "title" : session_name,
            "size-constraints" : {
                "maximum-size" : (w, h),
                "minimum-size" : (w, h),
                },
            #"set-initial-position" : False,
            "window-type" : ("NORMAL",),
            "has-alpha" : False,
            #"decorations" : True,
            "content-type" : "desktop",
            }
        client_properties = {}
        self._process_packet_cb(self, ["new-window", WID, 0, 0, w, h, metadata, client_properties])
        self._packet_parser = self._parse_rfb_packet
        self.send_set_encodings()
        #self.send_refresh_request(0, 0, 0, w, h)
        def request_refresh():
            self.send_refresh_request(0, 0, 0, w, h)
            return True
        self.timeout_add(1000, request_refresh)
        return ci_size+name_size

    def send_set_encodings(self):
        packet = struct.pack("!BBHi", RFBClientMessage.SetEncodings, 0, 1, RFBEncoding.RAW)
        self.send(packet)

    def send_refresh_request(self, incremental, x, y, w, h):
        packet = struct.pack("!BBHHHH", RFBClientMessage.FramebufferUpdateRequest, incremental, x, y, w, h)
        self.send(packet)

    def _parse_rfb_packet(self, packet):
        log("parse_rfb_packet(%s)", repr_ellipsized(packet))
        if len(packet)<=4:
            return 0
        if packet[:2]!=struct.pack(b"!BB", 0, 0):
            self.invalid("unknown packet", packet)
            return 0
        self.rectangles = struct.unpack(b"!H", packet[2:4])[0]
        log("%i rectangles coming up")
        if self.rectangles>0:
            self._packet_parser = self._parse_rectangle
        return 4

    def _parse_rectangle(self, packet):
        header_size = struct.calcsize(b"!HHHHi")
        if len(packet)<=header_size:
            return 0
        x, y, w, h, encoding = struct.unpack(b"!HHHHi", packet[:header_size])
        if encoding!=RFBEncoding.RAW:
            self.invalid("invalid encoding: %s" % encoding, packet)
            return 0
        log("screen update: %s", (x, y, w, h))
        if len(packet)<header_size + w*h*4:
            return 0
        pixels = packet[header_size:header_size + w*h*4]
        draw = ["draw", WID, x, y, w, h, "rgb32", pixels, 0, w*4, {}]
        self._process_packet_cb(self, draw)
        self.rectangles -= 1
        if self.rectangles==0:
            self._packet_parser = self._parse_rfb_packet
        return header_size + w*h*4
