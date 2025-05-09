# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from time import monotonic
from socket import error as socket_error
from collections.abc import Callable, Sequence
from queue import Queue

from xpra.os_util import gi_import
from xpra.util.str_fn import repr_ellipsized, hexstr
from xpra.util.env import envint
from xpra.util.thread import make_thread, start_thread
from xpra.util.stats import std_unit
from xpra.net.protocol.socket_handler import force_flush_queue, exit_queue
from xpra.net.protocol.constants import INVALID, CONNECTION_LOST
from xpra.net.common import Packet, ConnectionClosedException  # @UndefinedVariable (pydev false positive)
from xpra.net.bytestreams import ABORT
from xpra.net.rfb.const import RFBClientMessage, CLIENT_PACKET_TYPE_STR, PACKET_STRUCT
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network", "protocol", "rfb")

RFB_LOG = os.environ.get("XPRA_RFB_LOG", "")
READ_BUFFER_SIZE = envint("XPRA_READ_BUFFER_SIZE", 65536)

PROTOCOL_VERSION = (3, 8)


class RFBProtocol:
    TYPE = "rfb"

    def __init__(self, conn, process_packet_cb, data=b""):
        if not conn:
            raise ValueError(f"no connection: {conn}")
        self.start_time = monotonic()
        self._conn = conn
        self._process_packet_cb = process_packet_cb
        self._write_queue = Queue()
        self._buffer = data
        self._challenge = None
        self.share = False
        # counters:
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        self._closed = False
        self._packet_parser = self._parse_protocol_handshake
        self._write_thread = None
        self._read_thread = make_thread(self._read_thread_loop, "read", daemon=True)
        self.log = None
        if RFB_LOG:
            # pylint: disable=consider-using-with
            self.log = open(RFB_LOG, "w", encoding="utf8")

    def is_closed(self) -> bool:
        return self._closed

    # noinspection PyMethodMayBeStatic
    def is_sending_encrypted(self) -> bool:
        return False

    def send_protocol_handshake(self) -> None:
        self.send(b"RFB 003.008\n")

    # noinspection PyMethodMayBeStatic
    def _parse_invalid(self, rfbdata) -> int:
        return len(rfbdata)

    def _parse_protocol_handshake(self, rfbdata) -> int:
        log(f"parse_protocol_handshake({rfbdata})")
        if len(rfbdata) < 12:
            return 0
        if not rfbdata.startswith(b'RFB '):
            self.invalid_header(self, rfbdata, "invalid RFB protocol handshake rfbdata header")
            return 0
        # ie: rfbdata==b'RFB 003.008\n'
        protocol_version = tuple(int(x) for x in rfbdata[4:11].split(b"."))
        if protocol_version != PROTOCOL_VERSION:
            msg = b"unsupported protocol version"
            log.error(f"Error: {msg!r}")
            self.send(struct.pack(b"!BI", 0, len(msg)) + msg)
            self.invalid(msg, rfbdata)
            return 0
        self.handshake_complete()
        return 12

    def handshake_complete(self) -> None:
        raise NotImplementedError

    def _parse_security_handshake(self, rfbdata) -> int:
        raise NotImplementedError

    def _parse_challenge(self, response) -> int:
        raise NotImplementedError

    def _parse_security_result(self, rfbdata) -> int:
        raise NotImplementedError

    def _parse_rfb(self, rfbdata) -> int:
        try:
            ptype = ord(rfbdata[0])
        except TypeError:
            ptype = rfbdata[0]
        packet_type = CLIENT_PACKET_TYPE_STR.get(ptype)
        if not packet_type:
            self.invalid(f"unknown RFB packet type: {ptype:x}", rfbdata)
            return 0
        s = PACKET_STRUCT.get(ptype)  # ie: Struct("!BBBB")
        if not s:
            self.invalid(f"RFB rfbdata type {packet_type!r} is not supported", rfbdata)
            return 0
        if len(rfbdata) < s.size:
            return 0
        size = s.size
        values = list(s.unpack(rfbdata[:size]))
        values[0] = packet_type
        # some packets require parsing extra data:
        if ptype == RFBClientMessage.SetEncodings:
            N = values[2]
            estruct = struct.Struct(b"!" + b"i" * N)
            size += estruct.size
            if len(rfbdata) < size:
                return 0
            encodings = estruct.unpack(rfbdata[s.size:size])
            values.append(encodings)
        elif ptype == RFBClientMessage.ClientCutText:
            count = values[4]
            size += count
            if len(rfbdata) < size:
                return 0
            text = rfbdata[s.size:size]
            values.append(text)
        self.input_packetcount += 1
        log(f"RFB packet: {packet_type}: {values[1:]}")
        # now trigger the callback:
        self._process_packet_cb(self, values)
        # return part of packet not consumed:
        return size

    def __repr__(self):
        return f"RFBProtocol({self._conn})"

    def get_threads(self) -> tuple:
        return tuple(x for x in (self._write_thread, self._read_thread) if x is not None)

    def get_info(self, *_args) -> dict[str, Sequence[int] | dict[str, bool]]:
        info: dict[str, tuple | dict] = {
            "protocol": PROTOCOL_VERSION,
            "thread": dict((thread.name, thread.is_alive()) for thread in self.get_threads()),
        }
        return info

    def start(self) -> None:
        def start_network_read_thread() -> None:
            if not self._closed:
                self._read_thread.start()

        GLib.idle_add(start_network_read_thread)

    def send_disconnect(self, *_args, **_kwargs) -> None:
        # no such packet in RFB, just close
        self.close()

    def queue_size(self) -> int:
        return self._write_queue.qsize()

    def send(self, rfbdata) -> None:
        if self._closed:
            log("connection is closed already, not sending packet")
            return
        if log.is_debug_enabled():
            size = len(rfbdata)
            lstr = str(size) if size <= 16 else std_unit(size)
            log(f"send({lstr} bytes: %s..)", hexstr(rfbdata[:16]))
        if self.log:
            self.log.write(f"send: {hexstr(rfbdata)}\n")
        if self._write_thread is None:
            self.start_write_thread()
        self._write_queue.put(rfbdata)

    def start_write_thread(self) -> None:
        log("rfb: starting write thread")
        self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def _io_thread_loop(self, name: str, callback: Callable) -> None:
        try:
            log(f"io_thread_loop({name}, {callback}) loop starting")
            while not self._closed and callback():
                "wait for an exit condition"
            log(f"io_thread_loop({name}, {callback}) loop ended, closed={self._closed}")
        except ConnectionClosedException:
            log(f"{self._conn} closed", exc_info=True)
            if not self._closed:
                # ConnectionClosedException means the warning has been logged already
                self._connection_lost(f"{name} connection {self._conn} closed")
        except (OSError, socket_error) as e:
            if not self._closed:
                self._internal_error(f"{name} connection {self._conn} reset", e, exc_info=e.args[0] not in ABORT)
        except Exception as e:
            # can happen during close(), in which case we just ignore:
            if not self._closed:
                log.error(f"Error: {name} on {self._conn} failed: {type(e)}", exc_info=True)
                self.close()

    def _write_thread_loop(self) -> None:
        self._io_thread_loop("write", self._write)

    def _write(self) -> bool:
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

    def _read_thread_loop(self) -> None:
        self._io_thread_loop("read", self._read)

    def _read(self) -> bool:
        c = self._conn
        if not c:
            return False
        buf = c.read(READ_BUFFER_SIZE)
        # log("read()=%i bytes (%s)", len(buf or b""), type(buf))
        if not buf:
            log("read thread: eof")
            # give time to the parse thread to call close itself,
            # so it has time to parse and process the last packet received
            GLib.timeout_add(1000, self.close)
            return False
        if self.log:
            self.log.write(f"receive: {hexstr(buf)}\n")
        self.input_raw_packetcount += 1
        self._buffer += buf
        # log("calling %s(%s)", self._packet_parser, repr_ellipsized(self._buffer))
        while self._buffer:
            consumed = self._packet_parser(self._buffer)
            if consumed == 0:
                break
            self._buffer = self._buffer[consumed:]
        return True

    def _internal_error(self, message="", exc=None, exc_info=False) -> None:
        # log exception info with last log message
        if self._closed:
            return
        ei = exc_info
        if exc:
            ei = None  # log it separately below
        log.error(f"Error: {message}", exc_info=ei)
        if exc:
            log.error(f" {exc}", exc_info=exc_info)
        GLib.idle_add(self._connection_lost, message)

    def _connection_lost(self, message="", exc_info=False) -> bool:
        log(f"connection lost: {message}", exc_info=exc_info)
        self.close()
        return False

    def invalid(self, msg, data) -> None:
        log("invalid(%s, %r)", msg, data)
        self._packet_parser = self._parse_invalid
        GLib.idle_add(self._process_packet_cb, self, Packet(INVALID, msg, data))
        # Then hang up:
        GLib.timeout_add(1000, self._connection_lost, msg)

    # delegates to invalid_header()
    def invalid_header(self, proto, data, msg="") -> None:
        log("invalid_header%s", (proto, data, msg))
        self._invalid_header(proto, data, msg)

    def _invalid_header(self, _proto, data, msg="invalid packet header") -> None:
        self._packet_parser = self._parse_invalid
        err = f"{msg}: {hexstr(data[:8])!r}"
        if len(data) > 1:
            err += f" read buffer={repr_ellipsized(data)} ({len(data)} bytes)"
        self.invalid(err, data)

    def gibberish(self, msg, data) -> None:
        log(f"gibberish({msg}, {data!r})")
        self.close()

    def close(self) -> None:
        c = self._conn
        log(f"RFBProtocol.close() closed={self._closed}, connection={self._conn}")
        if self._closed:
            return
        self._closed = True
        # GLib.idle_add(self._process_packet_cb, self, [CONNECTION_LOST])
        if c:
            try:
                log(f"RFBProtocol.close() calling {c.close}")
                c.close()
            except OSError:
                log.error(f"Error closing {c}", exc_info=True)
            self._conn = None
        self.terminate_queue_threads()
        self._process_packet_cb(self, Packet(CONNECTION_LOST))
        GLib.idle_add(self.clean)
        log_file = self.log
        if log_file:
            self.log = None
            log_file.close()
        log("RFBProtocol.close() done")

    def clean(self) -> None:
        # clear all references to ensure we can get garbage collected quickly:
        self._write_thread = None
        self._read_thread = None
        self._process_packet_cb = None

    def terminate_queue_threads(self) -> None:
        log("terminate_queue_threads()")
        # make all the queue based threads exit by adding the empty marker:
        owq = self._write_queue
        self._write_queue = exit_queue()
        force_flush_queue(owq)
