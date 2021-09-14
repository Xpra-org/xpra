# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from xpra.util import typedict
from xpra.os_util import hexstr, strtobytes
from xpra.net.rfb.rfb_protocol import RFBProtocol
from xpra.net.rfb.rfb_const import RFBAuth, AUTH_STR, CLIENT_INIT
from xpra.log import Logger

log = Logger("network", "protocol", "rfb")
authlog = Logger("auth", "rfb")


class RFBServerProtocol(RFBProtocol):

    def __init__(self, scheduler, conn, auth, process_packet_cb, get_rfb_pixelformat, session_name="Xpra", data=b""):
        self._authenticator = auth
        self._get_rfb_pixelformat = get_rfb_pixelformat
        self.session_name = session_name
        super().__init__(scheduler, conn, process_packet_cb, data=b"")

    def handshake_complete(self):
        log.info("RFB connection from %s", self._conn.target)
        #reply with Security Handshake:
        self._packet_parser = self._parse_security_handshake
        if self._authenticator and self._authenticator.requires_challenge():
            security_types = [RFBAuth.VNC]
        else:
            security_types = [RFBAuth.NONE]
        packet = struct.pack(b"B", len(security_types))
        for x in security_types:
            packet += struct.pack(b"B", x)
        self.send(packet)

    def _parse_security_handshake(self, packet):
        authlog("parse_security_handshake(%s)", hexstr(packet))
        try:
            auth = struct.unpack(b"B", packet)[0]
        except struct.error:
            self._internal_error(packet, "cannot parse security handshake response '%s'" % hexstr(packet))
            return 0
        auth_str = AUTH_STR.get(auth, auth)
        if auth==RFBAuth.VNC:
            #send challenge:
            self._packet_parser = self._parse_challenge
            assert self._authenticator
            challenge, digest = self._authenticator.get_challenge("des")
            assert digest=="des", "invalid digest %r, only 'des' is supported" % digest
            self._challenge = challenge[:16]
            authlog("sending RFB challenge value: %s", hexstr(self._challenge))
            self.send(self._challenge)
            return 1
        if self._authenticator and self._authenticator.requires_challenge():
            self.invalid_header(self, packet, "invalid security handshake response, authentication is required")
            return 0
        authlog("parse_security_handshake: auth=%s, sending SecurityResult", auth_str)
        #Security Handshake, send SecurityResult Handshake
        self._packet_parser = self._parse_security_result
        self.send(struct.pack(b"!I", 0))
        return 1

    def _parse_challenge(self, response):
        authlog("parse_challenge(%s)", hexstr(response))
        if len(response)<16:
            return 0
        assert self._authenticator
        try:
            assert len(response)==16
            hex_response = hexstr(response)
            #log("padded password=%s", password)
            caps = typedict({
                "challenge_response" : hex_response,
                })
            if self._authenticator.authenticate(caps):
                authlog("challenge authentication succeeded")
                self.send(struct.pack(b"!I", 0))
                self._packet_parser = self._parse_security_result
                return 16
            authlog.warn("Warning: authentication challenge response failure")
            authlog.warn(" password does not match")
        except Exception as e:
            authlog("parse_challenge(%s)", hexstr(response), exc_info=True)
            authlog.error("Error: authentication challenge failure:")
            authlog.error(" %s", e)
        self.timeout_add(1000, self.send_fail_challenge)
        return len(response)

    def send_fail_challenge(self):
        self.send(struct.pack(b"!I", 1))
        self.close()

    def _parse_security_result(self, packet):
        self.share  = packet != b"\0"
        authlog("parse_security_result: sharing=%s, sending ClientInit with session-name=%s",
                self.share, self.session_name)
        #send ServerInit
        self._packet_parser = self._parse_rfb
        try:
            sn = self.session_name.encode("utf8")
        except UnicodeEncodeError:
            sn = strtobytes(self.session_name)
        w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = self._get_rfb_pixelformat()
        packet =  struct.pack(CLIENT_INIT,
                              w, h, bpp, depth, bigendian, truecolor,
                              rmax, gmax, bmax, rshift, bshift, gshift,
                              0, 0, 0, len(sn))+sn
        self.send(packet)
        self._process_packet_cb(self, [b"authenticated"])
        return 1
