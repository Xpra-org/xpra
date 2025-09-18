# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from collections.abc import Callable

from xpra.common import SizedBuffer
from xpra.net.websockets.mask import hybi_mask
from xpra.net.websockets.header import encode_hybi_header, decode_hybi, close_packet
from xpra.net.websockets.common import OPCODE, OPCODE_STR
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.util.env import envbool, first_time
from xpra.util.str_fn import hexstr, memoryview_to_bytes, Ellipsizer
from xpra.log import Logger

log = Logger("websocket")
eventlog = Logger("websocket", "events")

MASK = envbool("XPRA_WEBSOCKET_MASK", False)


class WebSocketProtocol(SocketProtocol):
    TYPE = "websocket"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws_data: bytes = b""
        self.ws_payload: list[SizedBuffer] = []
        self.ws_payload_opcode: int = 0
        self.ws_mask: bool = MASK
        self._process_read = self.parse_ws_frame
        self.make_chunk_header: Callable = self.make_xpra_header
        self.make_frame_header: Callable = self.make_wsframe_header

    def __repr__(self):
        return f"WebSocket({self._conn})"

    def close(self, message="closing") -> None:
        eventlog("close(%s) closed=%s", message, self._closed)
        if self._closed:
            return
        self.send_ws_close(reason=message)
        super().close(message)
        self.ws_data = b""
        self.ws_payload = []

    def send_ws_close(self, code: int = 1000, reason: str = "closing") -> None:
        data = close_packet(code, reason)
        eventlog(f"send_ws_close({code}, {reason}) {data=!r}")
        self.flush_then_close(None, data)

    def make_wsframe_header(self, packet_type: str, items: list[SizedBuffer]) -> bytes:
        payload_len = sum(len(item) for item in items)
        header = encode_hybi_header(OPCODE.BINARY, payload_len, self.ws_mask)
        log("make_wsframe_header(%s, %i items) %i bytes, ws_mask=%s, header=0x%s (%i bytes)",
            packet_type, len(items), payload_len, self.ws_mask, hexstr(header), len(header))
        if self.ws_mask:
            mask = os.urandom(4)
            # now mask all the items:
            for i, item in enumerate(items):
                items[i] = hybi_mask(mask, item)
            return header + mask
        return header

    def parse_ws_frame(self, buf: SizedBuffer) -> None:
        if self.ws_data:
            ws_data = b"".join((self.ws_data, buf))
            self.ws_data = b""
        else:
            ws_data = buf
        while self.input_packetcount == 0 and ws_data.startswith(b"\r\n"):
            ws_data = ws_data[2:]
        log("parse_ws_frame(%i bytes) total buffer is %i bytes", len(buf), len(ws_data))
        while ws_data and not self._closed:
            parsed = decode_hybi(ws_data)
            if parsed is None:
                log("parse_ws_frame(%i bytes) not enough data: %r", len(ws_data), Ellipsizer(ws_data))
                # not enough data to get a full websocket frame,
                # save it for later:
                self.ws_data = ws_data
                return
            opcode, payload, processed, fin = parsed
            ws_data = ws_data[processed:]
            log("parse_ws_frame(%i bytes) payload=%i bytes, processed=%i, remaining=%i, opcode=%s, fin=%s",
                len(buf), len(payload), processed, len(ws_data), OPCODE_STR.get(opcode, opcode), fin)
            if opcode == OPCODE.CONTINUE:
                assert self.ws_payload_opcode and self.ws_payload, "continuation frame does not follow a partial frame"
                self.ws_payload.append(payload)
                if not fin:
                    # wait for more
                    continue
                # join all the frames and process the payload:
                full_payload = b"".join(memoryview_to_bytes(v) for v in self.ws_payload)
                self.ws_payload = []
                opcode = self.ws_payload_opcode
                self.ws_payload_opcode = 0
            else:
                if self.ws_payload and self.ws_payload_opcode:
                    op = OPCODE_STR.get(opcode, opcode)
                    raise ValueError(f"expected a continuation frame not {op}")
                full_payload = payload
                if not fin:
                    if opcode not in (OPCODE.BINARY, OPCODE.TEXT):
                        op = OPCODE_STR.get(opcode, opcode)
                        log(f"invalid opcode {opcode} from {buf!r}")
                        log(f"parsed as {parsed}")
                        raise RuntimeError(f"cannot handle fragmented {op} frames")
                    # fragmented, keep this payload for later
                    self.ws_payload_opcode = opcode
                    self.ws_payload.append(payload)
                    continue
            if opcode == OPCODE.BINARY:
                if not full_payload:
                    log.warn("Warning: empty websocket binary payload")
                    continue
                self._read_queue_put(full_payload)
            elif opcode == OPCODE.TEXT:
                if first_time(f"ws-text-frame-from-{self._conn}"):
                    log.warn("Warning: handling text websocket frame as binary")
                self._read_queue_put(full_payload)
            elif opcode == OPCODE.CLOSE:
                self._process_ws_close(full_payload)
            elif opcode == OPCODE.PING:
                self._process_ws_ping(full_payload)
            elif opcode == OPCODE.PONG:
                self._process_ws_pong(full_payload)
            else:
                log.warn("Warning unhandled websocket opcode '%s'", OPCODE_STR.get(opcode, f"{opcode:x}"))
                log("payload=%r", payload)

    def _process_ws_ping(self, payload: SizedBuffer) -> None:
        log("_process_ws_ping(%r)", payload)
        item = encode_hybi_header(OPCODE.PONG, len(payload)) + memoryview_to_bytes(payload)
        items = (item,)
        with self._write_lock:
            self.raw_write("ws-ping", items)

    @staticmethod
    def _process_ws_pong(payload: SizedBuffer) -> None:
        log("_process_ws_pong(%r)", payload)

    def _process_ws_close(self, payload: SizedBuffer) -> None:
        eventlog("_process_ws_close(%r)", payload)
        if len(payload) < 2:
            self._connection_lost("unknown reason")
            return
        code = struct.unpack(">H", payload[:2])[0]
        try:
            reason = memoryview_to_bytes(payload[2:]).decode("utf8")
        except UnicodeDecodeError:
            reason = str(payload[2:])
        self._connection_lost(f"code {code}: {reason}")
