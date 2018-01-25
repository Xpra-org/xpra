# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods it's threads

# but it works on win32, for whatever that's worth.

import os
from socket import error as socket_error
from threading import Lock, Event


from xpra.log import Logger
log = Logger("network", "protocol")
cryptolog = Logger("network", "crypto")

from xpra.os_util import PYTHON3, Queue, memoryview_to_bytes, strtobytes, hexstr
from xpra.util import repr_ellipsized, csv, envint, envbool
from xpra.make_thread import make_thread, start_thread
from xpra.net.common import ConnectionClosedException          #@UndefinedVariable (pydev false positive)
from xpra.net.bytestreams import ABORT
from xpra.net import compression
from xpra.net import packet_encoding
from xpra.net.compression import decompress, sanity_checks as compression_sanity_checks,\
        InvalidCompressionException, Compressed, LevelCompressed, Compressible, LargeStructure
from xpra.net.packet_encoding import decode, sanity_checks as packet_encoding_sanity_checks, InvalidPacketEncodingException
from xpra.net.header import unpack_header, pack_header, FLAGS_CIPHER, FLAGS_NOHEADER
from xpra.net.crypto import get_encryptor, get_decryptor, pad, INITIAL_PADDING


#stupid python version breakage:
JOIN_TYPES = (str, bytes)
if PYTHON3:
    long = int              #@ReservedAssignment
    unicode = str           #@ReservedAssignment
    JOIN_TYPES = (bytes, )


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
        except:
            pass
        q.put_nowait(None)
    except:
        pass


def verify_packet(packet):
    """ look for None values which may have caused the packet to fail encoding """
    if type(packet)!=list:
        return False
    assert len(packet)>0, "invalid packet: %s" % packet
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
    if type(packet) in (list, tuple):
        for i, x in enumerate(packet):
            if not do_verify_packet(new_tree("[%s]" % i), x):
                r = False
    elif type(packet)==dict:
        for k,v in packet.items():
            if not do_verify_packet(new_tree("key for value='%s'" % str(v)), k):
                r = False
            if not do_verify_packet(new_tree("value for key='%s'" % str(k)), v):
                r = False
    elif type(packet) in (int, bool, str, bytes):
        pass
    else:
        err("unsupported type: %s" % type(packet))
        r = False
    return r


