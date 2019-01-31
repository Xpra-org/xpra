# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from xpra.net.websocket import encode_hybi_header, decode_hybi_header
from xpra.net.protocol import Protocol
from xpra.util import first_time
from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger

log = Logger("websocket")

OPCODE_CONTINUE = 1
OPCODE_TEXT     = 1
OPCODE_BINARY   = 2
OPCODE_CLOSE    = 8
OPCODE_PING     = 9
OPCODE_PONG     = 10
OPCODES = {
    OPCODE_CONTINUE : "continuation frame",
    OPCODE_TEXT     : "text frame",
    OPCODE_BINARY   : "binary frame",
    OPCODE_CLOSE    : "connection close",
    OPCODE_PING     : "ping",
    OPCODE_PONG     : "pong",
    }


class WebSocketProtocol(Protocol):

    def __init__(self, *args):
        Protocol.__init__(self, *args)
        self.ws_data = b""
        self._process_read = self.parse_ws_frame

    def make_frame_header(self, packet_type, items):
        payload_len = sum(len(item) for item in items)
        log("make_frame_header(%s, %i items) %i bytes", packet_type, len(items), payload_len)
        return encode_hybi_header(OPCODE_BINARY, payload_len)

    def parse_ws_frame(self, buf):
        log("parse_ws_frame(%i bytes)", len(buf))
        self.ws_data += buf
        while self.ws_data:
            parsed = decode_hybi_header(self.ws_data)
            if parsed is None:
                log("parse_ws_header(%i bytes) not enough data", len(self.ws_data), parsed is not None)
                #not enough data to get a full websocket frame
                return
            opcode, payload, processed, fin = parsed
            log("parse_ws_header(%i bytes) payload=%i bytes, processed=%i, remaining=%i, opcode=%s, fin=%s", len(self.ws_data), len(payload), processed, len(self.ws_data), OPCODES.get(opcode, opcode), fin)
            self.ws_data = self.ws_data[processed:]
            if opcode==OPCODE_BINARY:
                self._read_queue_put(payload)
            elif opcode==OPCODE_TEXT:
                if first_time("ws-text-frame-from-%s" % self._conn):
                    log.warn("Warning: handling text websocket frame as binary")
                self._read_queue_put(payload)
            elif opcode==OPCODE_CLOSE:
                self._process_ws_close(payload)
            elif opcode==OPCODE_PING:
                self._process_ws_ping(payload)
            elif opcode==OPCODE_PONG:
                self._process_ws_pong(payload)
            else:
                log.warn("Warning unhandled websocket opcode '%s'", OPCODES.get(opcode, "%#x" % opcode))
                log("payload=%r", payload)

    def _process_ws_ping(self, payload):
        log("_process_ws_ping(%r)", payload)
        item = encode_hybi_header(OPCODE_PONG, len(payload)) + payload
        items = (item, )
        with self._write_lock:
            self.raw_write(items)

    def _process_ws_pong(self, payload):
        log("_process_ws_pong(%r)", payload)

    def _process_ws_close(self, payload):
        log("_process_ws_close(%r)", payload)
        if len(payload)<2:
            self._connection_lost("unknown reason")
            return
        code = struct.unpack(">H", payload[:2])[0]
        try:
            reason = memoryview_to_bytes(payload[2:]).decode("utf8")
        except UnicodeDecodeError:
            reason = str(reason)
        self._connection_lost("code %i: %s" % (code, reason))
