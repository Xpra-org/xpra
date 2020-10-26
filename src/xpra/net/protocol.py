# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods it's threads

# but it works on win32, for whatever that's worth.

import os
from socket import error as socket_error
from threading import Lock, Event
from queue import Queue

from xpra.os_util import memoryview_to_bytes, strtobytes, bytestostr, hexstr
from xpra.util import repr_ellipsized, ellipsizer, csv, envint, envbool, typedict, nonl
from xpra.make_thread import make_thread, start_thread
from xpra.net.common import ConnectionClosedException,may_log_packet    #@UndefinedVariable (pydev false positive)
from xpra.net.bytestreams import ABORT
from xpra.net import compression
from xpra.net.compression import (
    decompress, sanity_checks as compression_sanity_checks,
    InvalidCompressionException, Compressed, LevelCompressed, Compressible, LargeStructure,
    )
from xpra.net import packet_encoding
from xpra.net.socket_util import guess_header_protocol
from xpra.net.packet_encoding import (
    decode, sanity_checks as packet_encoding_sanity_checks,
    InvalidPacketEncodingException,
    )
from xpra.net.header import unpack_header, pack_header, FLAGS_CIPHER, FLAGS_NOHEADER, HEADER_SIZE
from xpra.net.crypto import get_encryptor, get_decryptor, pad, INITIAL_PADDING
from xpra.log import Logger

log = Logger("network", "protocol")
cryptolog = Logger("network", "crypto")


USE_ALIASES = envbool("XPRA_USE_ALIASES", True)
READ_BUFFER_SIZE = envint("XPRA_READ_BUFFER_SIZE", 65536)
#merge header and packet if packet is smaller than:
PACKET_JOIN_SIZE = envint("XPRA_PACKET_JOIN_SIZE", READ_BUFFER_SIZE)
LARGE_PACKET_SIZE = envint("XPRA_LARGE_PACKET_SIZE", 4096)
LOG_RAW_PACKET_SIZE = envbool("XPRA_LOG_RAW_PACKET_SIZE", False)
#inline compressed data in packet if smaller than:
INLINE_SIZE = envint("XPRA_INLINE_SIZE", 32768)
FAKE_JITTER = envint("XPRA_FAKE_JITTER", 0)
MIN_COMPRESS_SIZE = envint("XPRA_MIN_COMPRESS_SIZE", 378)
SEND_INVALID_PACKET = envint("XPRA_SEND_INVALID_PACKET", 0)
SEND_INVALID_PACKET_DATA = strtobytes(os.environ.get("XPRA_SEND_INVALID_PACKET_DATA", b"ZZinvalid-packetZZ"))


def sanity_checks():
    """ warns the user if important modules are missing """
    compression_sanity_checks()
    packet_encoding_sanity_checks()


def exit_queue():
    queue = Queue()
    for _ in range(10):     #just 2 should be enough!
        queue.put(None)
    return queue

def force_flush_queue(q):
    try:
        #discard all elements in the old queue and push the None marker:
        try:
            while q.qsize()>0:
                q.read(False)
        except Exception:
            pass
        q.put_nowait(None)
    except Exception:
        pass


def verify_packet(packet):
    """ look for None values which may have caused the packet to fail encoding """
    if not isinstance(packet, list):
        return False
    assert packet, "invalid packet: %s" % packet
    tree = ["'%s' packet" % packet[0]]
    return do_verify_packet(tree, packet)

def do_verify_packet(tree, packet):
    def err(msg):
        log.error("%s in %s", msg, "->".join(tree))
    def new_tree(append):
        nt = tree[:]
        nt.append(append)
        return nt
    if packet is None:
        err("None value")
        return False
    r = True
    if isinstance(packet, (list, tuple)):
        for i, x in enumerate(packet):
            if not do_verify_packet(new_tree("[%s]" % i), x):
                r = False
    elif isinstance(packet, dict):
        for k,v in packet.items():
            if not do_verify_packet(new_tree("key for value='%s'" % str(v)), k):
                r = False
            if not do_verify_packet(new_tree("value for key='%s'" % str(k)), v):
                r = False
    elif isinstance(packet, (int, bool, str, bytes)):
        pass
    else:
        err("unsupported type: %s" % type(packet))
        r = False
    return r


