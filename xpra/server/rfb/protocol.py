# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import strtobytes, hexstr, csv
from xpra.net.rfb.protocol import RFBProtocol, READ_BUFFER_SIZE
from xpra.net.rfb.const import RFBAuth, RFBVeNCrypt, AUTH_STR, VENCRYPT_STR, CLIENT_INIT
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network", "protocol", "rfb")
authlog = Logger("auth")


class RFBServerProtocol(RFBProtocol):

    def __init__(self, conn, auth, process_packet_cb, get_rfb_pixelformat, session_name="Xpra", data=b"",
                 ssl_options: dict | None = None):
        self._authenticator = auth
        self._get_rfb_pixelformat = get_rfb_pixelformat
        self.session_name = session_name
        self._ssl_options = ssl_options or {}
        self._vencrypt_subtypes: tuple[RFBVeNCrypt, ...] = ()
        self._vencrypt_subtype = 0
        super().__init__(conn, process_packet_cb, data=data)

    def handshake_complete(self) -> None:
        log.info("RFB connection from %s", self._conn.target)
        # reply with Security Handshake:
        self._packet_parser = self._parse_security_handshake
        if self._authenticator and self._authenticator.requires_challenge():
            security_types = [RFBAuth.VNC]
            self._vencrypt_subtypes = (RFBVeNCrypt.X509VNC, )
        else:
            security_types = [RFBAuth.NONE]
            self._vencrypt_subtypes = (RFBVeNCrypt.X509NONE, )
        if self._can_use_vencrypt():
            security_types.insert(0, RFBAuth.VeNCrypt)
        packet = struct.pack(b"B", len(security_types))
        for x in security_types:
            packet += struct.pack(b"B", x)
        self.send(packet)

    def _can_use_vencrypt(self) -> bool:
        return bool(self._ssl_options.get("cert"))

    def _parse_security_handshake(self, rfbdata) -> int:
        authlog("parse_security_handshake(%s)", hexstr(rfbdata))
        if len(rfbdata) < 1:
            return 0
        try:
            auth = RFBAuth(struct.unpack(b"B", rfbdata[:1])[0])
        except struct.error:
            self._internal_error(rfbdata, "cannot parse security handshake response '%s'" % hexstr(rfbdata))
            return 0
        except ValueError:
            self.invalid_header(self, rfbdata, "invalid security handshake response")
            return 0
        auth_str = AUTH_STR.get(auth, auth)
        if auth == RFBAuth.VeNCrypt:
            if not self._can_use_vencrypt():
                self.invalid_header(self, rfbdata, "VeNCrypt is not available")
                return 0
            authlog("parse_security_handshake: auth=%s, sending VeNCrypt version", auth_str)
            self._packet_parser = self._parse_vencrypt_version
            self.send_struct(b"BB", 0, 2)
            return 1
        if auth == RFBAuth.VNC:
            self._send_challenge()
            return 1
        if self._authenticator and self._authenticator.requires_challenge():
            self.invalid_header(self, rfbdata, "invalid security handshake response, authentication is required")
            return 0
        authlog("parse_security_handshake: auth=%s, sending SecurityResult", auth_str)
        # Security Handshake, send SecurityResult Handshake
        self._packet_parser = self._parse_security_result
        self.send(struct.pack(b"!I", 0))
        return 1

    def _parse_vencrypt_version(self, rfbdata) -> int:
        if len(rfbdata) < 2:
            return 0
        client_version = (rfbdata[0], rfbdata[1])
        authlog("parse_vencrypt_version: client version=%i.%i", *client_version)
        if client_version != (0, 2):
            self.send_struct(b"B", 1)
            self._internal_error("unsupported VeNCrypt version %i.%i" % client_version)
            return 0
        self._packet_parser = self._parse_vencrypt_subtype
        self.send_struct(b"B", 0)
        subtypes = self._vencrypt_subtypes
        packet = struct.pack(b"!B", len(subtypes))
        for subtype in subtypes:
            packet += struct.pack(b"!I", subtype)
        authlog("sending VeNCrypt sub-types: %s", csv(VENCRYPT_STR.get(v, v) for v in subtypes))
        self.send(packet)
        self.read_buffer_size = 4
        return 2

    def _parse_vencrypt_subtype(self, rfbdata) -> int:
        if len(rfbdata) < 4:
            return 0
        self.read_buffer_size = READ_BUFFER_SIZE
        subtype = struct.unpack(b"!I", rfbdata[:4])[0]
        try:
            subtype = RFBVeNCrypt(subtype)
        except ValueError:
            self._send_vencrypt_subtype_ack(False)
            self._internal_error("unsupported VeNCrypt sub-type %s" % subtype)
            return 0
        authlog("parse_vencrypt_subtype: client selected %s", VENCRYPT_STR.get(subtype, subtype))
        if subtype not in self._vencrypt_subtypes:
            self._send_vencrypt_subtype_ack(False)
            self._internal_error("unsupported VeNCrypt sub-type %s" % VENCRYPT_STR.get(subtype, subtype))
            return 0
        self._vencrypt_subtype = subtype
        if not self._send_vencrypt_subtype_ack(True):
            return 0
        self._upgrade_to_tls()
        return 4

    def _send_vencrypt_subtype_ack(self, accepted: bool) -> bool:
        conn = self._conn
        try:
            sock = conn.get_raw_socket()
            sock.setblocking(True)
            sock.sendall(struct.pack(b"B", int(accepted)))
        except Exception as e:
            log("send VeNCrypt sub-type ack", exc_info=True)
            self._internal_error("failed to send VeNCrypt sub-type acknowledgement", e)
            return False
        return True

    def _upgrade_to_tls(self) -> None:
        subtype = self._vencrypt_subtype
        log("upgrading RFB connection to TLS using VeNCrypt %s", VENCRYPT_STR.get(subtype, subtype))
        conn = self._conn
        try:
            from xpra.net.tls.socket import ssl_wrap_socket, ssl_handshake
            from xpra.net.tls.connection import SSLSocketConnection
        except ImportError as e:
            self._internal_error("cannot use TLS for VeNCrypt: %s" % e)
            return
        raw_sock = conn.get_raw_socket()
        raw_sock.setblocking(True)
        ssl_options = dict(self._ssl_options)
        ssl_options["server_side"] = True
        try:
            ssl_sock = ssl_wrap_socket(raw_sock, **ssl_options)
            if not ssl_sock:
                self._internal_error("failed to wrap the socket for VeNCrypt TLS")
                return
            ssl_handshake(ssl_sock)
        except Exception as e:
            log("_upgrade_to_tls()", exc_info=True)
            self._internal_error("VeNCrypt TLS handshake failed", e)
            return
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint,
                                       conn.socktype, socket_options=conn.options)
        ssl_conn.target = conn.target
        ssl_conn.timeout = conn.timeout
        self._conn = ssl_conn
        log.info("RFB connection upgraded to TLS: %s", ssl_sock.version())
        if subtype == RFBVeNCrypt.X509VNC:
            self._send_challenge()
        else:
            self._packet_parser = self._parse_security_result
            self.send(struct.pack(b"!I", 0))

    def _send_challenge(self) -> None:
        self._packet_parser = self._parse_challenge
        assert self._authenticator
        challenge, digest = self._authenticator.get_challenge(("des", ))
        assert digest == "des", "invalid digest %r, only 'des' is supported" % digest
        self._challenge = challenge[:16]
        authlog("sending RFB challenge value: %s", hexstr(self._challenge))
        self.send(self._challenge)

    def _parse_challenge(self, response) -> int:
        authlog("parse_challenge(%s)", hexstr(response))
        if len(response) < 16:
            return 0
        assert self._authenticator
        try:
            assert len(response) == 16
            hex_response = hexstr(response)
            # log("padded password=%s", password)
            caps = typedict({
                "challenge_response": hex_response,
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
            authlog.estr(e)
        GLib.timeout_add(1000, self.send_fail_challenge)
        return len(response)

    def send_fail_challenge(self) -> None:
        self.send(struct.pack(b"!I", 1))
        self.close()

    def _parse_security_result(self, rfbdata) -> int:
        self.share = rfbdata != b"\0"
        authlog("parse_security_result: sharing=%s, sending ClientInit with session-name=%s",
                self.share, self.session_name)
        # send ServerInit
        self._packet_parser = self._parse_rfb
        try:
            sn = self.session_name.encode("utf8")
        except UnicodeEncodeError:
            sn = strtobytes(self.session_name)
        w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = self._get_rfb_pixelformat()
        packet = struct.pack(CLIENT_INIT,
                             w, h, bpp, depth, bigendian, truecolor,
                             rmax, gmax, bmax, rshift, bshift, gshift,
                             0, 0, 0, len(sn)) + sn
        self.send(packet)
        self._process_packet_cb(self, [b"authenticated"])
        return 1
