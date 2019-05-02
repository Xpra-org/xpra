# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from socket import error as socket_error

from xpra.os_util import Queue, hexstr, strtobytes
from xpra.util import repr_ellipsized, envint, nonl
from xpra.make_thread import make_thread, start_thread
from xpra.net.protocol import force_flush_queue, exit_queue
from xpra.net.common import ConnectionClosedException          #@UndefinedVariable (pydev false positive)
from xpra.net.bytestreams import ABORT
from xpra.server.rfb.rfb_const import RFBClientMessage, RFBAuth, PIXEL_FORMAT
from xpra.log import Logger

log = Logger("network", "protocol", "rfb")

READ_BUFFER_SIZE = envint("XPRA_READ_BUFFER_SIZE", 65536)


class RFBProtocol(object):
    CONNECTION_LOST = "connection-lost"
    INVALID = "invalid"

    def __init__(self, scheduler, conn, auth, process_packet_cb, get_rfb_pixelformat, session_name="Xpra"):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert scheduler is not None
        assert conn is not None
        self.timeout_add = scheduler.timeout_add
        self.idle_add = scheduler.idle_add
        self._conn = conn
        self._authenticator = auth
        self._process_packet_cb = process_packet_cb
        self._get_rfb_pixelformat = get_rfb_pixelformat
        self.session_name = session_name
        self._write_queue = Queue()
        self._buffer = b""
        self._challenge = None
        self.share = False
        #counters:
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        self._protocol_version = ()
        self._closed = False
        self._packet_parser = self._parse_protocol_handshake
        self._write_thread = None
        self._read_thread = make_thread(self._read_thread_loop, "read", daemon=True)


    def is_closed(self):
        return self._closed


    def send_protocol_handshake(self):
        self.send(b"RFB 003.008\n")

    def _parse_invalid(self, packet):
        return len(packet)

    def _parse_protocol_handshake(self, packet):
        log("parse_protocol_handshake(%s)", nonl(packet))
        if len(packet)<12:
            return 0
        if not packet.startswith(b'RFB '):
            self._invalid_header(packet, "invalid RFB protocol handshake packet header")
            return 0
        #ie: packet==b'RFB 003.008\n'
        self._protocol_version = tuple(int(x) for x in packet[4:11].split(b"."))
        log.info("RFB version %s connection from %s",
                 ".".join(str(x) for x in self._protocol_version), self._conn.target)
        if self._protocol_version!=(3, 8):
            msg = "unsupported protocol version"
            log.error("Error: %s", msg)
            self.send(struct.pack(b"!BI", 0, len(msg))+msg)
            self.invalid(msg, packet)
            return 0
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
        return 12

    def _parse_security_handshake(self, packet):
        log("parse_security_handshake(%s)", hexstr(packet))
        try:
            auth = struct.unpack(b"B", packet)[0]
        except struct.error:
            self._internal_error(packet, "cannot parse security handshake response '%s'" % hexstr(packet))
            return 0
        auth_str = RFBAuth.AUTH_STR.get(auth, auth)
        if auth==RFBAuth.VNC:
            #send challenge:
            self._packet_parser = self._parse_challenge
            assert self._authenticator
            challenge, digest = self._authenticator.get_challenge("des")
            assert digest=="des"
            self._challenge = challenge[:16]
            log("sending RFB challenge value: %s", hexstr(self._challenge))
            self.send(self._challenge)
            return 1
        if self._authenticator and self._authenticator.requires_challenge():
            self._invalid_header(packet, "invalid security handshake response, authentication is required")
            return 0
        log("parse_security_handshake: auth=%s, sending SecurityResult", auth_str)
        #Security Handshake, send SecurityResult Handshake
        self._packet_parser = self._parse_security_result
        self.send(struct.pack(b"!I", 0))
        return 1

    def _parse_challenge(self, response):
        assert self._authenticator
        log("parse_challenge(%s)", hexstr(response))
        try:
            assert len(response)==16
            hex_response = hexstr(response)
            #log("padded password=%s", password)
            if self._authenticator.authenticate(hex_response):
                log("challenge authentication succeeded")
                self.send(struct.pack(b"!I", 0))
                self._packet_parser = self._parse_security_result
                return 16
            log.warn("Warning: authentication challenge response failure")
            log.warn(" password does not match")
        except Exception as e:
            log("parse_challenge(%s)", hexstr(response), exc_info=True)
            log.error("Error: authentication challenge failure:")
            log.error(" %s", e)
        self.timeout_add(1000, self.send_fail_challenge)
        return len(response)

    def send_fail_challenge(self):
        self.send(struct.pack(b"!I", 1))
        self.close()

    def _parse_security_result(self, packet):
        self.share  = packet != b"\0"
        log("parse_security_result: sharing=%s, sending ClientInit with session-name=%s", self.share, self.session_name)
        #send ClientInit
        self._packet_parser = self._parse_rfb
        w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = self._get_rfb_pixelformat()
        packet =  struct.pack(b"!HH"+PIXEL_FORMAT+b"I",
                              w, h, bpp, depth, bigendian, truecolor,
                              rmax, gmax, bmax, rshift, bshift, gshift,
                              0, 0, 0, len(self.session_name))+strtobytes(self.session_name)
        self.send(packet)
        self._process_packet_cb(self, [b"authenticated"])
        return 1

    def _parse_rfb(self, packet):
        try:
            ptype = ord(packet[0])
        except TypeError:
            ptype = packet[0]
        packet_type = RFBClientMessage.PACKET_TYPE_STR.get(ptype)
        if not packet_type:
            self.invalid("unknown RFB packet type: %#x" % ptype, packet)
            return 0
        s = RFBClientMessage.PACKET_STRUCT.get(ptype)     #ie: Struct("!BBBB")
        if not s:
            self.invalid("RFB packet type '%s' is not supported" % packet_type, packet)
            return 0
        if len(packet)<s.size:
            return 0
        size = s.size
        values = list(s.unpack(packet[:size]))
        values[0] = packet_type
        #some packets require parsing extra data:
        if ptype==RFBClientMessage.SETENCODINGS:
            N = values[2]
            estruct = struct.Struct(b"!"+b"i"*N)
            size += estruct.size
            if len(packet)<size:
                return 0
            encodings = estruct.unpack(packet[s.size:size])
            values.append(encodings)
        elif ptype==RFBClientMessage.CLIENTCUTTEXT:
            l = values[4]
            size += l
            if len(packet)<size:
                return 0
            text = packet[s.size:size]
            values.append(text)
        self.input_packetcount += 1
        log("RFB packet: %s: %s", packet_type, values[1:])
        #now trigger the callback:
        self._process_packet_cb(self, values)
        #return part of packet not consumed:
        return size


    def __repr__(self):
        return "RFBProtocol(%s)" % self._conn

    def get_threads(self):
        return tuple(x for x in (
            self._write_thread,
            self._read_thread,
            ) if x is not None)


    def get_info(self, *_args):
        info = {"protocol" : self._protocol_version}
        for t in self.get_threads():
            info.setdefault("thread", {})[t.name] = t.is_alive()
        return info


    def start(self):
        def start_network_read_thread():
            if not self._closed:
                self._read_thread.start()
        self.idle_add(start_network_read_thread)


    def send_disconnect(self, *_args, **_kwargs):
        #no such packet in RFB, just close
        self.close()


    def queue_size(self):
        return self._write_queue.qsize()

    def send(self, packet):
        if self._closed:
            log("connection is closed already, not sending packet")
            return
        if log.is_debug_enabled():
            if len(packet)<=16:
                log("send(%i bytes: %s)", len(packet), hexstr(packet))
            else:
                from xpra.simple_stats import std_unit
                log("send(%sBytes: %s..)", std_unit(len(packet)), hexstr(packet[:16]))
        if self._write_thread is None:
            self.start_write_thread()
        self._write_queue.put(packet)

    def start_write_thread(self):
        self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def _io_thread_loop(self, name, callback):
        try:
            log("io_thread_loop(%s, %s) loop starting", name, callback)
            while not self._closed and callback():
                pass
            log("io_thread_loop(%s, %s) loop ended, closed=%s", name, callback, self._closed)
        except ConnectionClosedException as e:
            log("%s closed", self._conn, exc_info=True)
            if not self._closed:
                #ConnectionClosedException means the warning has been logged already
                self._connection_lost("%s connection %s closed" % (name, self._conn))
        except (OSError, IOError, socket_error) as e:
            if not self._closed:
                self._internal_error("%s connection %s reset" % (name, self._conn), e, exc_info=e.args[0] not in ABORT)
        except Exception as e:
            #can happen during close(), in which case we just ignore:
            if not self._closed:
                log.error("Error: %s on %s failed: %s", name, self._conn, type(e), exc_info=True)
                self.close()

    def _write_thread_loop(self):
        self._io_thread_loop("write", self._write)
    def _write(self):
        buf = self._write_queue.get()
        # Used to signal that we should exit:
        if buf is None:
            log("write thread: empty marker, exiting")
            self.close()
            return False
        con = self._conn
        if not con:
            return False
        while buf and not self._closed:
            written = con.write(buf)
            if written:
                buf = buf[written:]
                self.output_raw_packetcount += 1
        self.output_packetcount += 1
        return True

    def _read_thread_loop(self):
        self._io_thread_loop("read", self._read)
    def _read(self):
        c = self._conn
        if not c:
            return None
        buf = c.read(READ_BUFFER_SIZE)
        #log("read()=%s", repr_ellipsized(buf))
        if not buf:
            log("read thread: eof")
            #give time to the parse thread to call close itself
            #so it has time to parse and process the last packet received
            self.timeout_add(1000, self.close)
            return False
        self.input_raw_packetcount += 1
        self._buffer += buf
        #log("calling %s(%s)", self._packet_parser, repr_ellipsized(self._buffer))
        while self._buffer:
            consumed = self._packet_parser(self._buffer)
            if consumed==0:
                break
            self._buffer = self._buffer[consumed:]
        return True

    def _internal_error(self, message="", exc=None, exc_info=False):
        #log exception info with last log message
        if self._closed:
            return
        ei = exc_info
        if exc:
            ei = None   #log it separately below
        log.error("Error: %s", message, exc_info=ei)
        if exc:
            log.error(" %s", exc, exc_info=exc_info)
        self.idle_add(self._connection_lost, message)

    def _connection_lost(self, message="", exc_info=False):
        log("connection lost: %s", message, exc_info=exc_info)
        self.close()
        return False


    def invalid(self, msg, data):
        self._packet_parser = self._parse_invalid
        self.idle_add(self._process_packet_cb, self, [RFBProtocol.INVALID, msg, data])
        # Then hang up:
        self.timeout_add(1000, self._connection_lost, msg)


    #delegates to invalid_header()
    #(so this can more easily be intercepted and overriden
    # see tcp-proxy)
    def _invalid_header(self, data, msg=""):
        self.invalid_header(self, data, msg)

    def invalid_header(self, _proto, data, msg="invalid packet header"):
        self._packet_parser = self._parse_invalid
        err = "%s: '%s'" % (msg, hexstr(data[:8]))
        if len(data)>1:
            err += " read buffer=%s (%i bytes)" % (repr_ellipsized(data), len(data))
        self.invalid(err, data)


    def gibberish(self, msg, data):
        log("gibberish(%s, %r)", msg, data)
        self.close()


    def close(self):
        log("RFBProtocol.close() closed=%s, connection=%s", self._closed, self._conn)
        if self._closed:
            return
        self._closed = True
        #self.idle_add(self._process_packet_cb, self, [Protocol.CONNECTION_LOST])
        c = self._conn
        if c:
            try:
                log("RFBProtocol.close() calling %s", c.close)
                c.close()
            except IOError:
                log.error("Error closing %s", self._conn, exc_info=True)
            self._conn = None
        self.terminate_queue_threads()
        self._process_packet_cb(self, [RFBProtocol.CONNECTION_LOST])
        self.idle_add(self.clean)
        log("RFBProtocol.close() done")

    def clean(self):
        #clear all references to ensure we can get garbage collected quickly:
        self._write_thread = None
        self._read_thread = None
        self._process_packet_cb = None

    def terminate_queue_threads(self):
        log("terminate_queue_threads()")
        #make all the queue based threads exit by adding the empty marker:
        owq = self._write_queue
        self._write_queue = exit_queue()
        force_flush_queue(owq)