class Protocol:
    """
        This class handles sending and receiving packets,
        it will encode and compress them before sending,
        and decompress and decode when receiving.
    """

    CONNECTION_LOST = "connection-lost"
    GIBBERISH = "gibberish"
    INVALID = "invalid"

    TYPE = "xpra"

    def __init__(self, scheduler, conn, process_packet_cb, get_packet_cb=None):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert scheduler is not None
        assert conn is not None
        self.timeout_add = scheduler.timeout_add
        self.idle_add = scheduler.idle_add
        self.source_remove = scheduler.source_remove
        self.read_buffer_size = READ_BUFFER_SIZE
        self.hangup_delay = 1000
        self._conn = conn
        if FAKE_JITTER>0:   # pragma: no cover
            from xpra.net.fake_jitter import FakeJitter
            fj = FakeJitter(self.timeout_add, process_packet_cb, FAKE_JITTER)
            self._process_packet_cb =  fj.process_packet_cb
        else:
            self._process_packet_cb = process_packet_cb
        self.make_chunk_header = self.make_xpra_header
        self.make_frame_header = self.noframe_header
        self._write_queue = Queue(1)
        self._read_queue = Queue(20)
        self._process_read = self.read_queue_put
        self._read_queue_put = self.read_queue_put
        # Invariant: if .source is None, then _source_has_more == False
        self._get_packet_cb = get_packet_cb
        #counters:
        self.input_stats = {}
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_stats = {}
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        #initial value which may get increased by client/server after handshake:
        self.max_packet_size = 16*1024*1024
        self.abs_max_packet_size = 256*1024*1024
        self.large_packets = [b"hello", b"window-metadata", b"sound-data", b"notify_show", b"setting-change"]
        self.send_aliases = {}
        self.receive_aliases = {}
        self._log_stats = None          #None here means auto-detect
        self._closed = False
        self.encoder = "none"
        self._encoder = self.noencode
        self.compressor = "none"
        self._compress = compression.nocompress
        self.compression_level = 0
        self.cipher_in = None
        self.cipher_in_name = None
        self.cipher_in_block_size = 0
        self.cipher_in_padding = INITIAL_PADDING
        self.cipher_out = None
        self.cipher_out_name = None
        self.cipher_out_block_size = 0
        self.cipher_out_padding = INITIAL_PADDING
        self._write_lock = Lock()
        self._write_thread = None
        self._read_thread = make_thread(self._read_thread_loop, "read", daemon=True)
        self._read_parser_thread = None         #started when needed
        self._write_format_thread = None        #started when needed
        self._source_has_more = Event()

    STATE_FIELDS = ("max_packet_size", "large_packets", "send_aliases", "receive_aliases",
                    "cipher_in", "cipher_in_name", "cipher_in_block_size", "cipher_in_padding",
                    "cipher_out", "cipher_out_name", "cipher_out_block_size", "cipher_out_padding",
                    "compression_level", "encoder", "compressor")

    def save_state(self):
        state = {}
        for x in Protocol.STATE_FIELDS:
            state[x] = getattr(self, x)
        return state

    def restore_state(self, state):
        assert state is not None
        for x in Protocol.STATE_FIELDS:
            assert x in state, "field %s is missing" % x
            setattr(self, x, state[x])
        #special handling for compressor / encoder which are named objects:
        self.enable_compressor(self.compressor)
        self.enable_encoder(self.encoder)


    def is_closed(self) -> bool:
        return self._closed


    def wait_for_io_threads_exit(self, timeout=None):
        io_threads = [x for x in (self._read_thread, self._write_thread) if x is not None]
        for t in io_threads:
            if t.isAlive():
                t.join(timeout)
        exited = True
        cinfo = self._conn or "cleared connection"
        for t in io_threads:
            if t.isAlive():
                log.warn("Warning: %s thread of %s is still alive (timeout=%s)", t.name, cinfo, timeout)
                exited = False
        return exited

    def set_packet_source(self, get_packet_cb):
        self._get_packet_cb = get_packet_cb


    def set_cipher_in(self, ciphername, iv, password, key_salt, iterations, padding):
        cryptolog("set_cipher_in%s", (ciphername, iv, password, key_salt, iterations))
        self.cipher_in, self.cipher_in_block_size = get_decryptor(ciphername, iv, password, key_salt, iterations)
        self.cipher_in_padding = padding
        if self.cipher_in_name!=ciphername:
            cryptolog.info("receiving data using %s encryption", ciphername)
            self.cipher_in_name = ciphername

    def set_cipher_out(self, ciphername, iv, password, key_salt, iterations, padding):
        cryptolog("set_cipher_out%s", (ciphername, iv, password, key_salt, iterations, padding))
        self.cipher_out, self.cipher_out_block_size = get_encryptor(ciphername, iv, password, key_salt, iterations)
        self.cipher_out_padding = padding
        if self.cipher_out_name!=ciphername:
            cryptolog.info("sending data using %s encryption", ciphername)
            self.cipher_out_name = ciphername


    def __repr__(self):
        return "Protocol(%s)" % self._conn

    def get_threads(self):
        return tuple(x for x in (
            self._write_thread,
            self._read_thread,
            self._read_parser_thread,
            self._write_format_thread,
            ) if x is not None)

    def accept(self):
        pass

    def parse_remote_caps(self, caps : typedict):
        for k,v in caps.dictget("aliases", {}).items():
            self.send_aliases[bytestostr(k)] = v

    def get_info(self, alias_info=True) -> dict:
        info = {
            "large_packets"         : tuple(bytestostr(x) for x in self.large_packets),
            "compression_level"     : self.compression_level,
            "max_packet_size"       : self.max_packet_size,
            "aliases"               : USE_ALIASES,
            }
        c = self._compress
        if c:
            info["compressor"] = compression.get_compressor_name(self._compress)
        e = self._encoder
        if e:
            if self._encoder==self.noencode:        #pylint: disable=comparison-with-callable
                info["encoder"] = "noencode"
            else:
                info["encoder"] = packet_encoding.get_encoder_name(self._encoder)
        if alias_info:
            info["send_alias"] = self.send_aliases
            info["receive_alias"] = self.receive_aliases
        c = self._conn
        if c:
            try:
                info.update(self._conn.get_info())
            except Exception:
                log.error("error collecting connection information on %s", self._conn, exc_info=True)
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
        shm = self._source_has_more
        info["has_more"] = shm and shm.is_set()
        for t in (self._write_thread, self._read_thread, self._read_parser_thread, self._write_format_thread):
            if t:
                info.setdefault("thread", {})[t.name] = t.is_alive()
        return info


    def start(self):
        def start_network_read_thread():
            if not self._closed:
                self._read_thread.start()
        self.idle_add(start_network_read_thread)
        if SEND_INVALID_PACKET:
            self.timeout_add(SEND_INVALID_PACKET*1000, self.raw_write, "invalid", SEND_INVALID_PACKET_DATA)


    def send_disconnect(self, reasons, done_callback=None):
        self.flush_then_close(["disconnect"]+list(reasons), done_callback=done_callback)

    def send_now(self, packet):
        if self._closed:
            log("send_now(%s ...) connection is closed already, not sending", packet[0])
            return
        log("send_now(%s ...)", packet[0])
        if self._get_packet_cb:
            raise Exception("cannot use send_now when a packet source exists! (set to %s)" % self._get_packet_cb)
        tmp_queue = [packet]
        def packet_cb():
            self._get_packet_cb = None
            if not tmp_queue:
                raise Exception("packet callback used more than once!")
            packet = tmp_queue.pop()
            return (packet, )
        self._get_packet_cb = packet_cb
        self.source_has_more()

    def source_has_more(self):      #pylint: disable=method-hidden
        shm = self._source_has_more
        if not shm or self._closed:
            return
        shm.set()
        #start the format thread:
        if not self._write_format_thread and not self._closed:
            self._write_format_thread = make_thread(self._write_format_thread_loop, "format", daemon=True)
            self._write_format_thread.start()
        #from now on, take shortcut:
        self.source_has_more = self._source_has_more.set

    def _write_format_thread_loop(self):
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

    def _add_packet_to_queue(self, packet, start_send_cb=None, end_send_cb=None, fail_cb=None, synchronous=True, has_more=False, wait_for_more=False):
        if not has_more:
            shm = self._source_has_more
            if shm:
                shm.clear()
        if packet is None:
            return
        #log("add_packet_to_queue(%s ... %s, %s, %s)", packet[0], synchronous, has_more, wait_for_more)
        packet_type = packet[0]
        chunks = self.encode(packet)
        with self._write_lock:
            if self._closed:
                return
            try:
                self._add_chunks_to_queue(packet_type, chunks, start_send_cb, end_send_cb, fail_cb, synchronous, has_more or wait_for_more)
            except:
                log.error("Error: failed to queue '%s' packet", packet[0])
                log("add_chunks_to_queue%s", (chunks, start_send_cb, end_send_cb, fail_cb), exc_info=True)
                raise

    def _add_chunks_to_queue(self, packet_type, chunks, start_send_cb=None, end_send_cb=None, fail_cb=None, synchronous=True, more=False):
        """ the write_lock must be held when calling this function """
        items = []
        for proto_flags,index,level,data in chunks:
            payload_size = len(data)
            actual_size = payload_size
            if self.cipher_out:
                proto_flags |= FLAGS_CIPHER
                #note: since we are padding: l!=len(data)
                padding_size = self.cipher_out_block_size - (payload_size % self.cipher_out_block_size)
                if padding_size==0:
                    padded = data
                else:
                    # pad byte value is number of padding bytes added
                    padded = memoryview_to_bytes(data) + pad(self.cipher_out_padding, padding_size)
                    actual_size += padding_size
                assert len(padded)==actual_size, "expected padded size to be %i, but got %i" % (len(padded), actual_size)
                data = self.cipher_out.encrypt(padded)
                assert len(data)==actual_size, "expected encrypted size to be %i, but got %i" % (len(data), actual_size)
                cryptolog("sending %s bytes %s encrypted with %s padding",
                          payload_size, self.cipher_out_name, padding_size)
            if proto_flags & FLAGS_NOHEADER:
                assert not self.cipher_out
                #for plain/text packets (ie: gibberish response)
                log("sending %s bytes without header", payload_size)
                items.append(data)
            else:
                #the xpra packet header:
                #(WebSocketProtocol may also add a websocket header too)
                header = self.make_chunk_header(packet_type, proto_flags, level, index, payload_size, actual_size)
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
        self.raw_write(packet_type, items, start_send_cb, end_send_cb, fail_cb, synchronous, more)

    def make_xpra_header(self, _packet_type, proto_flags, level, index, payload_size, actual_size) -> bytes:
        return pack_header(proto_flags, level, index, payload_size)

    def noframe_header(self, _packet_type, _items):
        return None


    def start_write_thread(self):
        self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def raw_write(self, packet_type, items, start_cb=None, end_cb=None, fail_cb=None, synchronous=True, more=False):
        """ Warning: this bypasses the compression and packet encoder! """
        if self._write_thread is None:
            self.start_write_thread()
        self._write_queue.put((items, start_cb, end_cb, fail_cb, synchronous, more))


    def enable_default_encoder(self):
        opts = packet_encoding.get_enabled_encoders()
        assert opts, "no packet encoders available!"
        self.enable_encoder(opts[0])

    def enable_encoder_from_caps(self, caps):
        opts = packet_encoding.get_enabled_encoders(order=packet_encoding.PERFORMANCE_ORDER)
        log("enable_encoder_from_caps(..) options=%s", opts)
        for e in opts:
            if caps.boolget(e, e=="bencode"):
                self.enable_encoder(e)
                return True
        log.error("no matching packet encoder found!")
        return False

    def enable_encoder(self, e):
        self._encoder = packet_encoding.get_encoder(e)
        self.encoder = e
        log("enable_encoder(%s): %s", e, self._encoder)


    def enable_default_compressor(self):
        opts = compression.get_enabled_compressors()
        if opts:
            self.enable_compressor(opts[0])
        else:
            self.enable_compressor("none")

    def enable_compressor_from_caps(self, caps):
        if self.compression_level==0:
            self.enable_compressor("none")
            return
        opts = compression.get_enabled_compressors(order=compression.PERFORMANCE_ORDER)
        log("enable_compressor_from_caps(..) options=%s", opts)
        for c in opts:      #ie: [zlib, lz4, lzo]
            if caps.boolget(c):
                self.enable_compressor(c)
                return
        log.warn("compression disabled: no matching compressor found")
        self.enable_compressor("none")

    def enable_compressor(self, compressor):
        self._compress = compression.get_compressor(compressor)
        self.compressor = compressor
        log("enable_compressor(%s): %s", compressor, self._compress)


    def noencode(self, data):
        #just send data as a string for clients that don't understand xpra packet format:
        import codecs
        def b(x):
            if isinstance(x, bytes):
                return x
            return codecs.latin_1_encode(x)[0]
        return b(": ".join(str(x) for x in data)+"\n"), FLAGS_NOHEADER


    def encode(self, packet_in):
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
        packets = []
        packet = list(packet_in)
        level = self.compression_level
        size_check = LARGE_PACKET_SIZE
        min_comp_size = MIN_COMPRESS_SIZE
        for i in range(1, len(packet)):
            item = packet[i]
            if item is None:
                raise TypeError("invalid None value in %s packet at index %s" % (packet[0], i))
            ti = type(item)
            if ti in (int, bool, dict, list, tuple):
                continue
            try:
                l = len(item)
            except TypeError as e:
                raise TypeError("invalid type %s in %s packet at index %s: %s" % (ti, packet[0], i, e))
            if ti==LargeStructure:
                item = item.data
                packet[i] = item
                ti = type(item)
                continue
            elif ti==Compressible:
                #this is a marker used to tell us we should compress it now
                #(used by the client for clipboard data)
                item = item.compress()
                packet[i] = item
                ti = type(item)
                #(it may now be a "Compressed" item and be processed further)
            if ti in (Compressed, LevelCompressed):
                #already compressed data (usually pixels, cursors, etc)
                if not item.can_inline or l>INLINE_SIZE:
                    il = 0
                    if ti==LevelCompressed:
                        #unlike Compressed (usually pixels, decompressed in the paint thread),
                        #LevelCompressed is decompressed by the network layer
                        #so we must tell it how to do that and pass the level flag
                        il = item.level
                    packets.append((0, i, il, item.data))
                    packet[i] = b''
                else:
                    #data is small enough, inline it:
                    packet[i] = item.data
                    min_comp_size += l
                    size_check += l
            elif ti==bytes and level>0 and l>LARGE_PACKET_SIZE:
                log.warn("Warning: found a large uncompressed item")
                log.warn(" in packet '%s' at position %i: %s bytes", packet[0], i, len(item))
                #add new binary packet with large item:
                cl, cdata = self._compress(item, level)
                packets.append((0, i, cl, cdata))
                #replace this item with an empty string placeholder:
                packet[i] = ''
            elif ti not in (str, bytes):
                log.warn("Warning: unexpected data type %s", ti)
                log.warn(" in '%s' packet at position %i: %s", packet[0], i, repr_ellipsized(item))
        #now the main packet (or what is left of it):
        packet_type = packet[0]
        self.output_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
        if USE_ALIASES:
            alias = self.send_aliases.get(packet_type)
            if alias:
                #replace the packet type with the alias:
                packet[0] = alias
            else:
                log("packet type send alias not found for '%s'", packet_type)
        try:
            main_packet, proto_flags = self._encoder(packet)
        except Exception:
            if self._closed:
                return [], 0
            log.error("Error: failed to encode packet: %s", packet, exc_info=True)
            #make the error a bit nicer to parse: undo aliases:
            packet[0] = packet_type
            verify_packet(packet)
            raise
        if len(main_packet)>size_check and strtobytes(packet_in[0]) not in self.large_packets:
            log.warn("Warning: found large packet")
            log.warn(" '%s' packet is %s bytes: ", packet_type, len(main_packet))
            log.warn(" argument types: %s", csv(type(x) for x in packet[1:]))
            log.warn(" sizes: %s", csv(len(strtobytes(x)) for x in packet[1:]))
            log.warn(" packet: %s", repr_ellipsized(packet))
        #compress, but don't bother for small packets:
        if level>0 and len(main_packet)>min_comp_size:
            try:
                cl, cdata = self._compress(main_packet, level)
            except Exception as e:
                log.error("Error compressing '%s' packet", packet_type)
                log.error(" %s", e)
                raise
            packets.append((proto_flags, 0, cl, cdata))
        else:
            packets.append((proto_flags, 0, 0, main_packet))
        may_log_packet(True, packet_type, packet)
        return packets

    def set_compression_level(self, level : int):
        #this may be used next time encode() is called
        assert 0<=level<=10, "invalid compression level: %s (must be between 0 and 10" % level
        self.compression_level = level


    def _io_thread_loop(self, name, callback):
        try:
            log("io_thread_loop(%s, %s) loop starting", name, callback)
            while not self._closed and callback():
                pass
            log("io_thread_loop(%s, %s) loop ended, closed=%s", name, callback, self._closed)
        except ConnectionClosedException:
            log("%s closed", self._conn, exc_info=True)
            if not self._closed:
                #ConnectionClosedException means the warning has been logged already
                self._connection_lost("%s connection %s closed" % (name, self._conn))
        except (OSError, socket_error) as e:
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
        items = self._write_queue.get()
        # Used to signal that we should exit:
        if items is None:
            log("write thread: empty marker, exiting")
            self.close()
            return False
        return self.write_items(*items)

    def write_items(self, buf_data, start_cb=None, end_cb=None, fail_cb=None, synchronous=True, more=False):
        conn = self._conn
        if not conn:
            return False
        if more or len(buf_data)>1:
            conn.set_nodelay(False)
        if len(buf_data)>1:
            conn.set_cork(True)
        if start_cb:
            try:
                start_cb(conn.output_bytecount)
            except Exception:
                if not self._closed:
                    log.error("Error on write start callback %s", start_cb, exc_info=True)
        self.write_buffers(buf_data, fail_cb, synchronous)
        if len(buf_data)>1:
            conn.set_cork(False)
        if not more:
            conn.set_nodelay(True)
        if end_cb:
            try:
                end_cb(self._conn.output_bytecount)
            except Exception:
                if not self._closed:
                    log.error("Error on write end callback %s", end_cb, exc_info=True)
        return True

    def write_buffers(self, buf_data, _fail_cb, _synchronous):
        con = self._conn
        if not con:
            return
        for buf in buf_data:
            while buf and not self._closed:
                written = self.con_write(con, buf)
                #example test code, for sending small chunks very slowly:
                #written = con.write(buf[:1024])
                #import time
                #time.sleep(0.05)
                if written:
                    buf = buf[written:]
                    self.output_raw_packetcount += 1
        self.output_packetcount += 1

    def con_write(self, con, buf):
        return con.write(buf)


    def _read_thread_loop(self):
        self._io_thread_loop("read", self._read)
    def _read(self):
        buf = self._conn.read(self.read_buffer_size)
        #log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
        #add to the read queue (or whatever takes its place - see steal_connection)
        self._process_read(buf)
        if not buf:
            log("read thread: eof")
            #give time to the parse thread to call close itself
            #so it has time to parse and process the last packet received
            self.timeout_add(1000, self.close)
            return False
        self.input_raw_packetcount += 1
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
            exc = None
        self.idle_add(self._connection_lost, message)

    def _connection_lost(self, message="", exc_info=False):
        log("connection lost: %s", message, exc_info=exc_info)
        self.close()
        return False


    def invalid(self, msg, data):
        self.idle_add(self._process_packet_cb, self, [Protocol.INVALID, msg, data])
        # Then hang up:
        self.timeout_add(1000, self._connection_lost, msg)

    def gibberish(self, msg, data):
        self.idle_add(self._process_packet_cb, self, [Protocol.GIBBERISH, msg, data])
        # Then hang up:
        self.timeout_add(self.hangup_delay, self._connection_lost, msg)


    #delegates to invalid_header()
    #(so this can more easily be intercepted and overriden
    # see tcp-proxy)
    def invalid_header(self, proto, data, msg="invalid packet header"):
        self._invalid_header(proto, data, msg)

    def _invalid_header(self, proto, data, msg=""):
        log("invalid_header(%s, %s bytes: '%s', %s)",
               proto, len(data or ""), msg, ellipsizer(data))
        guess = guess_header_protocol(data)
        if guess[0]:
            err = "invalid packet format, %s" % guess[1]
        else:
            err = "%s: '%s'" % (msg, hexstr(data[:HEADER_SIZE]))
            if len(data)>1:
                err += " read buffer=%s (%i bytes)" % (repr_ellipsized(data), len(data))
        self.gibberish(err, data)


    def process_read(self, data):
        self._read_queue_put(data)

    def read_queue_put(self, data):
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

    def start_read_parser_thread(self):
        self._read_parser_thread = start_thread(self._read_parse_thread_loop, "parse", daemon=True)

    def _read_parse_thread_loop(self):
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
        compression_level = 0
        raw_packets = {}
        while not self._closed:
            buf = self._read_queue.get()
            if not buf:
                log("parse thread: empty marker, exiting")
                self.idle_add(self.close)
                return

            read_buffers.append(buf)
            while read_buffers:
                #have we read the header yet?
                if payload_size<0:
                    #try to handle the first buffer:
                    buf = read_buffers[0]
                    if not header and buf[0]!=ord("P"):
                        self.invalid_header(self, buf, "invalid packet header byte %s" % nonl(bytestostr(buf)))
                        return
                    #how much to we need to slice off to complete the header:
                    read = min(len(buf), HEADER_SIZE-len(header))
                    header += memoryview_to_bytes(buf[:read])
                    if len(header)<HEADER_SIZE:
                        #need to process more buffers to get a full header:
                        read_buffers.pop(0)
                        continue
                    elif len(buf)>read:
                        #got the full header and more, keep the rest of the packet:
                        read_buffers[0] = buf[read:]
                    else:
                        #we only got the header:
                        assert len(buf)==read
                        read_buffers.pop(0)
                        continue
                    #parse the header:
                    # format: struct.pack(b'cBBBL', ...) - HEADER_SIZE bytes
                    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(header)

                    #sanity check size (will often fail if not an xpra client):
                    if data_size>self.abs_max_packet_size:
                        self.invalid_header(self, header, "invalid size in packet header: %s" % data_size)
                        return

                    if protocol_flags & FLAGS_CIPHER:
                        if self.cipher_in_block_size==0 or not self.cipher_in_name:
                            cryptolog.warn("Warning: received cipher block,")
                            cryptolog.warn(" but we don't have a cipher to decrypt it with,")
                            cryptolog.warn(" not an xpra client?")
                            self.invalid_header(self, header, "invalid encryption packet flag (no cipher configured)")
                            return
                        padding_size = self.cipher_in_block_size - (data_size % self.cipher_in_block_size)
                        payload_size = data_size + padding_size
                    else:
                        #no cipher, no padding:
                        padding_size = 0
                        payload_size = data_size
                    assert payload_size>0, "invalid payload size: %i" % payload_size

                    if payload_size>self.max_packet_size:
                        #this packet is seemingly too big, but check again from the main UI thread
                        #this gives 'set_max_packet_size' a chance to run from "hello"
                        def check_packet_size(size_to_check, packet_header):
                            if self._closed:
                                return False
                            log("check_packet_size(%#x, %s) max=%#x",
                                size_to_check, hexstr(packet_header), self.max_packet_size)
                            if size_to_check>self.max_packet_size:
                                msg = "packet size requested is %s but maximum allowed is %s" % \
                                              (size_to_check, self.max_packet_size)
                                self.invalid(msg, packet_header)
                            return False
                        self.timeout_add(1000, check_packet_size, payload_size, header)

                #how much data do we have?
                bl = sum(len(v) for v in read_buffers)
                if bl<payload_size:
                    # incomplete packet, wait for the rest to arrive
                    break

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
                    data = self.cipher_in.decrypt(data)
                    if padding_size > 0:
                        def debug_str(s):
                            try:
                                return hexstr(bytearray(s))
                            except Exception:
                                return csv(tuple(s))
                        # pad byte value is number of padding bytes added
                        padtext = pad(self.cipher_in_padding, padding_size)
                        if data.endswith(padtext):
                            cryptolog("found %s %s padding", self.cipher_in_padding, self.cipher_in_name)
                        else:
                            actual_padding = data[-padding_size:]
                            cryptolog.warn("Warning: %s decryption failed: invalid padding", self.cipher_in_name)
                            cryptolog(" data does not end with %s padding bytes %s",
                                      self.cipher_in_padding, debug_str(padtext))
                            cryptolog(" but with %s (%s)", debug_str(actual_padding), type(data))
                            cryptolog(" decrypted data: %s", debug_str(data[:128]))
                            self._internal_error("%s encryption padding error - wrong key?" % self.cipher_in_name)
                            return
                        data = data[:-padding_size]
                #uncompress if needed:
                if compression_level>0:
                    try:
                        data = decompress(data, compression_level)
                    except InvalidCompressionException as e:
                        self.invalid("invalid compression: %s" % e, data)
                        return
                    except Exception as e:
                        ctype = compression.get_compression_type(compression_level)
                        log("%s packet decompression failed", ctype, exc_info=True)
                        msg = "%s packet decompression failed" % ctype
                        if self.cipher_in:
                            msg += " (invalid encryption key?)"
                        else:
                            #only include the exception text when not using encryption
                            #as this may leak crypto information:
                            msg += " %s" % e
                        del e
                        self.gibberish(msg, data)
                        return

                if self._closed:
                    return

                #we're processing this packet,
                #make sure we get a new header next time
                header = b""
                if packet_index>0:
                    #raw packet, store it and continue:
                    raw_packets[packet_index] = data
                    payload_size = -1
                    if len(raw_packets)>=4:
                        self.invalid("too many raw packets: %s" % len(raw_packets), data)
                        return
                    continue
                #final packet (packet_index==0), decode it:
                try:
                    packet = decode(data, protocol_flags)
                except InvalidPacketEncodingException as e:
                    self.invalid("invalid packet encoding: %s" % e, data)
                    return
                except ValueError as e:
                    etype = packet_encoding.get_packet_encoding_type(protocol_flags)
                    log.error("Error parsing %s packet:", etype)
                    log.error(" %s", e)
                    if self._closed:
                        return
                    log("failed to parse %s packet: %s", etype, hexstr(data[:128]))
                    log(" %s", e)
                    log(" data: %s", repr_ellipsized(data))
                    log(" packet index=%i, packet size=%i, buffer size=%s", packet_index, payload_size, bl)
                    self.gibberish("failed to parse %s packet" % etype, data)
                    return

                if self._closed:
                    return
                payload_size = -1
                #add any raw packets back into it:
                if raw_packets:
                    for index,raw_data in raw_packets.items():
                        #replace placeholder with the raw_data packet data:
                        packet[index] = raw_data
                    raw_packets = {}

                packet_type = packet[0]
                if self.receive_aliases and isinstance(packet_type, int):
                    packet_type = self.receive_aliases.get(packet_type)
                    if packet_type:
                        packet[0] = packet_type
                self.input_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
                if LOG_RAW_PACKET_SIZE:
                    log("%s: %i bytes", packet_type, HEADER_SIZE + payload_size)

                self.input_packetcount += 1
                log("processing packet %s", bytestostr(packet_type))
                self._process_packet_cb(self, packet)
                packet = None

    def flush_then_close(self, last_packet, done_callback=None):    #pylint: disable=method-hidden
        """ Note: this is best effort only
            the packet may not get sent.

            We try to get the write lock,
            we try to wait for the write queue to flush
            we queue our last packet,
            we wait again for the queue to flush,
            then no matter what, we close the connection and stop the threads.
        """
        def closing_already(last_packet, done_callback=None):
            log("flush_then_close%s had already been called, this new request has been ignored",
                (last_packet, done_callback))
        self.flush_then_close = closing_already
        log("flush_then_close(%s, %s) closed=%s", last_packet, done_callback, self._closed)
        def done():
            log("flush_then_close: done, callback=%s", done_callback)
            if done_callback:
                done_callback()
        if self._closed:
            log("flush_then_close: already closed")
            done()
            return
        def wait_for_queue(timeout=10):
            #IMPORTANT: if we are here, we have the write lock held!
            if not self._write_queue.empty():
                #write queue still has stuff in it..
                if timeout<=0:
                    log("flush_then_close: queue still busy, closing without sending the last packet")
                    try:
                        self._write_lock.release()
                    except Exception:
                        pass
                    self.close()
                    done()
                else:
                    log("flush_then_close: still waiting for queue to flush")
                    self.timeout_add(100, wait_for_queue, timeout-1)
            else:
                log("flush_then_close: queue is now empty, sending the last packet and closing")
                chunks = self.encode(last_packet)
                def close_and_release():
                    log("flush_then_close: wait_for_packet_sent() close_and_release()")
                    self.close()
                    try:
                        self._write_lock.release()
                    except Exception:
                        pass
                    done()
                def wait_for_packet_sent():
                    log("flush_then_close: wait_for_packet_sent() queue.empty()=%s, closed=%s",
                        self._write_queue.empty(), self._closed)
                    if self._write_queue.empty() or self._closed:
                        #it got sent, we're done!
                        close_and_release()
                        return False
                    return not self._closed     #run until we manage to close (here or via the timeout)
                def packet_queued(*_args):
                    #if we're here, we have the lock and the packet is in the write queue
                    log("flush_then_close: packet_queued() closed=%s", self._closed)
                    if wait_for_packet_sent():
                        #check again every 100ms
                        self.timeout_add(100, wait_for_packet_sent)
                self._add_chunks_to_queue(last_packet[0], chunks,
                                          start_send_cb=None, end_send_cb=packet_queued,
                                          synchronous=False, more=False)
                #just in case wait_for_packet_sent never fires:
                self.timeout_add(5*1000, close_and_release)

        def wait_for_write_lock(timeout=100):
            wl = self._write_lock
            if not wl:
                #cleaned up already
                return
            if not wl.acquire(False):
                if timeout<=0:
                    log("flush_then_close: timeout waiting for the write lock")
                    self.close()
                    done()
                else:
                    log("flush_then_close: write lock is busy, will retry %s more times", timeout)
                    self.timeout_add(10, wait_for_write_lock, timeout-1)
            else:
                log("flush_then_close: acquired the write lock")
                #we have the write lock - we MUST free it!
                wait_for_queue()
        #normal codepath:
        # -> wait_for_write_lock
        # -> wait_for_queue
        # -> _add_chunks_to_queue
        # -> packet_queued
        # -> wait_for_packet_sent
        # -> close_and_release
        log("flush_then_close: wait_for_write_lock()")
        wait_for_write_lock()

    def close(self):
        log("Protocol.close() closed=%s, connection=%s", self._closed, self._conn)
        if self._closed:
            return
        self._closed = True
        self.idle_add(self._process_packet_cb, self, [Protocol.CONNECTION_LOST])
        c = self._conn
        if c:
            self._conn = None
            try:
                log("Protocol.close() calling %s", c.close)
                c.close()
                if self._log_stats is None and c.input_bytecount==0 and c.output_bytecount==0:
                    #no data sent or received, skip logging of stats:
                    self._log_stats = False
                if self._log_stats:
                    from xpra.simple_stats import std_unit, std_unit_dec
                    log.info("connection closed after %s packets received (%s bytes) and %s packets sent (%s bytes)",
                         std_unit(self.input_packetcount), std_unit_dec(c.input_bytecount),
                         std_unit(self.output_packetcount), std_unit_dec(c.output_bytecount)
                         )
            except Exception:
                log.error("error closing %s", c, exc_info=True)
        self.terminate_queue_threads()
        self.idle_add(self.clean)
        log("Protocol.close() done")

    def steal_connection(self, read_callback=None):
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

    def clean(self):
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
        def noop(): # pragma: no cover
            pass
        self.source_has_more = noop


    def terminate_queue_threads(self):
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
