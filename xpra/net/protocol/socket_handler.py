# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods, it's threads

# but it works on win32, for whatever that's worth.

import os
from enum import Enum, IntEnum
from time import monotonic
from socket import error as socket_error
from threading import Lock, RLock, Event, Thread, current_thread
from queue import Queue, SimpleQueue, Empty, Full
from typing import Any
from collections.abc import Callable, Iterable, Sequence, Mapping

from xpra.util.objects import typedict
from xpra.util.str_fn import (
    csv, hexstr, nicestr,
    Ellipsizer, repr_ellipsized, strtobytes, memoryview_to_bytes,
)
from xpra.util.env import envint, envbool, first_time
from xpra.util.thread import make_thread, start_thread
from xpra.common import noop, SizedBuffer
from xpra.scripts.config import TRUE_OPTIONS
from xpra.net.bytestreams import SOCKET_TIMEOUT, set_socket_timeout
from xpra.net.protocol.header import (
    unpack_header, pack_header, find_xpra_header,
    FLAGS_CIPHER, FLAGS_NOHEADER, FLAGS_FLUSH, HEADER_SIZE,
)
from xpra.net.protocol.constants import CONNECTION_LOST, INVALID, GIBBERISH
from xpra.net.common import (
    ConnectionClosedException, may_log_packet,
    MAX_PACKET_SIZE,
    PacketType, NetPacketType,
)
from xpra.net.bytestreams import ABORT
from xpra.net import compression
from xpra.net.compression import (
    decompress,
    InvalidCompressionException, Compressed, LevelCompressed, Compressible, LargeStructure,
)
from xpra.net import packet_encoding
from xpra.net.socket_util import guess_packet_type
from xpra.net.packet_encoding import decode, InvalidPacketEncodingException
from xpra.net.crypto import get_cipher, get_key, get_mode, pad, get_block_size, INITIAL_PADDING
from xpra.log import Logger

log = Logger("network", "protocol")
cryptolog = Logger("network", "crypto")
eventlog = Logger("network", "events")

USE_ALIASES = envbool("XPRA_USE_ALIASES", True)
READ_BUFFER_SIZE = envint("XPRA_READ_BUFFER_SIZE", 65536)
# merge header and packet if packet is smaller than:
PACKET_JOIN_SIZE = envint("XPRA_PACKET_JOIN_SIZE", READ_BUFFER_SIZE)
LARGE_PACKET_SIZE = envint("XPRA_LARGE_PACKET_SIZE", 16384)
LOG_RAW_PACKET_SIZE = envbool("XPRA_LOG_RAW_PACKET_SIZE", False)
# inline compressed data in packet if smaller than:
INLINE_SIZE = envint("XPRA_INLINE_SIZE", 32768)
FAKE_JITTER = envint("XPRA_FAKE_JITTER", 0)
MIN_COMPRESS_SIZE = envint("XPRA_MIN_COMPRESS_SIZE", 378)
SEND_INVALID_PACKET = envint("XPRA_SEND_INVALID_PACKET", 0)
SEND_INVALID_PACKET_DATA = strtobytes(os.environ.get("XPRA_SEND_INVALID_PACKET_DATA", b"ZZinvalid-packetZZ"))
ALIAS_INFO = envbool("XPRA_ALIAS_INFO", False)

PACKET_HEADER_CHAR = ord("P")


def exit_queue() -> SimpleQueue[tuple[Sequence, str, bool, bool] | None]:
    queue: SimpleQueue[tuple[Sequence, str, bool, bool] | None] = SimpleQueue()
    for _ in range(10):  # just 2 should be enough!
        queue.put(None)
    return queue


def force_flush_queue(q: Queue) -> None:
    # discard all elements in the old queue and push the None marker:
    try:
        while q.qsize() > 0:
            q.get(False)
    except Empty:
        log("force_flush_queue(%s)", q, exc_info=True)
    try:
        q.put_nowait(None)
    except Full:
        log("force_flush_queue(%s)", q, exc_info=True)


def no_packet() -> [PacketType, bool, bool]:
    return ("closed", ), False, False


