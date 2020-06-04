# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct

from xpra.net.websockets.header import encode_hybi_header, decode_hybi
from xpra.net.protocol import Protocol
from xpra.util import first_time, envbool
from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger

log = Logger("websocket")

OPCODE_CONTINUE = 0
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

#default to legacy mode until we parse the remote caps:
#(this can be removed in the future once all html5 clients have been updated)
LEGACY_FRAME_PER_CHUNK = envbool("XPRA_WEBSOCKET_LEGACY", None)
MASK = envbool("XPRA_WEBSOCKET_MASK", False)


class WebSocketProtocol(Protocol):

    STATE_FIELDS = tuple(list(Protocol.STATE_FIELDS)+["legacy_frame_per_chunk"])

    TYPE = "websocket"

    def __init__(self, *args, **kwargs):
        Protocol.__init__(self, *args, **kwargs)
        self.ws_data = b""
        self.ws_payload = []
        self.ws_payload_opcode = 0
        self.ws_mask = MASK
        self._process_read = self.parse_ws_frame
        self.legacy_frame_per_chunk = LEGACY_FRAME_PER_CHUNK in (None, True)
        if self.legacy_frame_per_chunk:
            self.make_chunk_header = self.make_wschunk_header
        else:
            self.make_chunk_header = self.make_xpra_header
            self.make_frame_header = self.make_wsframe_header

    def __repr__(self):
        return "WebSocket(%s)" % self._conn

    def close(self):
        Protocol.close(self)
        self.ws_data = b""
        self.ws_payload = []


    def get_info(self, alias_info=True):
        info = Protocol.get_info(self, alias_info)
        info["legacy-frames"] = self.legacy_frame_per_chunk
        return info


    def parse_remote_caps(self, caps):
        Protocol.parse_remote_caps(self, caps)
        if LEGACY_FRAME_PER_CHUNK is None:
            may_have_bug = caps.strget("client_type", "")=="HTML5"
            self.legacy_frame_per_chunk = not caps.boolget("websocket.multi-packet", not may_have_bug)
            log("parse_remote_caps() may_have_bug=%s, legacy_frame_per_chunk=%s",
                may_have_bug, self.legacy_frame_per_chunk)
        if self.legacy_frame_per_chunk:
            log.warn("Warning: using slower legacy websocket frames")
            log.warn(" the other end is probably out of date")
            #websocker header for every chunk:
            self.make_chunk_header = self.make_wschunk_header
            #no frame header:
            self.make_frame_header = self.noframe_header
        else:
            #just the regular xpra header for each chunk:
            self.make_chunk_header = self.make_xpra_header
            #and one websocket header for all the chunks:
            self.make_frame_header = self.make_wsframe_header

    def make_wschunk_header(self, packet_type, proto_flags, level, index, payload_size, total_size):
        header = Protocol.make_xpra_header(self, packet_type, proto_flags, level, index, payload_size, total_size)
        log("make_wschunk_header(%s)", (packet_type, proto_flags, level, index, payload_size))
        return encode_hybi_header(OPCODE_BINARY, total_size+len(header))+header

    def make_wsframe_header(self, packet_type, items):
        payload_len = sum(len(item) for item in items)
        log("make_wsframe_header(%s, %i items) %i bytes", packet_type, len(items), payload_len)
        header = encode_hybi_header(OPCODE_BINARY, payload_len, self.ws_mask)
        if self.ws_mask:
            from xpra.codecs.xor.cyxor import hybi_mask     #@UnresolvedImport
            mask = os.urandom(4)
            #now mask all the items:
            for i, item in enumerate(items):
                items[i] = hybi_mask(mask, item)
            return header+mask
        return header

    def parse_ws_frame(self, buf):
        if not buf:
            self._read_queue_put(buf)
            return
        if self.ws_data:
            ws_data = self.ws_data+buf
            self.ws_data = b""
        else:
            ws_data = buf
        log("parse_ws_frame(%i bytes) total buffer is %i bytes", len(buf), len(ws_data))
        while ws_data and not self._closed:
            parsed = decode_hybi(ws_data)
            if parsed is None:
                log("parse_ws_frame(%i bytes) not enough data", len(ws_data))
                #not enough data to get a full websocket frame,
                #save it for later:
                self.ws_data = ws_data
                return
            opcode, payload, processed, fin = parsed
            ws_data = ws_data[processed:]
            log("parse_ws_frame(%i bytes) payload=%i bytes, processed=%i, remaining=%i, opcode=%s, fin=%s",
                len(buf), len(payload), processed, len(ws_data), OPCODES.get(opcode, opcode), fin)
            if opcode==OPCODE_CONTINUE:
                assert self.ws_payload_opcode and self.ws_payload, "continuation frame does not follow a partial frame"
                self.ws_payload.append(payload)
                if not fin:
                    #wait for more
                    continue
                #join all the frames and process the payload:
                full_payload = b"".join(memoryview_to_bytes(v) for v in self.ws_payload)
                self.ws_payload = []
                opcode = self.ws_payload_opcode
                self.ws_payload_opcode = 0
            else:
                if self.ws_payload and self.ws_payload_opcode:
                    raise Exception("expected a continuation frame not %s" % OPCODES.get(opcode, opcode))
                full_payload = payload
                if not fin:
                    if opcode not in (OPCODE_BINARY, OPCODE_TEXT):
                        raise Exception("cannot handle fragmented '%s' frames" % OPCODES.get(opcode, opcode))
                    #fragmented, keep this payload for later
                    self.ws_payload_opcode = opcode
                    self.ws_payload.append(payload)
                    continue
            if opcode==OPCODE_BINARY:
                self._read_queue_put(full_payload)
            elif opcode==OPCODE_TEXT:
                if first_time("ws-text-frame-from-%s" % self._conn):
                    log.warn("Warning: handling text websocket frame as binary")
                self._read_queue_put(full_payload)
            elif opcode==OPCODE_CLOSE:
                self._process_ws_close(full_payload)
            elif opcode==OPCODE_PING:
                self._process_ws_ping(full_payload)
            elif opcode==OPCODE_PONG:
                self._process_ws_pong(full_payload)
            else:
                log.warn("Warning unhandled websocket opcode '%s'", OPCODES.get(opcode, "%#x" % opcode))
                log("payload=%r", payload)

    def _process_ws_ping(self, payload):
        log("_process_ws_ping(%r)", payload)
        item = encode_hybi_header(OPCODE_PONG, len(payload)) + memoryview_to_bytes(payload)
        items = (item, )
        with self._write_lock:
            self.raw_write("ws-ping", items)

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