class Protocol(object):
    """
        This class handles sending and receiving packets,
        it will encode and compress them before sending,
        and decompress and decode when receiving.
    """

    CONNECTION_LOST = "connection-lost"
    GIBBERISH = "gibberish"
    INVALID = "invalid"

    def __init__(self, scheduler, conn, process_packet_cb, get_packet_cb=None):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert scheduler is not None
        assert conn is not None
        self.timeout_add = scheduler.timeout_add
        self.idle_add = scheduler.idle_add
        self.source_remove = scheduler.source_remove
        self._conn = conn
        if FAKE_JITTER>0:
            from xpra.net.fake_jitter import FakeJitter
            fj = FakeJitter(self.timeout_add, process_packet_cb)
            self._process_packet_cb =  fj.process_packet_cb
        else:
            self._process_packet_cb = process_packet_cb
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
        self.max_packet_size = 256*1024
        self.abs_max_packet_size = 256*1024*1024
        self.large_packets = ["hello", "window-metadata", "sound-data", "notify_show"]
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
        if self.cipher_in_name!=ciphername:
            cryptolog.info("receiving data using %s encryption", ciphername)
            self.cipher_in_name = ciphername
        cryptolog("set_cipher_in%s", (ciphername, iv, password, key_salt, iterations))
        self.cipher_in, self.cipher_in_block_size = get_decryptor(ciphername, iv, password, key_salt, iterations)
        self.cipher_in_padding = padding

    def set_cipher_out(self, ciphername, iv, password, key_salt, iterations, padding):
        if self.cipher_out_name!=ciphername:
            cryptolog.info("sending data using %s encryption", ciphername)
            self.cipher_out_name = ciphername
        cryptolog("set_cipher_out%s", (ciphername, iv, password, key_salt, iterations, padding))
        self.cipher_out, self.cipher_out_block_size = get_encryptor(ciphername, iv, password, key_salt, iterations)
        self.cipher_out_padding = padding


    def __repr__(self):
        return "Protocol(%s)" % self._conn

    def get_threads(self):
        return  [x for x in [self._write_thread, self._read_thread, self._read_parser_thread, self._write_format_thread] if x is not None]

    def accept(self):
        pass


    def get_info(self, alias_info=True):
        info = {
            "large_packets"         : self.large_packets,
            "compression_level"     : self.compression_level,
            "max_packet_size"       : self.max_packet_size,
            "aliases"               : USE_ALIASES,
            "input" : {
                       "buffer-size"            : READ_BUFFER_SIZE,
                       "packetcount"            : self.input_packetcount,
                       "raw_packetcount"        : self.input_raw_packetcount,
                       "count"                  : self.input_stats,
                       "cipher"                 : {"": self.cipher_in_name or "",
                                                   "padding"        : self.cipher_in_padding,
                                                   },
                        },
            "output" : {
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
                        },
            }
        c = self._compress
        if c:
            info["compressor"] = compression.get_compressor_name(self._compress)
        e = self._encoder
        if e:
            if self._encoder==self.noencode:
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
            except:
                log.error("error collecting connection information on %s", self._conn, exc_info=True)
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
            self.timeout_add(SEND_INVALID_PACKET*1000, self.raw_write, SEND_INVALID_PACKET_DATA)


    def send_disconnect(self, reasons, done_callback=None):
        self.flush_then_close(["disconnect"]+list(reasons), done_callback=done_callback)

    def send_now(self, packet):
        if self._closed:
            log("send_now(%s ...) connection is closed already, not sending", packet[0])
            return
        log("send_now(%s ...)", packet[0])
        assert self._get_packet_cb==None, "cannot use send_now when a packet source exists! (set to %s)" % self._get_packet_cb
        tmp_queue = [packet]
        def packet_cb():
            self._get_packet_cb = None
            if not tmp_queue:
                raise Exception("packet callback used more than once!")
            packet = tmp_queue.pop()
            return (packet, )
        self._get_packet_cb = packet_cb
        self.source_has_more()

    def source_has_more(self):
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

    def _add_packet_to_queue(self, packet, start_send_cb=None, end_send_cb=None, fail_cb=None, synchronous=True, has_more=False):
        if not has_more:
            self._source_has_more.clear()
        if packet is None:
            return
        log("add_packet_to_queue(%s ...)", packet[0])
        chunks = self.encode(packet)
        with self._write_lock:
            if self._closed:
                return
            try:
                self._add_chunks_to_queue(chunks, start_send_cb, end_send_cb, fail_cb, synchronous)
            except:
                log.error("Error: failed to queue '%s' packet", packet[0])
                log("add_chunks_to_queue%s", (chunks, start_send_cb, end_send_cb, fail_cb), exc_info=True)
                raise

    def _add_chunks_to_queue(self, chunks, start_send_cb=None, end_send_cb=None, fail_cb=None, synchronous=True):
        """ the write_lock must be held when calling this function """
        counter = 0
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
                cryptolog("sending %s bytes %s encrypted with %s padding", payload_size, self.cipher_out_name, padding_size)
            if proto_flags & FLAGS_NOHEADER:
                assert not self.cipher_out
                #for plain/text packets (ie: gibberish response)
                log("sending %s bytes without header", payload_size)
                items.append(data)
            elif actual_size<PACKET_JOIN_SIZE:
                if not isinstance(data, JOIN_TYPES):
                    data = memoryview_to_bytes(data)
                header_and_data = pack_header(proto_flags, level, index, payload_size) + data
                items.append(header_and_data)
            else:
                header = pack_header(proto_flags, level, index, payload_size)
                items.append(header)
                items.append(data)
            counter += 1
        self.raw_write(items, start_send_cb, end_send_cb, fail_cb, synchronous)

    def start_write_thread(self):
        self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def raw_write(self, items, start_cb=None, end_cb=None, fail_cb=None, synchronous=True):
        """ Warning: this bypasses the compression and packet encoder! """
        if self._write_thread is None:
            self.start_write_thread()
        self._write_queue.put((items, start_cb, end_cb, fail_cb, synchronous))


    def enable_default_encoder(self):
        opts = packet_encoding.get_enabled_encoders()
        assert len(opts)>0, "no packet encoders available!"
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
        if len(opts)>0:
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
        if PYTHON3:
            import codecs
            def b(x):
                if type(x)==bytes:
                    return x
                return codecs.latin_1_encode(x)[0]
        else:
            def b(x):               #@DuplicatedSignature
                return x
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
            if ti in (int, long, bool, dict, list, tuple):
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
                    packet[i] = ''
                else:
                    #data is small enough, inline it:
                    packet[i] = item.data
                    min_comp_size += l
                    size_check += l
            elif ti in (str, bytes) and level>0 and l>LARGE_PACKET_SIZE:
                log.warn("found a large uncompressed item in packet '%s' at position %s: %s bytes", packet[0], i, len(item))
                #add new binary packet with large item:
                cl, cdata = self._compress(item, level)
                packets.append((0, i, cl, cdata))
                #replace this item with an empty string placeholder:
                packet[i] = ''
            elif ti not in (str, bytes):
                log.warn("unexpected data type %s in %s packet: %s", ti, packet[0], repr_ellipsized(item))
        #now the main packet (or what is left of it):
        packet_type = packet[0]
        self.output_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
        if USE_ALIASES and self.send_aliases and packet_type in self.send_aliases:
            #replace the packet type with the alias:
            packet[0] = self.send_aliases[packet_type]
        try:
            main_packet, proto_flags = self._encoder(packet)
        except Exception:
            if self._closed:
                return [], 0
            log.error("failed to encode packet: %s", packet, exc_info=True)
            #make the error a bit nicer to parse: undo aliases:
            packet[0] = packet_type
            verify_packet(packet)
            raise
        if len(main_packet)>size_check and packet_in[0] not in self.large_packets:
            log.warn("found large packet (%s bytes): %s, argument types:%s, sizes: %s, packet head=%s",
                     len(main_packet), packet_in[0], [type(x) for x in packet[1:]], [len(str(x)) for x in packet[1:]], repr_ellipsized(packet))
        #compress, but don't bother for small packets:
        if level>0 and len(main_packet)>min_comp_size:
            cl, cdata = self._compress(main_packet, level)
            packets.append((proto_flags, 0, cl, cdata))
        else:
            packets.append((proto_flags, 0, 0, main_packet))
        return packets

    def set_compression_level(self, level):
        #this may be used next time encode() is called
        assert level>=0 and level<=10, "invalid compression level: %s (must be between 0 and 10" % level
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
        items = self._write_queue.get()
        # Used to signal that we should exit:
        if items is None:
            log("write thread: empty marker, exiting")
            self.close()
            return False
        return self.write_items(*items)

    def write_items(self, buf_data, start_cb=None, end_cb=None, fail_cb=None, synchronous=True):
        con = self._conn
        if not con:
            return False
        if start_cb:
            try:
                start_cb(con.output_bytecount)
            except:
                if not self._closed:
                    log.error("Error on write start callback %s", start_cb, exc_info=True)
        self.write_buffers(buf_data, fail_cb, synchronous)
        if end_cb:
            try:
                end_cb(self._conn.output_bytecount)
            except:
                if not self._closed:
                    log.error("Error on write end callback %s", end_cb, exc_info=True)
        return True

    def write_buffers(self, buf_data, _fail_cb, _synchronous):
        con = self._conn
        if not con:
            return 0
        for buf in buf_data:
            while buf and not self._closed:
                written = con.write(buf)
                #example test code, for sending small chunks very slowly:
                #written = con.write(buf[:1024])
                #import time
                #time.sleep(0.05)
                if written:
                    buf = buf[written:]
                    self.output_raw_packetcount += 1
        self.output_packetcount += 1


    def _read_thread_loop(self):
        self._io_thread_loop("read", self._read)
    def _read(self):
        buf = self._conn.read(READ_BUFFER_SIZE)
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
        self.timeout_add(1000, self._connection_lost, msg)


    #delegates to invalid_header()
    #(so this can more easily be intercepted and overriden
    # see tcp-proxy)
    def _invalid_header(self, data, msg=""):
        self.invalid_header(self, data, msg)

    def invalid_header(self, _proto, data, msg="invalid packet header"):
        err = "%s: '%s'" % (msg, hexstr(data[:8]))
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
        if self._read_queue_put==self.read_queue_put:
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
        read_buffer = None
        packet_size = 0
        payload_size = -1
        padding_size = 0
        packet_index = 0
        compression_level = False
        packet = None
        raw_packets = {}
        while not self._closed:
            buf = self._read_queue.get()
            if not buf:
                log("parse thread: empty marker, exiting")
                self.idle_add(self.close)
                return
            if read_buffer:
                read_buffer = read_buffer + buf
            else:
                read_buffer = buf
            bl = len(read_buffer)
            while not self._closed:
                packet = None
                bl = len(read_buffer)
                if bl<=0:
                    break
                if payload_size<0:
                    if read_buffer[0] not in ("P", ord("P")):
                        self._invalid_header(read_buffer, "invalid packet header byte %s" % read_buffer[0])
                        return
                    if bl<8:
                        break   #packet still too small
                    #packet format: struct.pack('cBBBL', ...) - 8 bytes
                    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(read_buffer[:8])

                    #sanity check size (will often fail if not an xpra client):
                    if data_size>self.abs_max_packet_size:
                        self._invalid_header(read_buffer, "invalid size in packet header: %s" % data_size)
                        return

                    bl = len(read_buffer)-8
                    if protocol_flags & FLAGS_CIPHER:
                        if self.cipher_in_block_size==0 or not self.cipher_in_name:
                            cryptolog.warn("received cipher block but we don't have a cipher to decrypt it with, not an xpra client?")
                            self._invalid_header(read_buffer, "invalid encryption packet flag (no cipher configured)")
                            return
                        padding_size = self.cipher_in_block_size - (data_size % self.cipher_in_block_size)
                        payload_size = data_size + padding_size
                    else:
                        #no cipher, no padding:
                        padding_size = 0
                        payload_size = data_size
                    assert payload_size>0, "invalid payload size: %i" % payload_size
                    read_buffer = read_buffer[8:]

                    if payload_size>self.max_packet_size:
                        #this packet is seemingly too big, but check again from the main UI thread
                        #this gives 'set_max_packet_size' a chance to run from "hello"
                        def check_packet_size(size_to_check, packet_header):
                            if self._closed:
                                return False
                            log("check_packet_size(%s, 0x%s) limit is %s", size_to_check, repr_ellipsized(packet_header), self.max_packet_size)
                            if size_to_check>self.max_packet_size:
                                msg = "packet size requested is %s but maximum allowed is %s" % \
                                              (size_to_check, self.max_packet_size)
                                self.invalid(msg, packet_header)
                            return False
                        self.timeout_add(1000, check_packet_size, payload_size, read_buffer[:32])

                if bl<payload_size:
                    # incomplete packet, wait for the rest to arrive
                    break

                #chop this packet from the buffer:
                if len(read_buffer)==payload_size:
                    raw_string = read_buffer
                    read_buffer = ''
                else:
                    raw_string = read_buffer[:payload_size]
                    read_buffer = read_buffer[payload_size:]
                packet_size += 8+payload_size
                #decrypt if needed:
                data = raw_string
                if self.cipher_in and protocol_flags & FLAGS_CIPHER:
                    cryptolog("received %i %s encrypted bytes with %s padding", payload_size, self.cipher_in_name, padding_size)
                    data = self.cipher_in.decrypt(raw_string)
                    if padding_size > 0:
                        def debug_str(s):
                            try:
                                return hexstr(bytearray(s))
                            except:
                                return csv(tuple(s))
                        # pad byte value is number of padding bytes added
                        padtext = pad(self.cipher_in_padding, padding_size)
                        if data.endswith(padtext):
                            cryptolog("found %s %s padding", self.cipher_in_padding, self.cipher_in_name)
                        else:
                            actual_padding = data[-padding_size:]
                            cryptolog.warn("Warning: %s decryption failed: invalid padding", self.cipher_in_name)
                            cryptolog(" data does not end with %s padding bytes %s", self.cipher_in_padding, debug_str(padtext))
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
                        return self.gibberish(msg, data)

                if self.cipher_in and not (protocol_flags & FLAGS_CIPHER):
                    self.invalid("unencrypted packet dropped", data)
                    return

                if self._closed:
                    return
                if packet_index>0:
                    #raw packet, store it and continue:
                    raw_packets[packet_index] = data
                    payload_size = -1
                    packet_index = 0
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
                padding_size = 0
                #add any raw packets back into it:
                if raw_packets:
                    for index,raw_data in raw_packets.items():
                        #replace placeholder with the raw_data packet data:
                        packet[index] = raw_data
                    raw_packets = {}

                packet_type = packet[0]
                if self.receive_aliases and type(packet_type)==int and packet_type in self.receive_aliases:
                    packet_type = self.receive_aliases.get(packet_type)
                    packet[0] = packet_type
                self.input_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
                if LOG_RAW_PACKET_SIZE:
                    log("%s: %i bytes", packet_type, packet_size)
                packet_size = 0

                self.input_packetcount += 1
                log("processing packet %s", packet_type)
                self._process_packet_cb(self, packet)
                packet = None

    def flush_then_close(self, last_packet, done_callback=None):
        """ Note: this is best effort only
            the packet may not get sent.

            We try to get the write lock,
            we try to wait for the write queue to flush
            we queue our last packet,
            we wait again for the queue to flush,
            then no matter what, we close the connection and stop the threads.
        """
        log("flush_then_close(%s, %s) closed=%s", last_packet, done_callback, self._closed)
        def done():
            log("flush_then_close: done, callback=%s", done_callback)
            if done_callback:
                done_callback()
        if self._closed:
            log("flush_then_close: already closed")
            return done()
        def wait_for_queue(timeout=10):
            #IMPORTANT: if we are here, we have the write lock held!
            if not self._write_queue.empty():
                #write queue still has stuff in it..
                if timeout<=0:
                    log("flush_then_close: queue still busy, closing without sending the last packet")
                    try:
                        self._write_lock.release()
                    except:
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
                    except:
                        pass
                    done()
                def wait_for_packet_sent():
                    log("flush_then_close: wait_for_packet_sent() queue.empty()=%s, closed=%s", self._write_queue.empty(), self._closed)
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
                self._add_chunks_to_queue(chunks, start_send_cb=None, end_send_cb=packet_queued, synchronous=False)
                #just in case wait_for_packet_sent never fires:
                self.timeout_add(5*1000, close_and_release)

        def wait_for_write_lock(timeout=100):
            if not self._write_lock.acquire(False):
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
            except:
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
        def noop():
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