class SocketProtocol:
    """
        This class handles sending and receiving packets,
        it will encode and compress them before sending,
        and decompress and decode when receiving.
    """

    TYPE = "xpra"

    def __init__(self, conn,
                 process_packet_cb: Callable[[Any, PacketType], None],
                 get_packet_cb: Callable[[], tuple[PacketType, bool, bool]] = no_packet,
                 scheduler=None):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        if not conn:
            raise ValueError(f"missing connection: {conn}")
        for fn in ("read", "write", "close", "peek"):
            if not hasattr(conn, fn):
                raise ValueError(f"{conn} doesn't look like a connection object: no {fn!r}")
            if not callable(getattr(conn, fn)):
                raise ValueError(f"{fn!r} is not callable")
        if scheduler is None:
            log(f"using {scheduler=}")
            from xpra.os_util import gi_import
            GLib = gi_import("GLib")
            scheduler = GLib
        self.idle_add = scheduler.idle_add
        self.timeout_add = scheduler.timeout_add
        # self.source_remove = scheduler.source_remove

        self.start_time = monotonic()
        self.read_buffer_size: int = READ_BUFFER_SIZE
        self.hangup_delay: int = 1000
        self._conn = conn
        self._process_packet_cb: Callable[[Any, PacketType], None] = process_packet_cb
        self.make_chunk_header: Callable[[str | int, int, int, int, int], bytes] = self.make_xpra_header
        self.make_frame_header: Callable[[str | int, list[SizedBuffer]], SizedBuffer] = self.noframe_header
        self._write_queue: Queue[tuple[Sequence, str, bool, bool] | None] = Queue(1)
        self._read_queue: Queue[SizedBuffer] = Queue(20)
        self._pre_read = []
        self._process_read: Callable[[SizedBuffer], None] = self.read_queue_put
        self._read_queue_put: Callable[[SizedBuffer], None] = self.read_queue_put
        self._get_packet_cb: Callable[[], tuple[PacketType, bool, bool]] = get_packet_cb
        # counters:
        self.input_stats: dict[str, int] = {}
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_stats: dict[str, int] = {}
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        # initial value which may get increased by client/server after handshake:
        self.max_packet_size = MAX_PACKET_SIZE
        self.abs_max_packet_size = 256 * 1024 * 1024
        self.large_packets = [
            "hello", "window-metadata", "sound-data", "notify_show", "setting-change",
            "shell-reply", "configure-display",
            "encodings",
        ]
        self._log_stats = None  # None here means auto-detect
        if "XPRA_LOG_SOCKET_STATS" in os.environ:
            self._log_stats = envbool("XPRA_LOG_SOCKET_STATS")
        self._closed = False
        self.encoder = "none"
        self._encoder = packet_encoding.get_encoder("none")
        self.compressor = "none"
        self._compress = compression.get_compressor("none")
        self.compression_level = 0
        self.chunks = True
        self.authenticators = ()
        self.encryption = ""
        self.keyfile = ""
        self.keydata = b""
        self.cipher_in = None
        self.cipher_in_name = ""
        self.cipher_in_block_size = 0
        self.cipher_in_padding = INITIAL_PADDING
        self.cipher_in_always_pad = False
        self.cipher_in_stream = True
        self.cipher_in_key = b""
        self.cipher_in_decryptor = None
        self.cipher_out = None
        self.cipher_out_name = ""
        self.cipher_out_block_size = 0
        self.cipher_out_padding = INITIAL_PADDING
        self.cipher_out_always_pad = False
        self.cipher_out_stream = True
        self.cipher_out_key = b""
        self.cipher_out_encryptor = None
        self._threading_lock = RLock()
        self._write_lock = Lock()
        self._write_thread: Thread | None = None
        self._read_thread: Thread | None = make_thread(self._read_thread_loop, "read", daemon=True)
        self._read_parser_thread: Thread | None = None  # started when needed
        self._write_format_thread: Thread | None = None  # started when needed
        self._source_has_more = Event()
        self.receive_pending = False
        self.eof_pending = False
        # ssh channel may contain garbage initially,
        # tell the protocol to wait for a valid header:
        self.wait_for_header = conn.socktype == "ssh"
        self.source_has_more = self.source_has_more_start
        self.flush_then_close = self.do_flush_then_close

    STATE_FIELDS: Sequence[str] = (
        "max_packet_size", "large_packets",
        "cipher_in", "cipher_in_name", "cipher_in_block_size", "cipher_in_padding",
        "cipher_in_always_pad", "cipher_in_stream", "cipher_in_key",
        "cipher_out", "cipher_out_name", "cipher_out_block_size", "cipher_out_padding",
        "cipher_out_always_pad", "cipher_out_stream", "cipher_out_key",
        "compression_level", "chunks", "encoder", "compressor",
    )

    def save_state(self) -> dict[str, Any]:
        state = {}
        for x in self.STATE_FIELDS:
            state[x] = getattr(self, x)
        return state

    def restore_state(self, state: dict[str, Any]) -> None:
        assert state is not None
        for x in self.STATE_FIELDS:
            assert x in state, f"field {x!r} is missing"
            setattr(self, x, state[x])
        # special handling for compressor / encoder which are named objects:
        self.enable_compressor(self.compressor)
        self.enable_encoder(self.encoder)

    def is_closed(self) -> bool:
        return self._closed

    def is_sending_encrypted(self) -> bool:
        options = getattr(self._conn, "options", {})
        trusted = options.get("trusted")
        if trusted:
            return trusted.lower() in TRUE_OPTIONS
        http_headers = options.get("http-headers", {})
        if http_headers and isinstance(http_headers, dict):
            forwarded_proto = http_headers.get("X-Forwarded-Proto", "")
            trust_proxy_headers = options.get("trust-proxy-headers", "no")
            log(f"is_sending_encrypted() trust-proxy-headers={trust_proxy_headers}, http-headers={http_headers}")
            if forwarded_proto and trust_proxy_headers.lower() in TRUE_OPTIONS:
                return forwarded_proto == "https"
        return bool(self.cipher_out_name) or self._conn.socktype in ("ssl", "wss", "ssh", "quic")

    def wait_for_io_threads_exit(self, timeout=None) -> bool:
        io_threads = (self._read_thread, self._write_thread, self._read_parser_thread, self._read_parser_thread)
        current = current_thread()
        for t in io_threads:
            if t and t != current and t.is_alive():
                t.join(timeout)
        exited = True
        cinfo = self._conn or "cleared connection"
        for t in io_threads:
            if t and t != current and t.is_alive():
                log.warn("Warning: %s thread of %s is still alive (timeout=%s)", t.name, cinfo, timeout)
                exited = False
        return exited

    def set_packet_source(self, get_packet_cb: Callable[[], [PacketType, bool, bool]]) -> None:
        self._get_packet_cb = get_packet_cb

    def set_cipher_in(self, ciphername: str, iv: bytes, key_data: bytes, key_salt: bytes, key_hash: str, key_size: int,
                      iterations: int, padding: str, always_pad: bool, stream: bool) -> None:
        cryptolog("set_cipher_in%s", (ciphername, iv,
                                      hexstr(key_data), hexstr(key_salt), key_hash, key_size,
                                      iterations, padding, always_pad))
        mode = get_mode(ciphername)
        self.cipher_in_block_size = get_block_size(mode)
        self.cipher_in_padding = padding
        self.cipher_in_always_pad = always_pad
        self.cipher_in_stream = stream
        self.cipher_in_key = get_key(key_data, key_salt, key_hash, key_size, iterations)
        if stream:
            self.cipher_in_decryptor = get_cipher(self.cipher_in_key, iv, mode).decryptor()
        if self.cipher_in_name != ciphername:
            cryptolog.info(f"receiving data using {ciphername!r} %sencryption", "stream " if stream else "")
            self.cipher_in_name = ciphername

    def set_cipher_out(self, ciphername: str, iv: bytes, key_data: bytes, key_salt: bytes, key_hash: str, key_size: int,
                       iterations: int, padding: str, always_pad: bool, stream: bool) -> None:
        cryptolog("set_cipher_out%s", (ciphername, iv,
                                       hexstr(key_data), hexstr(key_salt), key_hash, key_size,
                                       iterations, padding, always_pad))
        mode = get_mode(ciphername)
        self.cipher_out_block_size = get_block_size(mode)
        self.cipher_out_padding = padding
        self.cipher_out_always_pad = always_pad
        self.cipher_out_stream = stream
        self.cipher_out_key = get_key(key_data, key_salt, key_hash, key_size, iterations)
        if stream:
            self.cipher_out_encryptor = get_cipher(self.cipher_out_key, iv, mode).encryptor()
        if self.cipher_out_name != ciphername:
            cryptolog.info(f"sending data using {ciphername!r} %sencryption", "stream " if stream else "")
            self.cipher_out_name = ciphername

    def decrypt(self, encrypted: SizedBuffer, padding_size: int) -> SizedBuffer:
        cryptolog("received %6i %s encrypted bytes with %i bytes of padding",
                  len(encrypted), self.cipher_in_name, padding_size)
        mode = get_mode(self.cipher_in_name)
        info_options = {
            "always-pad": self.cipher_in_always_pad,
            "stream": self.cipher_in_stream,
            "block-size": self.cipher_in_block_size,
            "mode": mode,
        }

        if self.cipher_in_stream:
            assert self.cipher_in_decryptor
            data = self.cipher_in_decryptor.update(encrypted)
        else:
            iv = encrypted[:16]
            decryptor = get_cipher(self.cipher_in_key, iv, mode).decryptor()
            data = decryptor.update(encrypted[16:]) + decryptor.finalize()
            info_options["iv"] = iv

        # remove the padding:
        if not padding_size:
            return data

        # pad byte value is number of padding bytes added
        padtext = pad(self.cipher_in_padding, padding_size)
        if data.endswith(padtext):
            cryptolog("removing %i bytes of %s padding", padding_size, self.cipher_in_name)
            return data[:-padding_size]

        def debug_str(s) -> str:
            try:
                return repr_ellipsized(hexstr(s))
            except (TypeError, ValueError):
                return repr_ellipsized(csv(tuple(s)))

        actual_padding = data[-padding_size:]
        cryptolog.warn("Warning: %s decryption failed: invalid padding", self.cipher_in_name)
        cryptolog(" cipher block size=%i", self.cipher_in_block_size)
        cryptolog(" data does not end with %i %s padding bytes %s (%s)",
                  padding_size, self.cipher_in_padding, debug_str(padtext), type(padtext))
        cryptolog(" but with %i bytes: %s (%s)",
                  len(actual_padding), debug_str(actual_padding), type(data))
        cryptolog(" encrypted data (%i bytes): %r..", len(encrypted), memoryview_to_bytes(encrypted[:128]))
        cryptolog(" encrypted data (hex): %s..", debug_str(encrypted))
        cryptolog(" decrypted data (%i bytes): %r..", len(data), data[:128])
        cryptolog(" decrypted data (hex): %s..", debug_str(data))
        cryptolog(" options: %s", info_options)
        self._internal_error(f"{self.cipher_in_name} encryption padding error - wrong key?")
        return b""

    def encrypt(self, data) -> tuple[bytes, int]:
        # add padding:
        payload_size = len(data)
        if self.cipher_out_block_size == 0:
            padding_size = 0
        else:
            padding_size = self.cipher_out_block_size - (payload_size % self.cipher_out_block_size)
            if self.cipher_out_always_pad and padding_size == 0:
                padding_size = self.cipher_out_block_size
        if padding_size == 0:
            padded = data
        else:
            # pad byte value is number of padding bytes added
            padded = memoryview_to_bytes(data) + pad(self.cipher_out_padding, padding_size)

        # create cipher if needed:
        assert self.cipher_out_name
        if self.cipher_out_stream:
            assert self.cipher_out_encryptor
            payload = self.cipher_out_encryptor.update(padded)
            iv_size = 0
        else:
            iv = os.urandom(16)
            iv_size = len(iv)
            payload_size += iv_size
            mode = get_mode(self.cipher_out_name)
            encryptor = get_cipher(self.cipher_out_key, iv, mode).encryptor()
            encrypted = encryptor.update(padded)
            extra = encryptor.finalize()
            payload = iv + encrypted + extra
        cryptolog("sending %6s bytes %s encrypted with %2s bytes of padding, %2s bytes of iv",
                  len(payload), self.cipher_out_name, padding_size, iv_size)
        # cryptolog("encrypted(%s)=%s", repr_ellipsized(hexstr(padded)), repr_ellipsized(hexstr(payload)))
        return payload, payload_size

    def __repr__(self):
        return f"Protocol({self._conn})"

    def get_threads(self) -> Sequence[Thread]:
        return tuple(x for x in (
            self._write_thread,
            self._read_thread,
            self._read_parser_thread,
            self._write_format_thread,
        ) if x is not None)

    def parse_remote_caps(self, caps: typedict) -> None:
        set_socket_timeout(self._conn, SOCKET_TIMEOUT)

    def get_info(self, alias_info: bool = ALIAS_INFO) -> dict[str, Any]:
        shm = self._source_has_more
        info = {
            "large_packets": self.large_packets,
            "compression_level": self.compression_level,
            "chunks": self.chunks,
            "max_packet_size": self.max_packet_size,
            "has_more": shm and shm.is_set(),
            "receive-pending": self.receive_pending,
            "closed": self._closed,
            "eof-pending": self.eof_pending,
        }
        comp = self.compressor
        if comp:
            info["compressor"] = comp
        encoder = self.encoder
        if encoder:
            info["encoder"] = encoder
        conn = self._conn
        if conn:
            with log.trap_error("Error collecting connection information on %s", conn):
                info.update(conn.get_info())
        # add stats to connection info:
        info["input"] = {
            "buffer-size": self.read_buffer_size,
            "hangup-delay": self.hangup_delay,
            "packetcount": self.input_packetcount,
            "raw_packetcount": self.input_raw_packetcount,
            "count": self.input_stats,
            "cipher": {
                "": self.cipher_in_name,
                "padding": self.cipher_in_padding,
            },
        }
        info["output"] = {
            "packet-join-size": PACKET_JOIN_SIZE,
            "large-packet-size": LARGE_PACKET_SIZE,
            "inline-size": INLINE_SIZE,
            "min-compress-size": MIN_COMPRESS_SIZE,
            "packetcount": self.output_packetcount,
            "raw_packetcount": self.output_raw_packetcount,
            "count": self.output_stats,
            "cipher": {
                "": self.cipher_out_name or "",
                "padding": self.cipher_out_padding
            },
        }
        thread_info: dict[str, bool] = {}
        for t in (self._write_thread, self._read_thread, self._read_parser_thread, self._write_format_thread):
            if t:
                thread_info[t.name] = t.is_alive()
        info["thread"] = thread_info
        return info

    def start(self) -> None:
        def start_network_read_thread() -> None:
            eventlog(f"start_network_read_thread() closed={self._closed}")
            if not self._closed:
                self._read_thread.start()

        self.idle_add(start_network_read_thread)
        if SEND_INVALID_PACKET:
            self.timeout_add(SEND_INVALID_PACKET * 1000, self.raw_write, SEND_INVALID_PACKET_DATA)

    def send_disconnect(self, reasons, done_callback=noop) -> None:
        packet = ["disconnect"] + [nicestr(x) for x in reasons]
        eventlog("send_disconnect(%r, %r)", reasons, done_callback)
        self.flush_then_close(self.encode, packet, done_callback=done_callback)

    def send_now(self, packet: PacketType) -> None:
        if self._closed:
            log("send_now(%s ...) connection is closed already, not sending", packet[0])
            return
        log("send_now(%s ...)", packet[0])
        if self._get_packet_cb != no_packet:
            raise RuntimeError(f"cannot use send_now when a packet source exists! (set to {self._get_packet_cb})")
        tmp_queue = [packet]

        def packet_cb() -> tuple[PacketType, bool, bool]:
            self._get_packet_cb = no_packet
            if not tmp_queue:
                raise RuntimeError("packet callback used more than once!")
            qpacket = tmp_queue.pop()
            return qpacket, True, self._source_has_more.is_set()

        self._get_packet_cb = packet_cb
        self.source_has_more()

    def source_has_more_start(self) -> None:  # pylint: disable=method-hidden
        shm = self._source_has_more
        if not shm or self._closed:
            return
        # from now on, take the shortcut:
        self.source_has_more = shm.set
        shm.set()
        # start the format thread:
        if self._write_format_thread or self._closed:
            return
        with self._threading_lock:
            if self._write_format_thread or self._closed:
                return
            self._write_format_thread = start_thread(self.write_format_thread_loop, "format", daemon=True)

    def write_format_thread_loop(self) -> None:
        log("write_format_thread_loop starting")
        try:
            while not self._closed:
                self._source_has_more.wait()
                gpc = self._get_packet_cb
                if self._closed or not gpc:
                    return
                self.add_packet_to_queue(*gpc())
        except Exception as e:
            if self._closed:
                return
            self._internal_error("error in network packet write/format", e, exc_info=True)

    def add_packet_to_queue(self, packet: PacketType, synchronous=True, more=False) -> None:
        if not more:
            shm = self._source_has_more
            if shm:
                shm.clear()
        if not packet:
            return
        packet_type: str | int = packet[0]
        if packet_type in ("closed", "none"):
            return
        chunks: tuple[NetPacketType, ...] = tuple(self.encode(packet))
        with self._write_lock:
            if self._closed:
                return
            try:
                self._add_chunks_to_queue(packet_type, chunks, synchronous, more)
            except Exception:
                log.error("Error: failed to queue '%s' packet", packet[0])
                log("add_chunks_to_queue%s", (chunks, ), exc_info=True)
                raise

    def _add_chunks_to_queue(self, packet_type: str | int,
                             chunks: Iterable[NetPacketType],
                             synchronous=True, more=False) -> None:
        """ the write_lock must be held when calling this function """
        items = []
        for proto_flags, index, level, data in chunks:
            if not data:
                raise RuntimeError(f"missing data in chunk {index}")
            payload = data
            size = len(payload)
            if self.cipher_out_name:
                proto_flags |= FLAGS_CIPHER
                payload, size = self.encrypt(data)
            if proto_flags & FLAGS_NOHEADER:
                assert not self.cipher_out
                # for plain/text packets (ie: gibberish response)
                log("sending %s bytes without header", size)
                items.append(payload)
            else:
                # if the other end can use this flag, expose it:
                if index == 0 and not more:
                    proto_flags |= FLAGS_FLUSH
                # the xpra packet header:
                # (WebSocketProtocol may also add a websocket header too)
                header = self.make_chunk_header(packet_type, proto_flags, level, index, size)
                if size < PACKET_JOIN_SIZE:
                    if not isinstance(payload, bytes):
                        payload = memoryview_to_bytes(payload)
                    items.append(header + payload)
                else:
                    items.append(header)
                    items.append(payload)
        # WebSocket header may be added here:
        frame_header = self.make_frame_header(packet_type, items)  # pylint: disable=assignment-from-none
        if frame_header:
            item0 = items[0]
            if len(item0) < PACKET_JOIN_SIZE:
                if not isinstance(item0, bytes):
                    item0 = memoryview_to_bytes(item0)
                items[0] = frame_header + item0
            else:
                items.insert(0, frame_header)
        self.raw_write(items, packet_type, synchronous, more)

    @staticmethod
    def make_xpra_header(_packet_type: str | int,
                         proto_flags: int, level: int, index: int, payload_size: int) -> bytes:
        return pack_header(proto_flags, level, index, payload_size)

    @staticmethod
    def noframe_header(_packet_type: str | int, _items) -> bytes:
        return b""

    def start_write_thread(self) -> None:
        with self._threading_lock:
            assert not self._write_thread, "write thread already started"
            self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def raw_write(self, items: Sequence, packet_type="", synchronous=True, more=False) -> None:
        """ Warning: this bypasses the compression and packet encoder! """
        if self._write_thread is None:
            log("raw_write for %s, starting write thread", packet_type)
            self.start_write_thread()
        self._write_queue.put((items, packet_type, synchronous, more))

    def enable_default_encoder(self) -> None:
        opts = packet_encoding.get_enabled_encoders()
        assert opts, "no packet encoders available!"
        self.enable_encoder(opts[0])

    def enable_encoder_from_caps(self, caps: typedict) -> bool:
        options = packet_encoding.get_enabled_encoders(order=packet_encoding.PERFORMANCE_ORDER)
        log(f"enable_encoder_from_caps(..) options={options}")
        self.chunks = caps.boolget("chunks", True)
        for e in options:
            if caps.boolget(e):
                self.enable_encoder(e)
                return True
            log(f"client does not support {e}")
        log.error("no matching packet encoder found!")
        return False

    def enable_encoder(self, e: str) -> None:
        self._encoder = packet_encoding.get_encoder(e)
        self.encoder = e
        log(f"enable_encoder({e}): {self._encoder}")

    def enable_default_compressor(self) -> None:
        opts = compression.get_enabled_compressors()
        if opts:
            self.enable_compressor(opts[0])
        else:
            self.enable_compressor("none")

    def enable_compressor_from_caps(self, caps: typedict) -> None:
        if self.compression_level == 0:
            self.enable_compressor("none")
            return
        opts = compression.get_enabled_compressors(order=compression.PERFORMANCE_ORDER)
        compressors = caps.strtupleget("compressors")
        log(f"enable_compressor_from_caps(..) options={opts}, compressors from caps={compressors}")
        for c in opts:  # ie: ["lz4", "none"]
            if c == "none":
                continue
            if c in compressors or caps.boolget(c):
                self.enable_compressor(c)
                return
            log(f"client does not support {c}")
        if not compressors:
            log.info("peer does not support packet compression")
        else:
            log.info("compression disabled, no matching compressor found")
            log.info(f" peer capabilities: {csv(compressors)}")
            log.info(f" enabled compressors: {csv(opts)}")
        self.enable_compressor("none")

    def enable_compressor(self, compressor: str) -> None:
        self._compress = compression.get_compressor(compressor)
        self.compressor = compressor
        log(f"enable_compressor({compressor}): {self._compress}")

    def encode(self, packet_in: PacketType) -> list[NetPacketType]:
        """
        Given a packet (tuple or list of items), converts it for the wire.
        This method returns all the binary packets to send, as an array of:
        (index, compression_level and compression flags, binary_data)
        The index, if positive indicates the item to populate in the packet
        whose index is zero.
        ie: ["blah", [large binary data], "hello", 200]
        may get converted to:
        ```
        [
            (1, compression_level, [large binary data now lz4 compressed]),
            (0,                 0, rencoded(["blah", '', "hello", 200]))
        ]
        ```
        """
        packets: list[NetPacketType] = []
        packet = list(packet_in)
        level = self.compression_level
        size_check = LARGE_PACKET_SIZE
        min_comp_size = MIN_COMPRESS_SIZE
        packet_type = str(packet[0])
        log(f"encode({packet_type}, ...)")
        payload_size = 0
        for i in range(1, len(packet)):
            item = packet[i]
            if item is None:
                raise TypeError(f"invalid None value in {packet_type!r} packet at index {i}")
            if isinstance(item, IntEnum):
                if first_time(f"enum-{packet_type}-%s" % type(item)):
                    log.warn(f"Warning: found IntEnum value in {packet_type!r} packet at index {i}")
                packet[i] = int(item)
                continue
            if isinstance(item, (int, bool, Mapping, Sequence)):
                continue
            if isinstance(item, Enum):
                packet[i] = str(item)
                continue
            try:
                size = len(item)
            except TypeError as e:
                raise TypeError(f"invalid type {type(item)} in {packet_type!r} packet at index {i}: {e}") from None
            if isinstance(item, Compressible):
                # this is a marker used to tell us we should compress it now
                # (used by the client for clipboard data)
                item = item.compress()
                packet[i] = item
                # (it may now be a "Compressed" item and be processed further)
            if isinstance(item, memoryview):
                if self.encoder != "rencodeplus":
                    packet[i] = item.tobytes()
                continue
            if isinstance(item, LargeStructure):
                packet[i] = item.data
                continue
            if isinstance(item, Compressed):
                # already compressed data (usually pixels, cursors, etc)
                if self.chunks and (not item.can_inline or size > INLINE_SIZE):
                    il = 0
                    if isinstance(item, LevelCompressed):
                        # unlike `Compressed` (usually pixels, decompressed in the paint thread),
                        # `LevelCompressed` is decompressed by the network layer,
                        # so we must tell it how to do that and using the level flag:
                        il = item.level
                    packets.append((0, i, il, item.data))
                    packet[i] = b''
                    payload_size += len(item.data)
                else:
                    # data is small enough, inline it:
                    packet[i] = item.data
                    if isinstance(item.data, memoryview) and self.encoder != "rencodeplus":
                        packet[i] = item.data.tobytes()
                    min_comp_size += size
                    size_check += size
                continue
            if self.chunks and isinstance(item, bytes) and level > 0 and size > LARGE_PACKET_SIZE:
                log.warn("Warning: found a large uncompressed item")
                log.warn(f" in packet {packet_type!r} at position {i}: {len(item)} bytes")
                # add new binary packet with large item:
                cl, cdata = self._compress(item, level)
                packets.append((0, i, cl, cdata))
                payload_size += len(cdata)
                # replace this item with an empty string placeholder:
                packet[i] = ''
                continue
            if not isinstance(item, (str, bytes)):
                log.warn(f"Warning: unexpected data type {type(item)}")
                log.warn(f" in {packet_type!r} packet at position {i}: {repr_ellipsized(item)}")
        # now the main packet (or what is left of it):
        self.output_stats[packet_type] = self.output_stats.get(packet_type, 0) + 1
        try:
            main_packet, proto_flags = self._encoder(packet)
        except Exception:
            if self._closed:
                return []
            log.error(f"Error: failed to encode packet: {packet}", exc_info=True)
            from xpra.net.protocol.check import verify_packet
            verify_packet(packet)
            raise
        size = len(main_packet)
        if self.chunks and size > size_check and packet_in[0] not in self.large_packets:
            log.warn("Warning: found large packet")
            log.warn(f" {packet_type!r} packet is {len(main_packet)} bytes: ")
            log.warn(" argument types: %s", csv(type(x) for x in packet[1:]))
            log.warn(" sizes: %s", csv(len(strtobytes(x)) for x in packet[1:]))
            log.warn(f" packet: {repr_ellipsized(packet, limit=4096)}")
        # compress, but don't bother for small packets:
        if level > 0 and size > min_comp_size:
            try:
                cl, cdata = self._compress(main_packet, level)
                if LOG_RAW_PACKET_SIZE and packet_type != "logging":
                    log.info(f"         {packet_type!r:<32}: %i bytes compressed, from %i", len(cdata), size)
            except Exception as e:
                log.error(f"Error compressing {packet_type!r} packet")
                log.estr(e)
                raise
            payload_size += len(cdata)
            packets.append((proto_flags, 0, cl, cdata))
        else:
            payload_size += size
            packets.append((proto_flags, 0, 0, main_packet))
        may_log_packet(True, packet_type, packet)
        if LOG_RAW_PACKET_SIZE and packet_type != "logging":
            log.info(f"sending  {packet_type!r:<32}: %i bytes", HEADER_SIZE + payload_size)
        return packets

    def set_compression_level(self, level: int) -> None:
        # this may be used next time encode() is called
        if level < 0 or level > 10:
            raise ValueError(f"invalid compression level: {level} (must be between 0 and 10")
        self.compression_level = level

    def _io_thread_loop(self, name: str, callback: Callable) -> None:
        try:
            log(f"io_thread_loop({name}, {callback}) loop starting")
            while not self._closed and callback():
                "wait for an exit condition"
            log(f"io_thread_loop({name}, {callback}) loop ended, closed={self._closed}")
        except ConnectionClosedException as e:
            log(f"{self._conn} closed in {name} loop", exc_info=True)
            if not self._closed:
                # ConnectionClosedException means the warning has been logged already
                self._connection_lost(str(e))
        except (OSError, socket_error) as e:
            if not self._closed:
                self._internal_error(f"{name} connection {e} reset", exc_info=e.args[0] not in ABORT)
        except Exception as e:
            # can happen during close(), in which case we just ignore:
            if not self._closed:
                log.error(f"Error: {name} on {self._conn} failed: {type(e)}", exc_info=True)
                self.close()

    def flush_write_queue(self):
        while self._write_queue.qsize() and not self._closed:
            if not self._write():
                return

    def _write_thread_loop(self) -> None:
        self._io_thread_loop("write", self._write)

    def _write(self) -> bool:
        items = self._write_queue.get()
        # Used to signal that we should exit:
        if not items:
            log("write thread: empty marker, exiting")
            self.close()
            return False
        return self.write_items(*items)

    def write_items(self, buf_data, packet_type: str = "", synchronous: bool = True, more: bool = False):
        conn = self._conn
        if not conn:
            return False
        try:
            if more or len(buf_data) > 1:
                conn.set_nodelay(False)
            if len(buf_data) > 1:
                conn.set_cork(True)
        except OSError:
            log("write_items(..)", exc_info=True)
            if not self._closed:
                raise
        try:
            self.write_buffers(buf_data, packet_type, synchronous)
        except TypeError:
            log("%s%s", self.write_buffers, (buf_data, packet_type, synchronous), exc_info=True)
            log.error(f"Error writing {packet_type!r} packet to {conn!r}")
            log.error(" data=%s (%s)", Ellipsizer(buf_data), type(buf_data))
        try:
            if len(buf_data) > 1:
                conn.set_cork(False)
            if not more:
                conn.set_nodelay(True)
        except OSError:
            log("write_items(..)", exc_info=True)
            if not self._closed:
                raise
        return True

    def write_buffers(self, buf_data, packet_type: str, _synchronous: bool):
        con = self._conn
        if not con:
            return
        for buf in buf_data:
            while buf and not self._closed:
                written = self.con_write(con, buf, packet_type)
                # example test code, for sending small chunks very slowly:
                # written = con.write(buf[:1024])
                # import time
                # time.sleep(0.05)
                if written:
                    buf = buf[written:]
                    self.output_raw_packetcount += 1
        self.output_packetcount += 1

    # noinspection PyMethodMayBeStatic
    def con_write(self, con, buf: SizedBuffer, packet_type: str):
        return con.write(buf, packet_type)

    def _read_thread_loop(self) -> None:
        self._io_thread_loop("read", self._read)

    def _read(self) -> bool:
        buf = self.con_read()
        # log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
        # add to the read queue (or whatever takes its place - see steal_connection)
        if not buf:
            eventlog("read thread: potential eof")
            if not self.eof_pending:
                self.eof_pending = True
                self.timeout_add(1000, self.check_eof, self.input_raw_packetcount)
        else:
            self._process_read(buf)
            self.input_raw_packetcount += 1
        return True

    def check_eof(self, raw_count=0) -> bool:
        self.eof_pending = False
        if self.input_raw_packetcount <= raw_count:
            eventlog("check_eof: eof detected")
            # give time to the parse thread to call close itself,
            # so it has time to parse and process the last packet received
            self.timeout_add(1000, self.close)
            return False
        return False

    def con_read(self) -> SizedBuffer:
        if self._pre_read:
            r = self._pre_read.pop(0)
            log("con_read() using pre_read value: %r", Ellipsizer(r))
            return r
        return self._conn.read(self.read_buffer_size)

    def _internal_error(self, message="", exc=None, exc_info=False) -> None:
        eventlog("_internal_error(%r, %r, %r)", message, exc, exc_info)
        # log exception info with last log message
        if self._closed:
            return
        ei = exc_info
        if exc:
            ei = None  # log it separately below
        log.error(f"Error: {message}", exc_info=ei)
        if exc:
            log.error(f" {exc}", exc_info=exc_info)
        self.idle_add(self._connection_lost, message)

    def _connection_lost(self, message="", exc_info=False) -> bool:
        eventlog(f"connection lost: {message}", exc_info=exc_info)
        self.close(message)
        return False

    def invalid(self, msg: str, data: SizedBuffer) -> None:
        eventlog("invalid(%r, %r)", msg, data)
        self.idle_add(self._process_packet_cb, self, [INVALID, msg, data])
        # Then hang up:
        self.timeout_add(1000, self._connection_lost, msg)

    def gibberish(self, msg: str, data: SizedBuffer) -> None:
        eventlog("gibberish(%r, %r)", msg, data)
        self.idle_add(self._process_packet_cb, self, [GIBBERISH, msg, data])
        # Then hang up:
        self.timeout_add(self.hangup_delay, self._connection_lost, msg)

    # delegates to invalid_header()
    # (so this can more easily be intercepted and overridden)
    def invalid_header(self, proto, data: SizedBuffer, msg="invalid packet header") -> None:
        eventlog("invalid_header(%r, %r)", msg, data)
        self._invalid_header(proto, data, msg)

    def _invalid_header(self, proto, data: SizedBuffer, msg="invalid packet header") -> None:
        log("invalid_header(%s, %s bytes: '%s', %s)",
            proto, len(data or ""), msg, Ellipsizer(data))
        guess = guess_packet_type(data)
        if guess:
            err = f"{msg}: {guess}"
        else:
            err = "%s: 0x%s" % (msg, hexstr(data[:HEADER_SIZE]))
            if len(data) > 1:
                err += " read buffer=%s (%i bytes)" % (repr_ellipsized(data), len(data))
        self.gibberish(err, data)

    def process_read(self, data: SizedBuffer) -> None:
        self._read_queue_put(data)

    def read_queue_put(self, data: SizedBuffer) -> None:
        # start the parse thread if needed:
        if not self._read_parser_thread and not self._closed:
            if data is None:
                eventlog("empty marker in read queue, exiting")
                self.idle_add(self.close)
                return
            self.start_read_parser_thread()
        self._read_queue.put(data)
        # from now on, take shortcut:
        self._read_queue_put = self._read_queue.put

    def start_read_parser_thread(self) -> None:
        with self._threading_lock:
            assert not self._read_parser_thread, "read parser thread already started"
            self._read_parser_thread = start_thread(self._read_parse_thread_loop, "parse", daemon=True)

    def _read_parse_thread_loop(self) -> None:
        log("read_parse_thread_loop starting")
        try:
            self.do_read_parse_thread_loop()
        except Exception as e:
            if self._closed:
                return
            self._internal_error("error in network packet reading/parsing", e, exc_info=True)

    def do_read_parse_thread_loop(self):
        """
            Process the individual network packets placed in _read_queue.
            Concatenate the raw packet data, then try to parse it.
            Extract the individual packets from the potentially large buffer,
            saving the rest of the buffer for later, and optionally decompress this data
            and re-construct the one python-object-packet from potentially multiple packets (see packet_index).
            The 8 bytes packet header gives us information on the packet index, packet size and compression.
            The actual processing of the packet is done via the callback process_packet_cb,
            this will be called from this parsing thread so any calls that need to be made
            from the UI thread will need to use a callback (usually via 'idle_add')
        """
        header = b""
        read_buffers: list[SizedBuffer] = []
        payload_size = -1
        padding_size = 0
        packet_index = 0
        protocol_flags = 0
        data_size = 0
        compression_level = 0
        raw_packets: dict[int, SizedBuffer] = {}
        while not self._closed:
            # log("parse thread: %i items in read queue", self._read_queue.qsize())
            buf = self._read_queue.get()
            if not buf:
                eventlog("parse thread: empty marker, exiting")
                self.idle_add(self.close)
                return

            read_buffers.append(buf)
            if self.wait_for_header:
                # we're waiting to see the first xpra packet header
                # which may come after some random characters
                # (ie: when connecting over ssh, the channel may contain some unexpected output)
                # for this to work, we have to assume that the initial packet is smaller than 64KB:
                joined = b"".join(read_buffers)
                pos = find_xpra_header(joined)
                eventlog("waiting for xpra header: pos=%i", pos)
                if pos < 0:
                    # wait some more:
                    read_buffers = [joined]
                    continue
                # found it, so proceed:
                read_buffers = [joined[pos:]]
                self.wait_for_header = False

            while read_buffers:
                # have we read the header yet?
                if payload_size < 0:
                    # try to handle the first buffer:
                    buf = read_buffers[0]
                    if not header and buf[0] != PACKET_HEADER_CHAR:
                        self.invalid_header(self, buf, f"invalid packet header byte {hex(buf[0])}")
                        return
                    # how much to we need to slice off to complete the header:
                    read = min(len(buf), HEADER_SIZE - len(header))
                    header += memoryview_to_bytes(buf[:read])
                    if len(header) < HEADER_SIZE:
                        # need to process more buffers to get a full header:
                        read_buffers.pop(0)
                        continue
                    if len(buf) <= read:
                        # we only got the header:
                        assert len(buf) == read
                        read_buffers.pop(0)
                        continue
                    # got the full header and more, keep the rest of the packet:
                    read_buffers[0] = buf[read:]
                    # parse the header:
                    # format: struct.pack(b'cBBBL', ...) - HEADER_SIZE bytes
                    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(header)

                    # sanity check size (will often fail if not an xpra client):
                    if data_size > self.abs_max_packet_size:
                        self.invalid_header(self, header, f"invalid size in packet header: {data_size}")
                        return

                    if packet_index >= 16:
                        self.invalid_header(self, header, f"invalid packet index: {packet_index}")
                        return

                    if protocol_flags & FLAGS_CIPHER:
                        if not self.cipher_in_name:
                            cryptolog.warn("Warning: received cipher block,")
                            cryptolog.warn(" but we don't have a cipher to decrypt it with,")
                            cryptolog.warn(" not an xpra client?")
                            self.invalid_header(self, header, "invalid encryption packet flag (no cipher configured)")
                            return
                        if self.cipher_in_block_size == 0:
                            padding_size = 0
                        else:
                            padding_size = self.cipher_in_block_size - (data_size % self.cipher_in_block_size)
                            if self.cipher_in_always_pad and padding_size == 0:
                                padding_size = self.cipher_in_block_size
                        payload_size = data_size + padding_size
                    else:
                        # no cipher, no padding:
                        padding_size = 0
                        payload_size = data_size
                    if payload_size <= 0:
                        raise ValueError(f"invalid payload size {payload_size} for header {header!r}")

                    if payload_size > self.max_packet_size:
                        # this packet is seemingly too big, but check again from the main UI thread
                        # this gives 'set_max_packet_size' a chance to run from "hello"

                        def check_packet_size(size_to_check, packet_header):
                            if self._closed:
                                return False
                            eventlog("check_packet_size(%#x, %s) max=%#x",
                                     size_to_check, hexstr(packet_header), self.max_packet_size)
                            if size_to_check > self.max_packet_size:
                                # pylint: disable=line-too-long
                                err_msg = f"packet size requested is {size_to_check}"
                                err_msg += f" but maximum allowed is {self.max_packet_size}"
                                self.invalid(err_msg, packet_header)
                            return False

                        self.timeout_add(1000, check_packet_size, payload_size, header)

                # how much data do we have?
                bl = sum(len(v) for v in read_buffers)
                if bl < payload_size:
                    # incomplete packet, wait for the rest to arrive
                    break

                raw_data: SizedBuffer
                buf = read_buffers[0]
                if len(buf) == payload_size:
                    # exact match, consume it all:
                    raw_data = read_buffers.pop(0)
                elif len(buf) > payload_size:
                    # keep rest of packet for later:
                    read_buffers[0] = buf[payload_size:]
                    raw_data = buf[:payload_size]
                else:
                    # we need to aggregate chunks,
                    # just concatenate them all:
                    raw_data = b"".join(read_buffers)
                    if bl == payload_size:
                        # nothing left:
                        read_buffers = []
                    else:
                        # keep the left over:
                        read_buffers = [raw_data[payload_size:]]
                        raw_data = raw_data[:payload_size]

                data = raw_data
                # decrypt if needed:
                if self.cipher_in_name:
                    if not protocol_flags & FLAGS_CIPHER:
                        self.invalid("unencrypted packet dropped", data)
                        return
                    data = self.decrypt(raw_data, padding_size)
                    if not data:
                        return

                # uncompress if needed:
                if compression_level > 0:
                    try:
                        data = decompress(data, compression_level)
                    except InvalidCompressionException as e:
                        self.invalid(f"invalid compression: {e}", data)
                        return
                    except Exception as e:
                        ctype = compression.get_compression_type(compression_level)
                        msg = f"{ctype} packet decompression failed"
                        log(msg, exc_info=True)
                        if self.cipher_in:
                            msg += " (invalid encryption key?)"
                        else:
                            # only include the exception text when not using encryption
                            # as this may leak crypto information:
                            msg += f" {e}"
                        del e
                        self.gibberish(msg, data)
                        return

                if self._closed:
                    return

                # we're processing this packet,
                # make sure we get a new header next time
                header = b""
                if packet_index > 0:
                    if packet_index in raw_packets:
                        self.invalid(f"duplicate raw packet at index {packet_index}", data)
                        return
                    # raw packet, store it and continue:
                    raw_packets[packet_index] = data
                    payload_size = -1
                    if len(raw_packets) >= 4:
                        self.invalid(f"too many raw packets: {len(raw_packets)}", data)
                        return
                    # we know for sure that another packet should follow immediately
                    # the one with packet_index=0 for this raw packet
                    self.receive_pending = True
                    continue
                # final packet (packet_index==0), decode it:
                try:
                    packet = list(decode(data, protocol_flags))
                except InvalidPacketEncodingException as e:
                    self.invalid(f"invalid packet encoding: {e}", data)
                    return
                except (ValueError, TypeError, IndexError) as e:
                    etype = packet_encoding.get_packet_encoding_type(protocol_flags)
                    log.error(f"Error parsing {etype} packet:")
                    log.estr(e)
                    if self._closed:
                        return
                    eventlog(f"failed to parse {etype} packet: %s", hexstr(data[:128]), exc_info=True)
                    data_str = memoryview_to_bytes(data)
                    eventlog(" data: %s", repr_ellipsized(data_str))
                    eventlog(f" packet_index={packet_index}, payload_size={payload_size}, buffer size={bl}")
                    eventlog(" full data: %s", hexstr(data_str))
                    self.may_log_stats()
                    self.gibberish(f"failed to parse {etype} packet", data)
                    return

                if self._closed:
                    return
                payload_size = len(data)
                # add any raw packets back into it:
                if raw_packets:
                    for index, raw_data in raw_packets.items():
                        # replace placeholder with the raw_data packet data:
                        packet[index] = raw_data
                        payload_size += len(raw_data)
                    raw_packets = {}

                packet_type = str(packet[0])
                self.input_stats[packet_type] = self.output_stats.get(packet_type, 0) + 1
                if LOG_RAW_PACKET_SIZE and packet_type != "logging":
                    log.info(f"received {packet_type:<32}: %i bytes", HEADER_SIZE + payload_size)
                payload_size = -1
                self.input_packetcount += 1
                self.receive_pending = bool(protocol_flags & FLAGS_FLUSH)
                log("processing packet %s", packet_type)
                self._process_packet_cb(self, tuple(packet))
                del packet

    def do_flush_then_close(self, encoder: Callable | None = None,
                            last_packet=None,
                            done_callback: Callable = noop) -> None:  # pylint: disable=method-hidden
        """ Note: this is best-effort only
            the packet may not get sent.

            We try to get the write lock,
            we try to wait for the write queue to flush
            we queue our last packet,
            we wait again for the queue to flush,
            then no matter what, we close the connection and stop the threads.
        """

        def closing_already(packet_encoder: Callable | None = None,
                            packet_data=None,
                            done_callback: Callable = noop) -> None:
            eventlog("flush_then_close%s had already been called, this new request has been ignored",
                     (packet_encoder, packet_data, done_callback))

        self.flush_then_close = closing_already
        eventlog("flush_then_close%s closed=%s", (encoder, last_packet, done_callback), self._closed)
        if self._closed:
            eventlog("flush_then_close: already closed")
            done_callback()
            return

        def writelockrelease() -> None:
            wl = self._write_lock
            try:
                if wl:
                    wl.release()
            except Exception as e:
                eventlog(f"error releasing the write lock: {e}")

        def close_and_release() -> None:
            eventlog("close_and_release()")
            self.close()
            writelockrelease()
            done_callback()

        def wait_for_queue(timeout: int = 10) -> None:
            # IMPORTANT: if we are here, we have the write lock held!
            if not self._write_queue.empty():
                # write queue still has stuff in it..
                if timeout <= 0:
                    eventlog("flush_then_close: queue still busy, closing without sending the last packet")
                    close_and_release()
                    return
                # retry later:
                eventlog("flush_then_close: still waiting for queue to flush")
                self.timeout_add(100, wait_for_queue, timeout - 1)
                return
            if not last_packet:
                close_and_release()
                return

            def wait_for_packet_sent():
                closed = self._closed
                eventlog("flush_then_close: wait_for_packet_sent() queue.empty()=%s, closed=%s",
                         self._write_queue.empty(), closed)
                if self._write_queue.empty() or closed:
                    # it got sent, we're done!
                    close_and_release()
                    return False
                return not closed  # run until we manage to close (here or via the timeout)

            eventlog(f"flush_then_close: queue is now empty, sending the last packet using {encoder=} and closing")
            if encoder:
                eventlog("last packet: %s", last_packet)
                chunks = encoder(last_packet)
                eventlog("last packet has %i chunks", len(chunks))
                self._add_chunks_to_queue(last_packet[0], chunks, synchronous=False, more=False)
            else:
                self.raw_write((last_packet,), "flush-then-close")
            eventlog("flush_then_close: last packet queued, closed=%s", self._closed)
            if wait_for_packet_sent():
                # check again every 100ms
                self.timeout_add(100, wait_for_packet_sent)
            # just in case wait_for_packet_sent never fires:
            self.timeout_add(5 * 1000, close_and_release)

        def wait_for_write_lock(timeout: int = 100) -> None:
            wl = self._write_lock
            if not wl:
                # cleaned up already
                return
            if wl.acquire(timeout=timeout / 1000):
                eventlog("flush_then_close: acquired the write lock")
                # we have the write lock - we MUST free it!
                wait_for_queue()
            else:
                eventlog("flush_then_close: timeout waiting for the write lock")
                self.close()
                done_callback()

        # normal codepath:
        # -> wait_for_write_lock
        # -> wait_for_queue
        # -> _add_chunks_to_queue
        # -> packet_queued
        # -> wait_for_packet_sent
        # -> close_and_release
        eventlog("flush_then_close: wait_for_write_lock()")
        wait_for_write_lock()

    def close(self, message=None) -> None:
        c = self._conn
        eventlog("Protocol.close(%s) closed=%s, connection=%s", message, self._closed, c)
        if self._closed:
            return
        self._closed = True
        packet = [CONNECTION_LOST]
        if message:
            packet.append(message)
        self.idle_add(self._process_packet_cb, self, packet)
        self.may_log_stats()
        if c:
            self._conn = None
            with log.trap_error("Error closing %s", c):
                eventlog("Protocol.close(%s) calling %s", message, c.close)
                c.close()
        self.terminate_queue_threads()
        self.idle_add(self.clean)
        eventlog("Protocol.close(%s) done", message)

    def may_log_stats(self, log_fn: Callable = log.info):
        if self._log_stats is False:
            return
        icount = self.input_packetcount
        ocount = self.output_packetcount
        if self._log_stats is None and icount == ocount == 0:
            # no data sent or received, skip logging of stats:
            return
        # pylint: disable=import-outside-toplevel
        from xpra.util.stats import std_unit, std_unit_dec

        def log_count(ptype="received", count: int = 0, bytecount: int = -1):
            msg = std_unit(count) + f" packets {ptype}"
            if bytecount > 0:
                msg += " (%s bytes)" % std_unit_dec(bytecount)
            log_fn(msg)

        ibytes = getattr(self._conn, "input_bytecount", -1)
        obytes = getattr(self._conn, "output_bytecount", -1)
        log_count("received", icount, ibytes)
        log_count("sent", ocount, obytes)

    def steal_connection(self, read_callback: Callable[[SizedBuffer], None] | None = None):
        # so we can re-use this connection somewhere else
        # (frees all protocol threads and resources)
        # Note: this method can only be used with non-blocking sockets,
        # and if more than one packet can arrive, the read_callback should be used
        # to ensure that no packets get lost.
        # The caller must call wait_for_io_threads_exit() to ensure that this
        # class is no longer reading from the connection before it can re-use it
        eventlog("steal_connection(%r)", read_callback)
        assert not self._closed, "cannot steal a closed connection"
        if read_callback:
            self._read_queue_put = read_callback
        conn = self._conn
        self._closed = True
        self._conn = None
        if conn:
            # this ensures that we exit the untilConcludes() read/write loop
            conn.set_active(False)
        self.terminate_queue_threads()
        return conn

    def clean(self) -> None:
        # clear all references to ensure we can get garbage collected quickly:
        self._get_packet_cb = no_packet
        self._encoder = noop
        self._write_thread = None
        self._read_thread = None
        self._read_parser_thread = None
        self._write_format_thread = None
        self._process_packet_cb = noop
        self._process_read = noop
        self._read_queue_put = noop
        self._compress = noop
        self._write_lock = None
        self._conn = None  # should be redundant
        self.source_has_more = noop

    def terminate_queue_threads(self) -> None:
        eventlog("terminate_queue_threads()")
        # the format thread will exit:
        self._get_packet_cb = no_packet
        self._source_has_more.set()
        # make all the queue based threads exit by adding the empty marker:
        # write queue:
        owq = self._write_queue
        self._write_queue = exit_queue()
        force_flush_queue(owq)
        # read queue:
        orq = self._read_queue
        self._read_queue = exit_queue()
        force_flush_queue(orq)
        # just in case the read thread is waiting again:
        self._source_has_more.set()
