# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods, it's threads

# but it works on win32, for whatever that's worth.

import os
from enum import Enum
from time import monotonic
from socket import error as socket_error
from threading import Lock, RLock, Event, Thread, current_thread
from queue import Queue
from typing import Dict, List, Tuple, Any, ByteString, Callable, Optional, Iterable

from xpra.os_util import memoryview_to_bytes, strtobytes, bytestostr, hexstr
from xpra.util import repr_ellipsized, ellipsizer, csv, envint, envbool, typedict, nicestr
from xpra.make_thread import make_thread, start_thread
from xpra.net.bytestreams import SOCKET_TIMEOUT, set_socket_timeout
from xpra.net.protocol.header import (
    unpack_header, pack_header, find_xpra_header,
    FLAGS_CIPHER, FLAGS_NOHEADER, FLAGS_FLUSH, HEADER_SIZE,
    )
from xpra.net.protocol.constants import CONNECTION_LOST, INVALID, GIBBERISH
from xpra.net.common import (
    ConnectionClosedException, may_log_packet,
    MAX_PACKET_SIZE, FLUSH_HEADER,
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
from xpra.net.packet_encoding import (
    decode,
    InvalidPacketEncodingException,
    )
from xpra.net.crypto import get_encryptor, get_decryptor, pad, INITIAL_PADDING
from xpra.log import Logger

log = Logger("network", "protocol")
cryptolog = Logger("network", "crypto")


USE_ALIASES = envbool("XPRA_USE_ALIASES", True)
READ_BUFFER_SIZE = envint("XPRA_READ_BUFFER_SIZE", 65536)
#merge header and packet if packet is smaller than:
PACKET_JOIN_SIZE = envint("XPRA_PACKET_JOIN_SIZE", READ_BUFFER_SIZE)
LARGE_PACKET_SIZE = envint("XPRA_LARGE_PACKET_SIZE", 8192)
LOG_RAW_PACKET_SIZE = envbool("XPRA_LOG_RAW_PACKET_SIZE", False)
#inline compressed data in packet if smaller than:
INLINE_SIZE = envint("XPRA_INLINE_SIZE", 32768)
FAKE_JITTER = envint("XPRA_FAKE_JITTER", 0)
MIN_COMPRESS_SIZE = envint("XPRA_MIN_COMPRESS_SIZE", 378)
SEND_INVALID_PACKET = envint("XPRA_SEND_INVALID_PACKET", 0)
SEND_INVALID_PACKET_DATA = strtobytes(os.environ.get("XPRA_SEND_INVALID_PACKET_DATA", b"ZZinvalid-packetZZ"))


def noop():  # pragma: no cover
    pass


def exit_queue() -> Queue:
    queue = Queue()
    for _ in range(10):     #just 2 should be enough!
        queue.put(None)
    return queue

def force_flush_queue(q : Queue):
    try:
        #discard all elements in the old queue and push the None marker:
        try:
            while q.qsize()>0:
                q.get(False)
        except Exception:
            log("force_flush_queue(%s)", q, exc_info=True)
        q.put_nowait(None)
    except Exception:
        log("force_flush_queue(%s)", q, exc_info=True)



class SocketProtocol:
    """
        This class handles sending and receiving packets,
        it will encode and compress them before sending,
        and decompress and decode when receiving.
    """

    TYPE = "xpra"

    def __init__(self, scheduler, conn, process_packet_cb:Callable, get_packet_cb:Optional[Callable]=None):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert scheduler is not None
        assert conn is not None
        self.start_time = monotonic()
        self.timeout_add : Callable = scheduler.timeout_add
        self.idle_add : Callable = scheduler.idle_add
        self.source_remove : Callable = scheduler.source_remove
        self.read_buffer_size : int = READ_BUFFER_SIZE
        self.hangup_delay : int = 1000
        self._conn = conn
        self._process_packet_cb : Callable[[PacketType],None] = process_packet_cb
        self.make_chunk_header : Callable = self.make_xpra_header
        self.make_frame_header : Callable[[str,Iterable], ByteString] = self.noframe_header
        self._write_queue : Queue[Tuple] = Queue(1)
        self._read_queue : Queue[ByteString] = Queue(20)
        self._pre_read = None
        self._process_read : Callable = self.read_queue_put
        self._read_queue_put : Callable = self.read_queue_put
        # Invariant: if .source is None, then _source_has_more == False
        self._get_packet_cb : Optional[Callable] = get_packet_cb
        #counters:
        self.input_stats = {}
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_stats = {}
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        #initial value which may get increased by client/server after handshake:
        self.max_packet_size = MAX_PACKET_SIZE
        self.abs_max_packet_size = 256*1024*1024
        self.large_packets = ["hello", "window-metadata", "sound-data", "notify_show", "setting-change", "shell-reply", "configure-display"]
        self.send_aliases = {}
        self.send_flush_flag = False
        self.receive_aliases = {}
        self._log_stats = None          #None here means auto-detect
        self._closed = False
        self.encoder = "none"
        self._encoder = packet_encoding.get_encoder("none")
        self.compressor = "none"
        self._compress = compression.get_compressor("none")
        self.compression_level = 0
        self.authenticators = ()
        self.encryption = ""
        self.keyfile = ""
        self.keydata = b""
        self.cipher_in = None
        self.cipher_in_name = None
        self.cipher_in_block_size = 0
        self.cipher_in_padding = INITIAL_PADDING
        self.cipher_out = None
        self.cipher_out_name = None
        self.cipher_out_block_size = 0
        self.cipher_out_padding = INITIAL_PADDING
        self._threading_lock = RLock()
        self._write_lock = Lock()
        self._write_thread : Optional[Thread] = None
        self._read_thread : Optional[Thread]= make_thread(self._read_thread_loop, "read", daemon=True)
        self._read_parser_thread : Optional[Thread]= None         #started when needed
        self._write_format_thread : Optional[Thread]= None        #started when needed
        self._source_has_more = Event()
        self.receive_pending = False
        self.wait_for_header = False
        self.source_has_more = self.source_has_more_start
        self.flush_then_close = self.do_flush_then_close

    STATE_FIELDS : Tuple[str,...] = (
        "max_packet_size", "large_packets", "send_aliases", "receive_aliases",
        "cipher_in", "cipher_in_name", "cipher_in_block_size", "cipher_in_padding",
        "cipher_out", "cipher_out_name", "cipher_out_block_size", "cipher_out_padding",
        "compression_level", "encoder", "compressor",
        )

    def save_state(self) -> Dict[str,Any]:
        state = {}
        for x in self.STATE_FIELDS:
            state[x] = getattr(self, x)
        return state

    def restore_state(self, state:Dict[str,Any]) -> None:
        assert state is not None
        for x in self.STATE_FIELDS:
            assert x in state, f"field {x!r} is missing"
            setattr(self, x, state[x])
        #special handling for compressor / encoder which are named objects:
        self.enable_compressor(self.compressor)
        self.enable_encoder(self.encoder)


    def is_closed(self) -> bool:
        return self._closed

    def is_sending_encrypted(self) -> bool:
        return bool(self.cipher_out) or self._conn.socktype in ("ssl", "wss", "ssh", "quic")

    def wait_for_io_threads_exit(self, timeout=None) -> bool:
        io_threads = (self._read_thread, self._write_thread, self._read_parser_thread, self._read_parser_thread)
        current = current_thread()
        for t in io_threads:
            if t and t!=current and t.is_alive():
                t.join(timeout)
        exited = True
        cinfo = self._conn or "cleared connection"
        for t in io_threads:
            if t and t!=current and t.is_alive():
                log.warn("Warning: %s thread of %s is still alive (timeout=%s)", t.name, cinfo, timeout)
                exited = False
        return exited

    def set_packet_source(self, get_packet_cb:Callable) -> None:
        self._get_packet_cb = get_packet_cb


    def set_cipher_in(self, ciphername:str, iv, password, key_salt, key_hash, key_size:int, iterations:int, padding):
        cryptolog("set_cipher_in%s", (ciphername, iv, password, key_salt, key_hash, key_size, iterations))
        self.cipher_in, self.cipher_in_block_size = get_decryptor(ciphername,
                                                                  iv, password,
                                                                  key_salt,key_hash, key_size, iterations)
        self.cipher_in_padding = padding
        if self.cipher_in_name!=ciphername:
            cryptolog.info("receiving data using %s encryption", ciphername)
            self.cipher_in_name = ciphername

    def set_cipher_out(self, ciphername:str, iv, password, key_salt, key_hash, key_size:int, iterations:int, padding):
        cryptolog("set_cipher_out%s", (ciphername, iv, password, key_salt, key_hash, key_size, iterations, padding))
        self.cipher_out, self.cipher_out_block_size = get_encryptor(ciphername,
                                                                    iv, password,
                                                                    key_salt, key_hash, key_size, iterations)
        self.cipher_out_padding = padding
        if self.cipher_out_name!=ciphername:
            cryptolog.info("sending data using %s encryption", ciphername)
            self.cipher_out_name = ciphername


    def __repr__(self):
        return f"Protocol({self._conn})"

    def get_threads(self) -> Tuple[Thread,...]:
        return tuple(x for x in (
            self._write_thread,
            self._read_thread,
            self._read_parser_thread,
            self._write_format_thread,
            ) if x is not None)

    def parse_remote_caps(self, caps : typedict) -> None:
        for k,v in caps.dictget("aliases", {}).items():
            self.send_aliases[bytestostr(k)] = v
        self.send_flush_flag = FLUSH_HEADER and caps.boolget("flush", False)
        set_socket_timeout(self._conn, SOCKET_TIMEOUT)


    def set_receive_aliases(self, aliases:Dict) -> None:
        self.receive_aliases = aliases

    def get_info(self, alias_info:bool=True) -> Dict[str,Any]:
        shm = self._source_has_more
        info = {
            "large_packets"         : self.large_packets,
            "compression_level"     : self.compression_level,
            "max_packet_size"       : self.max_packet_size,
            "aliases"               : USE_ALIASES,
            "flush"                 : self.send_flush_flag,
            "has_more"              : shm and shm.is_set(),
            "receive-pending"       : self.receive_pending,
            }
        c = self.compressor
        if c:
            info["compressor"] = c
        e = self.encoder
        if e:
            info["encoder"] = e
        if alias_info:
            info["send_alias"] = self.send_aliases
            info["receive_alias"] = self.receive_aliases
        c = self._conn
        if c:
            try:
                info.update(c.get_info())
            except Exception:
                log.error("error collecting connection information on %s", c, exc_info=True)
        #add stats to connection info:
        info.setdefault("input", {}).update({
                       "buffer-size"            : self.read_buffer_size,
                       "hangup-delay"           : self.hangup_delay,
                       "packetcount"            : self.input_packetcount,
                       "raw_packetcount"        : self.input_raw_packetcount,
                       "count"                  : self.input_stats,
                       "cipher"                 : {"": self.cipher_in_name or "",
                                                   "padding"        : self.cipher_in_padding,
                                                   },
                        })
        info.setdefault("output", {}).update({
                        "packet-join-size"      : PACKET_JOIN_SIZE,
                        "large-packet-size"     : LARGE_PACKET_SIZE,
                        "inline-size"           : INLINE_SIZE,
                        "min-compress-size"     : MIN_COMPRESS_SIZE,
                        "packetcount"           : self.output_packetcount,
                        "raw_packetcount"       : self.output_raw_packetcount,
                        "count"                 : self.output_stats,
                        "cipher"                : {"": self.cipher_out_name or "",
                                                   "padding" : self.cipher_out_padding
                                                   },
                        })
        for t in (self._write_thread, self._read_thread, self._read_parser_thread, self._write_format_thread):
            if t:
                info.setdefault("thread", {})[t.name] = t.is_alive()
        return info


    def start(self) -> None:
        def start_network_read_thread():
            if not self._closed:
                self._read_thread.start()
        self.idle_add(start_network_read_thread)
        if SEND_INVALID_PACKET:
            self.timeout_add(SEND_INVALID_PACKET*1000, self.raw_write, SEND_INVALID_PACKET_DATA)


    def send_disconnect(self, reasons, done_callback=noop) -> None:
        packet = ["disconnect"]+[nicestr(x) for x in reasons]
        self.flush_then_close(self.encode, packet, done_callback=done_callback)

    def send_now(self, packet : PacketType) -> None:
        if self._closed:
            log("send_now(%s ...) connection is closed already, not sending", packet[0])
            return
        log("send_now(%s ...)", packet[0])
        if self._get_packet_cb:
            raise RuntimeError(f"cannot use send_now when a packet source exists! (set to {self._get_packet_cb})")
        tmp_queue = [packet]
        def packet_cb():
            self._get_packet_cb = None
            if not tmp_queue:
                raise RuntimeError("packet callback used more than once!")
            packet = tmp_queue.pop()
            return (packet, )
        self._get_packet_cb = packet_cb
        self.source_has_more()

    def source_has_more_start(self) -> None:      #pylint: disable=method-hidden
        shm = self._source_has_more
        if not shm or self._closed:
            return
        #from now on, take the shortcut:
        self.source_has_more = shm.set
        shm.set()
        #start the format thread:
        if not self._write_format_thread and not self._closed:
            with self._threading_lock:
                assert not self._write_format_thread, "write format thread already started"
                self._write_format_thread = start_thread(self.write_format_thread_loop, "format", daemon=True)

    def write_format_thread_loop(self) -> None:
        log("write_format_thread_loop starting")
        try:
            while not self._closed:
                self._source_has_more.wait()
                gpc = self._get_packet_cb
                if self._closed or not gpc:
                    return
                self._add_packet_to_queue(*gpc())
        except Exception as e:
            if self._closed:
                return
            self._internal_error("error in network packet write/format", e, exc_info=True)

    def _add_packet_to_queue(self, packet : PacketType,
                             start_cb:Optional[Callable]=None, end_cb:Optional[Callable]=None, fail_cb:Optional[Callable]=None,
                             synchronous=True, has_more=False, wait_for_more=False) -> None:
        if not has_more:
            shm = self._source_has_more
            if shm:
                shm.clear()
        if packet is None:
            return
        #log("add_packet_to_queue(%s ... %s, %s, %s)", packet[0], synchronous, has_more, wait_for_more)
        packet_type : Union[str,int] = packet[0]
        chunks : NetPacketType = self.encode(packet)
        with self._write_lock:
            if self._closed:
                return
            try:
                self._add_chunks_to_queue(packet_type, chunks,
                                          start_cb, end_cb, fail_cb,
                                          synchronous, has_more or wait_for_more)
            except:
                log.error("Error: failed to queue '%s' packet", packet[0])
                log("add_chunks_to_queue%s", (chunks, start_cb, end_cb, fail_cb), exc_info=True)
                raise

    def _add_chunks_to_queue(self, packet_type:str, chunks,
                             start_cb:Optional[Callable]=None, end_cb:Optional[Callable]=None, fail_cb:Optional[Callable]=None,
                             synchronous=True, more=False) -> None:
        """ the write_lock must be held when calling this function """
        items = []
        for proto_flags,index,level,data in chunks:
            payload_size = len(data)
            if not payload_size:
                raise RuntimeError(f"missing data in chunk {index}")
            actual_size = payload_size
            if self.cipher_out:
                proto_flags |= FLAGS_CIPHER
                #note: since we are padding: l!=len(data)
                if self.cipher_out_block_size==0:
                    padding_size = 0
                else:
                    padding_size = self.cipher_out_block_size - (payload_size % self.cipher_out_block_size)
                if padding_size==0:
                    padded = data
                else:
                    # pad byte value is number of padding bytes added
                    padded = memoryview_to_bytes(data) + pad(self.cipher_out_padding, padding_size)
                    actual_size += padding_size
                if len(padded)!=actual_size:
                    raise RuntimeError(f"expected padded size to be {actual_size}, but got {len(padded)}")
                data = self.cipher_out.update(padded)
                if len(data)!=actual_size:
                    raise RuntimeError(f"expected encrypted size to be {actual_size}, but got {len(data)}")
                cryptolog("sending %s bytes %s encrypted with %s bytes of padding",
                          payload_size, self.cipher_out_name, padding_size)
            if proto_flags & FLAGS_NOHEADER:
                assert not self.cipher_out
                #for plain/text packets (ie: gibberish response)
                log("sending %s bytes without header", payload_size)
                items.append(data)
            else:
                #if the other end can use this flag, expose it:
                if self.send_flush_flag and not more and index==0:
                    proto_flags |= FLAGS_FLUSH
                #the xpra packet header:
                #(WebSocketProtocol may also add a websocket header too)
                header = self.make_chunk_header(packet_type, proto_flags, level, index, payload_size)
                if actual_size<PACKET_JOIN_SIZE:
                    if not isinstance(data, bytes):
                        data = memoryview_to_bytes(data)
                    items.append(header+data)
                else:
                    items.append(header)
                    items.append(data)
        #WebSocket header may be added here:
        frame_header = self.make_frame_header(packet_type, items)       #pylint: disable=assignment-from-none
        if frame_header:
            item0 = items[0]
            if len(item0)<PACKET_JOIN_SIZE:
                if not isinstance(item0, bytes):
                    item0 = memoryview_to_bytes(item0)
                items[0] = frame_header + item0
            else:
                items.insert(0, frame_header)
        self.raw_write(items, packet_type, start_cb, end_cb, fail_cb, synchronous, more)

    @staticmethod
    def make_xpra_header(_packet_type, proto_flags, level, index, payload_size) -> ByteString:
        return pack_header(proto_flags, level, index, payload_size)

    @staticmethod
    def noframe_header(_packet_type, _items) -> ByteString:
        return b""


    def start_write_thread(self) -> None:
        with self._threading_lock:
            assert not self._write_thread, "write thread already started"
            self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def raw_write(self, items, packet_type=None,
                  start_cb:Optional[Callable]=None, end_cb:Optional[Callable]=None, fail_cb:Optional[Callable]=None,
                  synchronous=True, more=False) -> None:
        """ Warning: this bypasses the compression and packet encoder! """
        if self._write_thread is None:
            log("raw_write for %s, starting write thread", packet_type)
            self.start_write_thread()
        self._write_queue.put((items, packet_type, start_cb, end_cb, fail_cb, synchronous, more))


    def enable_default_encoder(self) -> None:
        opts = packet_encoding.get_enabled_encoders()
        assert opts, "no packet encoders available!"
        self.enable_encoder(opts[0])

    def enable_encoder_from_caps(self, caps:typedict) -> bool:
        opts = packet_encoding.get_enabled_encoders(order=packet_encoding.PERFORMANCE_ORDER)
        log(f"enable_encoder_from_caps(..) options={opts}")
        for e in opts:
            if caps.boolget(e, e=="bencode"):
                self.enable_encoder(e)
                return True
            log(f"client does not support {e}")
        log.error("no matching packet encoder found!")
        return False

    def enable_encoder(self, e:str) -> None:
        self._encoder = packet_encoding.get_encoder(e)
        self.encoder = e
        log(f"enable_encoder({e}): {self._encoder}")


    def enable_default_compressor(self) -> None:
        opts = compression.get_enabled_compressors()
        if opts:
            self.enable_compressor(opts[0])
        else:
            self.enable_compressor("none")

    def enable_compressor_from_caps(self, caps:typedict) -> None:
        if self.compression_level==0:
            self.enable_compressor("none")
            return
        opts = compression.get_enabled_compressors(order=compression.PERFORMANCE_ORDER)
        compressors = caps.strtupleget("compressors")
        log(f"enable_compressor_from_caps(..) options={opts}, compressors from caps={compressors}")
        for c in opts:      #ie: [zlib, lz4]
            if c=="none":
                continue
            if c in compressors or caps.boolget(c):
                self.enable_compressor(c)
                return
            log(f"client does not support {c}")
        log.warn("Warning: compression disabled, no matching compressor found")
        log.warn(f" capabilities: {csv(compressors)}")
        log.warn(f" enabled compressors: {csv(opts)}")
        self.enable_compressor("none")

    def enable_compressor(self, compressor:str) -> None:
        self._compress = compression.get_compressor(compressor)
        self.compressor = compressor
        log(f"enable_compressor({compressor}): {self._compress}")


    def encode(self, packet_in : PacketType) -> List[NetPacketType]:
        """
        Given a packet (tuple or list of items), converts it for the wire.
        This method returns all the binary packets to send, as an array of:
        (index, compression_level and compression flags, binary_data)
        The index, if positive indicates the item to populate in the packet
        whose index is zero.
        ie: ["blah", [large binary data], "hello", 200]
        may get converted to:
        [
            (1, compression_level, [large binary data now zlib compressed]),
            (0,                 0, bencoded/rencoded(["blah", '', "hello", 200]))
        ]
        """
        packets : List[NetPacketType] = []
        packet = list(packet_in)
        level = self.compression_level
        size_check = LARGE_PACKET_SIZE
        min_comp_size = MIN_COMPRESS_SIZE
        packet_type = packet[0]
        payload_size = 0
        for i in range(1, len(packet)):
            item = packet[i]
            if item is None:
                raise TypeError(f"invalid None value in {packet_type!r} packet at index {i}")
            if isinstance(item, Enum):
                try:
                    packet[i] = int(item)
                except ValueError:
                    packet[i] = str(item)
                continue
            if isinstance(item, (int, bool, dict, list, tuple)):
                continue
            try:
                l = len(item)
            except TypeError as e:
                raise TypeError(f"invalid type {type(item)} in {packet_type!r} packet at index {i}: {e}") from None
            if isinstance(item, Compressible):
                #this is a marker used to tell us we should compress it now
                #(used by the client for clipboard data)
                item = item.compress()
                packet[i] = item
                #(it may now be a "Compressed" item and be processed further)
            if isinstance(item, memoryview):
                if self.encoder!="rencodeplus":
                    packet[i] = item.tobytes()
                continue
            if isinstance(item, LargeStructure):
                packet[i] = item.data
                continue
            if isinstance(item, Compressed):
                #already compressed data (usually pixels, cursors, etc)
                if not item.can_inline or l>INLINE_SIZE:
                    il = 0
                    if isinstance(item, LevelCompressed):
                        # unlike `Compressed` (usually pixels, decompressed in the paint thread),
                        # `LevelCompressed` is decompressed by the network layer
                        # so we must tell it how to do that and using the level flag:
                        il = item.level
                    packets.append((0, i, il, item.data))
                    packet[i] = b''
                    payload_size += len(item.data)
                else:
                    #data is small enough, inline it:
                    packet[i] = item.data
                    if isinstance(item.data, memoryview) and self.encoder!="rencodeplus":
                        packet[i] = item.data.tobytes()
                    min_comp_size += l
                    size_check += l
                continue
            if isinstance(item, bytes) and level>0 and l>LARGE_PACKET_SIZE:
                log.warn("Warning: found a large uncompressed item")
                log.warn(f" in packet {packet_type!r} at position {i}: {len(item)} bytes")
                #add new binary packet with large item:
                cl, cdata = self._compress(item, level)
                packets.append((0, i, cl, cdata))
                payload_size += len(cdata)
                #replace this item with an empty string placeholder:
                packet[i] = ''
                continue
            if not isinstance(item, (str, bytes)):
                log.warn(f"Warning: unexpected data type {type(item)}")
                log.warn(f" in {packet_type!r} packet at position {i}: {repr_ellipsized(item)}")
        #now the main packet (or what is left of it):
        self.output_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
        if USE_ALIASES:
            alias = self.send_aliases.get(packet_type)
            if alias:
                #replace the packet type with the alias:
                packet[0] = alias
        try:
            main_packet, proto_flags = self._encoder(packet)
        except Exception:
            if self._closed:
                return []
            log.error(f"Error: failed to encode packet: {packet}", exc_info=True)
            #make the error a bit nicer to parse: undo aliases:
            packet[0] = packet_type
            from xpra.net.protocol.check import verify_packet
            verify_packet(packet)
            raise
        l = len(main_packet)
        payload_size += l
        if l>size_check and bytestostr(packet_in[0]) not in self.large_packets:
            log.warn("Warning: found large packet")
            log.warn(f" {packet_type!r} packet is {len(main_packet)} bytes: ")
            log.warn(" argument types: %s", csv(type(x) for x in packet[1:]))
            log.warn(" sizes: %s", csv(len(strtobytes(x)) for x in packet[1:]))
            log.warn(f" packet: {repr_ellipsized(packet, limit=4096)}")
        #compress, but don't bother for small packets:
        if level>0 and l>min_comp_size:
            try:
                cl, cdata = self._compress(main_packet, level)
                if LOG_RAW_PACKET_SIZE and packet_type!="logging":
                    log.info(f"         {packet_type:<32}: %i bytes compressed", len(cdata))
            except Exception as e:
                log.error(f"Error compressing {packet_type} packet")
                log.estr(e)
                raise
            packets.append((proto_flags, 0, cl, cdata))
        else:
            packets.append((proto_flags, 0, 0, main_packet))
        may_log_packet(True, packet_type, packet)
        if LOG_RAW_PACKET_SIZE and packet_type!="logging":
            log.info(f"sending  {packet_type:<32}: %i bytes", HEADER_SIZE + payload_size)
        return packets

    def set_compression_level(self, level : int) -> None:
        #this may be used next time encode() is called
        if level<0 or level>10:
            raise ValueError(f"invalid compression level: {level} (must be between 0 and 10")
        self.compression_level = level


    def _io_thread_loop(self, name:str, callback:Callable) -> None:
        try:
            log(f"io_thread_loop({name}, {callback}) loop starting")
            while not self._closed and callback():
                "wait for an exit condition"
            log(f"io_thread_loop({name}, {callback}) loop ended, closed={self._closed}")
        except ConnectionClosedException as e:
            log(f"{self._conn} closed in {name} loop", exc_info=True)
            if not self._closed:
                #ConnectionClosedException means the warning has been logged already
                self._connection_lost(str(e))
        except (OSError, socket_error) as e:
            if not self._closed:
                self._internal_error(f"{name} connection {e} reset", exc_info=e.args[0] not in ABORT)
        except Exception as e:
            #can happen during close(), in which case we just ignore:
            if not self._closed:
                log.error(f"Error: {name} on {self._conn} failed: {type(e)}", exc_info=True)
                self.close()


    def _write_thread_loop(self) -> None:
        self._io_thread_loop("write", self._write)
    def _write(self) -> bool:
        items = self._write_queue.get()
        # Used to signal that we should exit:
        if items is None:
            log("write thread: empty marker, exiting")
            self.close()
            return False
        return self.write_items(*items)

    def write_items(self, buf_data, packet_type:str="",
                    start_cb:Optional[Callable]=None, end_cb:Optional[Callable]=None,
                    fail_cb:Optional[Callable]=None, synchronous:bool=True, more:bool=False):
        conn = self._conn
        if not conn:
            return False
        try:
            if more or len(buf_data)>1:
                conn.set_nodelay(False)
            if len(buf_data)>1:
                conn.set_cork(True)
        except OSError:
            log("write_items(..)", exc_info=True)
            if not self._closed:
                raise
        if start_cb:
            try:
                start_cb(conn.output_bytecount)
            except Exception:
                if not self._closed:
                    log.error(f"Error on write start callback {start_cb}", exc_info=True)
        self.write_buffers(buf_data, packet_type, fail_cb, synchronous)
        try:
            if len(buf_data)>1:
                conn.set_cork(False)
            if not more:
                conn.set_nodelay(True)
        except OSError:
            log("write_items(..)", exc_info=True)
            if not self._closed:
                raise
        if end_cb:
            try:
                end_cb(self._conn.output_bytecount)
            except Exception:
                if not self._closed:
                    log.error(f"Error on write end callback {end_cb}", exc_info=True)
        return True

    def write_buffers(self, buf_data, packet_type:str, _fail_cb:Optional[Callable], _synchronous:bool):
        con = self._conn
        if not con:
            return
        for buf in buf_data:
            while buf and not self._closed:
                written = self.con_write(con, buf, packet_type)
                #example test code, for sending small chunks very slowly:
                #written = con.write(buf[:1024])
                #import time
                #time.sleep(0.05)
                if written:
                    buf = buf[written:]
                    self.output_raw_packetcount += 1
        self.output_packetcount += 1

    def con_write(self, con, buf:ByteString, packet_type:str):
        return con.write(buf, packet_type)


    def _read_thread_loop(self) -> None:
        self._io_thread_loop("read", self._read)
    def _read(self) -> bool:
        buf = self.con_read()
        #log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
        #add to the read queue (or whatever takes its place - see steal_connection)
        self._process_read(buf)
        if not buf:
            log("read thread: eof")
            # give time to the parse thread to call close itself,
            # so it has time to parse and process the last packet received
            self.timeout_add(1000, self.close)
            return False
        self.input_raw_packetcount += 1
        return True

    def con_read(self) -> ByteString:
        if self._pre_read:
            r = self._pre_read.pop(0)
            log("con_read() using pre_read value: %r", ellipsizer(r))
            return r
        return self._conn.read(self.read_buffer_size)


    def _internal_error(self, message="", exc=None, exc_info=False) -> None:
        #log exception info with last log message
        if self._closed:
            return
        ei = exc_info
        if exc:
            ei = None   #log it separately below
        log.error(f"Error: {message}", exc_info=ei)
        if exc:
            log.error(f" {exc}", exc_info=exc_info)
        self.idle_add(self._connection_lost, message)

    def _connection_lost(self, message="", exc_info=False) -> bool:
        log(f"connection lost: {message}", exc_info=exc_info)
        self.close(message)
        return False


    def invalid(self, msg, data) -> None:
        self.idle_add(self._process_packet_cb, self, [INVALID, msg, data])
        # Then hang up:
        self.timeout_add(1000, self._connection_lost, msg)

    def gibberish(self, msg, data) -> None:
        self.idle_add(self._process_packet_cb, self, [GIBBERISH, msg, data])
        # Then hang up:
        self.timeout_add(self.hangup_delay, self._connection_lost, msg)


    #delegates to invalid_header()
    #(so this can more easily be intercepted and overridden)
    def invalid_header(self, proto, data:ByteString, msg="invalid packet header") -> None:
        self._invalid_header(proto, data, msg)

    def _invalid_header(self, proto, data:ByteString, msg="invalid packet header") -> None:
        log("invalid_header(%s, %s bytes: '%s', %s)",
               proto, len(data or ""), msg, ellipsizer(data))
        guess = guess_packet_type(data)
        if guess:
            err = f"{msg}: {guess}"
        else:
            err = "%s: 0x%s" % (msg, hexstr(data[:HEADER_SIZE]))
            if len(data)>1:
                err += " read buffer=%s (%i bytes)" % (repr_ellipsized(data), len(data))
        self.gibberish(err, data)


    def process_read(self, data:ByteString) -> None:
        self._read_queue_put(data)

    def read_queue_put(self, data:ByteString) -> None:
        #start the parse thread if needed:
        if not self._read_parser_thread and not self._closed:
            if data is None:
                log("empty marker in read queue, exiting")
                self.idle_add(self.close)
                return
            self.start_read_parser_thread()
        self._read_queue.put(data)
        #from now on, take shortcut:
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
        read_buffers = []
        payload_size = -1
        padding_size = 0
        packet_index = 0
        protocol_flags = 0
        data_size = 0
        compression_level = 0
        raw_packets = {}
        PACKET_HEADER_CHAR = ord("P")
        while not self._closed:
            #log("parse thread: %i items in read queue", self._read_queue.qsize())
            buf = self._read_queue.get()
            if not buf:
                log("parse thread: empty marker, exiting")
                self.idle_add(self.close)
                return

            read_buffers.append(buf)
            if self.wait_for_header:
                #we're waiting to see the first xpra packet header
                #which may come after some random characters
                #(ie: when connecting over ssh, the channel may contain some unexpected output)
                #for this to work, we have to assume that the initial packet is smaller than 64KB:
                joined = b"".join(read_buffers)
                pos = find_xpra_header(joined)
                if pos<0:
                    #wait some more:
                    read_buffers = [joined]
                    continue
                #found it, so proceed:
                read_buffers = [joined[pos:]]
                self.wait_for_header = False

            while read_buffers:
                #have we read the header yet?
                if payload_size<0:
                    #try to handle the first buffer:
                    buf = read_buffers[0]
                    if not header and buf[0]!=PACKET_HEADER_CHAR:
                        self.invalid_header(self, buf, "invalid packet header byte")
                        return
                    #how much to we need to slice off to complete the header:
                    read = min(len(buf), HEADER_SIZE-len(header))
                    header += memoryview_to_bytes(buf[:read])
                    if len(header)<HEADER_SIZE:
                        #need to process more buffers to get a full header:
                        read_buffers.pop(0)
                        continue
                    if len(buf)<=read:
                        #we only got the header:
                        assert len(buf)==read
                        read_buffers.pop(0)
                        continue
                    #got the full header and more, keep the rest of the packet:
                    read_buffers[0] = buf[read:]
                    #parse the header:
                    # format: struct.pack(b'cBBBL', ...) - HEADER_SIZE bytes
                    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(header)

                    #sanity check size (will often fail if not an xpra client):
                    if data_size>self.abs_max_packet_size:
                        self.invalid_header(self, header, f"invalid size in packet header: {data_size}")
                        return

                    if packet_index>=16:
                        self.invalid_header(self, header, f"invalid packet index: {packet_index}")
                        return

                    if protocol_flags & FLAGS_CIPHER:
                        if not self.cipher_in_name:
                            cryptolog.warn("Warning: received cipher block,")
                            cryptolog.warn(" but we don't have a cipher to decrypt it with,")
                            cryptolog.warn(" not an xpra client?")
                            self.invalid_header(self, header, "invalid encryption packet flag (no cipher configured)")
                            return
                        if self.cipher_in_block_size==0:
                            padding_size = 0
                        else:
                            padding_size = self.cipher_in_block_size - (data_size % self.cipher_in_block_size)
                        payload_size = data_size + padding_size
                    else:
                        #no cipher, no padding:
                        padding_size = 0
                        payload_size = data_size
                    if payload_size<=0:
                        raise ValueError(f"invalid payload size {payload_size} for header {header!r}")

                    if payload_size>self.max_packet_size:
                        #this packet is seemingly too big, but check again from the main UI thread
                        #this gives 'set_max_packet_size' a chance to run from "hello"
                        def check_packet_size(size_to_check, packet_header):
                            if self._closed:
                                return False
                            log("check_packet_size(%#x, %s) max=%#x",
                                size_to_check, hexstr(packet_header), self.max_packet_size)
                            if size_to_check>self.max_packet_size:
                                # pylint: disable=line-too-long
                                msg = f"packet size requested is {size_to_check} but maximum allowed is {self.max_packet_size}"
                                self.invalid(msg, packet_header)
                            return False
                        self.timeout_add(1000, check_packet_size, payload_size, header)

                #how much data do we have?
                bl = sum(len(v) for v in read_buffers)
                if bl<payload_size:
                    # incomplete packet, wait for the rest to arrive
                    break

                data : ByteString
                buf = read_buffers[0]
                if len(buf)==payload_size:
                    #exact match, consume it all:
                    data = read_buffers.pop(0)
                elif len(buf)>payload_size:
                    #keep rest of packet for later:
                    read_buffers[0] = buf[payload_size:]
                    data = buf[:payload_size]
                else:
                    #we need to aggregate chunks,
                    #just concatenate them all:
                    data = b"".join(read_buffers)
                    if bl==payload_size:
                        #nothing left:
                        read_buffers = []
                    else:
                        #keep the left over:
                        read_buffers = [data[payload_size:]]
                        data = data[:payload_size]

                #decrypt if needed:
                if self.cipher_in:
                    if not protocol_flags & FLAGS_CIPHER:
                        self.invalid("unencrypted packet dropped", data)
                        return
                    cryptolog("received %i %s encrypted bytes with %i padding",
                              payload_size, self.cipher_in_name, padding_size)
                    data = self.cipher_in.update(data)
                    if padding_size > 0:
                        def debug_str(s):
                            try:
                                return hexstr(s)
                            except Exception:
                                return csv(tuple(s))
                        # pad byte value is number of padding bytes added
                        padtext = pad(self.cipher_in_padding, padding_size)
                        if data.endswith(padtext):
                            cryptolog("found %s %s padding", self.cipher_in_padding, self.cipher_in_name)
                        else:
                            actual_padding = data[-padding_size:]
                            cryptolog.warn("Warning: %s decryption failed: invalid padding", self.cipher_in_name)
                            cryptolog(" cipher block size=%i, data size=%i", self.cipher_in_block_size, data_size)
                            cryptolog(" data does not end with %i %s padding bytes %s (%s)",
                                      padding_size, self.cipher_in_padding, debug_str(padtext), type(padtext))
                            cryptolog(" but with %i bytes: %s (%s)",
                                      len(actual_padding), debug_str(actual_padding), type(data))
                            cryptolog(" decrypted data (%i bytes): %r..", len(data), data[:128])
                            cryptolog(" decrypted data (hex): %s..", debug_str(data[:128]))
                            self._internal_error(f"{self.cipher_in_name} encryption padding error - wrong key?")
                            return
                        data = data[:-padding_size]
                #uncompress if needed:
                if compression_level>0:
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
                            #only include the exception text when not using encryption
                            #as this may leak crypto information:
                            msg += f" {e}"
                        del e
                        self.gibberish(msg, data)
                        return

                if self._closed:
                    return

                #we're processing this packet,
                #make sure we get a new header next time
                header = b""
                if packet_index>0:
                    if packet_index in raw_packets:
                        self.invalid(f"duplicate raw packet at index {packet_index}", data)
                        return
                    #raw packet, store it and continue:
                    raw_packets[packet_index] = data
                    payload_size = -1
                    if len(raw_packets)>=4:
                        self.invalid(f"too many raw packets: {len(raw_packets)}", data)
                        return
                    #we know for sure that another packet should follow immediately
                    #the one with packet_index=0 for this raw packet
                    self.receive_pending = True
                    continue
                #final packet (packet_index==0), decode it:
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
                    log(f"failed to parse {etype} packet: %s", hexstr(data[:128]), exc_info=True)
                    data_str = memoryview_to_bytes(data)
                    log(" data: %s", repr_ellipsized(data_str))
                    log(f" packet index={packet_index}, packet size={payload_size}, buffer size={bl}")
                    log(" full data: %s", hexstr(data_str))
                    self.gibberish(f"failed to parse {etype} packet", data)
                    return

                if self._closed:
                    return
                payload_size = len(data)
                #add any raw packets back into it:
                if raw_packets:
                    for index,raw_data in raw_packets.items():
                        #replace placeholder with the raw_data packet data:
                        packet[index] = raw_data
                        payload_size += len(raw_data)
                    raw_packets = {}

                packet_type = packet[0]
                if self.receive_aliases and isinstance(packet_type, int):
                    packet_type = self.receive_aliases.get(packet_type)
                    if packet_type:
                        packet[0] = packet_type
                    else:
                        raise ValueError(f"receive alias not found for packet type {packet_type}")
                else:
                    packet_type = bytestostr(packet_type)
                self.input_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
                if LOG_RAW_PACKET_SIZE and packet_type!="logging":
                    log.info(f"received {packet_type:<32}: %i bytes", HEADER_SIZE + payload_size)
                payload_size = -1
                self.input_packetcount += 1
                self.receive_pending = bool(protocol_flags & FLAGS_FLUSH)
                log("processing packet %s", bytestostr(packet_type))
                self._process_packet_cb(self, tuple(packet))
                del packet

    def do_flush_then_close(self, encoder:Optional[Callable]=None,
                         last_packet=None,
                         done_callback:Callable=noop) -> None:    #pylint: disable=method-hidden
        """ Note: this is best-effort only
            the packet may not get sent.

            We try to get the write lock,
            we try to wait for the write queue to flush
            we queue our last packet,
            we wait again for the queue to flush,
            then no matter what, we close the connection and stop the threads.
        """
        def closing_already(encoder, last_packet, done_callback=noop):
            log("flush_then_close%s had already been called, this new request has been ignored",
                (encoder, last_packet, done_callback))
        self.flush_then_close = closing_already
        log("flush_then_close%s closed=%s", (encoder, last_packet, done_callback), self._closed)
        if self._closed:
            log("flush_then_close: already closed")
            done_callback()
            return
        def writelockrelease() -> None:
            wl = self._write_lock
            try:
                if wl:
                    wl.release()
            except Exception as e:
                log(f"error releasing the write lock: {e}")
        def close_and_release():
            log("close_and_release()")
            self.close()
            writelockrelease()
            done_callback()
        def wait_for_queue(timeout:int=10) -> None:
            #IMPORTANT: if we are here, we have the write lock held!
            if not self._write_queue.empty():
                #write queue still has stuff in it..
                if timeout<=0:
                    log("flush_then_close: queue still busy, closing without sending the last packet")
                    close_and_release()
                    return
                #retry later:
                log("flush_then_close: still waiting for queue to flush")
                self.timeout_add(100, wait_for_queue, timeout-1)
                return
            if not last_packet:
                close_and_release()
                return
            log("flush_then_close: queue is now empty, sending the last packet and closing")
            def wait_for_packet_sent():
                closed = self._closed
                log("flush_then_close: wait_for_packet_sent() queue.empty()=%s, closed=%s",
                    self._write_queue.empty(), closed)
                if self._write_queue.empty() or closed:
                    #it got sent, we're done!
                    close_and_release()
                    return False
                return not closed     #run until we manage to close (here or via the timeout)
            def packet_queued(*_args):
                #if we're here, we have the lock and the packet is in the write queue
                log("flush_then_close: packet_queued() closed=%s", self._closed)
                if wait_for_packet_sent():
                    #check again every 100ms
                    self.timeout_add(100, wait_for_packet_sent)
            if encoder:
                chunks = encoder(last_packet)
                self._add_chunks_to_queue(last_packet[0], chunks,
                                          start_cb=None, end_cb=packet_queued,
                                          synchronous=False, more=False)
            else:
                self.raw_write((last_packet, ), "flush-then-close")
            #just in case wait_for_packet_sent never fires:
            self.timeout_add(5*1000, close_and_release)

        def wait_for_write_lock(timeout:int=100) -> None:
            wl = self._write_lock
            if not wl:
                #cleaned up already
                return
            if wl.acquire(timeout=timeout/1000):
                log("flush_then_close: acquired the write lock")
                #we have the write lock - we MUST free it!
                wait_for_queue()
            else:
                log("flush_then_close: timeout waiting for the write lock")
                self.close()
                done_callback()
        #normal codepath:
        # -> wait_for_write_lock
        # -> wait_for_queue
        # -> _add_chunks_to_queue
        # -> packet_queued
        # -> wait_for_packet_sent
        # -> close_and_release
        log("flush_then_close: wait_for_write_lock()")
        wait_for_write_lock()

    def close(self, message=None) -> None:
        c = self._conn
        log("Protocol.close(%s) closed=%s, connection=%s", message, self._closed, c)
        if self._closed:
            return
        self._closed = True
        packet = [CONNECTION_LOST]
        if message:
            packet.append(message)
        self.idle_add(self._process_packet_cb, self, packet)
        if c:
            self._conn = None
            try:
                log("Protocol.close(%s) calling %s", message, c.close)
                c.close()
                if self._log_stats is None and c.input_bytecount==0 and c.output_bytecount==0:
                    #no data sent or received, skip logging of stats:
                    self._log_stats = False
                if self._log_stats:
                    # pylint: disable=import-outside-toplevel
                    from xpra.simple_stats import std_unit, std_unit_dec
                    log.info("connection closed after %s packets received (%s bytes) and %s packets sent (%s bytes)",
                         std_unit(self.input_packetcount), std_unit_dec(c.input_bytecount),
                         std_unit(self.output_packetcount), std_unit_dec(c.output_bytecount)
                         )
            except Exception:
                log.error("error closing %s", c, exc_info=True)
        self.terminate_queue_threads()
        self.idle_add(self.clean)
        log("Protocol.close(%s) done", message)

    def steal_connection(self, read_callback:Optional[Callable]=None):
        #so we can re-use this connection somewhere else
        #(frees all protocol threads and resources)
        #Note: this method can only be used with non-blocking sockets,
        #and if more than one packet can arrive, the read_callback should be used
        #to ensure that no packets get lost.
        #The caller must call wait_for_io_threads_exit() to ensure that this
        #class is no longer reading from the connection before it can re-use it
        assert not self._closed, "cannot steal a closed connection"
        if read_callback:
            self._read_queue_put = read_callback
        conn = self._conn
        self._closed = True
        self._conn = None
        if conn:
            #this ensures that we exit the untilConcludes() read/write loop
            conn.set_active(False)
        self.terminate_queue_threads()
        return conn

    def clean(self) -> None:
        #clear all references to ensure we can get garbage collected quickly:
        self._get_packet_cb = None
        self._encoder = None
        self._write_thread = None
        self._read_thread = None
        self._read_parser_thread = None
        self._write_format_thread = None
        self._process_packet_cb = None
        self._process_read = None
        self._read_queue_put = None
        self._compress = None
        self._write_lock = None
        self._source_has_more = None
        self._conn = None       #should be redundant
        self.source_has_more = noop


    def terminate_queue_threads(self) -> None:
        log("terminate_queue_threads()")
        #the format thread will exit:
        self._get_packet_cb = None
        self._source_has_more.set()
        #make all the queue based threads exit by adding the empty marker:
        #write queue:
        owq = self._write_queue
        self._write_queue = exit_queue()
        force_flush_queue(owq)
        #read queue:
        orq = self._read_queue
        self._read_queue = exit_queue()
        force_flush_queue(orq)
        #just in case the read thread is waiting again:
        self._source_has_more.set()
