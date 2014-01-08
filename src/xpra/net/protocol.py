# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods it's threads

# but it works on win32, for whatever that's worth.

import time
import sys
from socket import error as socket_error
import struct
import os
import threading
import errno
import binascii
from threading import Lock

ZLIB_FLAG = 0x00
LZ4_FLAG = 0x10


from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_NETWORK_DEBUG")
from xpra.os_util import Queue, strtobytes, get_hex_uuid
from xpra.daemon_thread import make_daemon_thread
from xpra.simple_stats import std_unit, std_unit_dec

try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
except Exception, e:
    AES = None
    PBKDF2 = None
    debug("pycrypto is missing: %s", e)


from zlib import compress, decompress, decompressobj
try:
    from lz4 import LZ4_compress, LZ4_uncompress        #@UnresolvedImport
    has_lz4 = True
    def lz4_compress(packet, level):
        return level + LZ4_FLAG, LZ4_compress(packet)
except Exception, e:
    debug("lz4 not found: %s", e)
    LZ4_compress, LZ4_uncompress = None, None
    has_lz4 = False
    def lz4_compress(packet, level):
        raise Exception("lz4 is not supported!")
use_lz4 = has_lz4 and os.environ.get("XPRA_USE_LZ4", "1")=="1"

rencode_dumps, rencode_loads, rencode_version = None, None, None
try:
    try:
        from xpra.net.rencode import dumps as rencode_dumps  #@UnresolvedImport
        from xpra.net.rencode import loads as rencode_loads  #@UnresolvedImport
        from xpra.net.rencode import __version__ as rencode_version
    except ImportError, e:
        print("rencode load error: %s" % e)
except Exception, e:
    print("xpra.rencode is missing: %s", e)
has_rencode = rencode_dumps is not None and rencode_loads is not None and rencode_version is not None
use_rencode = has_rencode and os.environ.get("XPRA_USE_RENCODER", "1")=="1"

bencode, bdecode = None, None
try:
    from xpra.net.bencode import bencode, bdecode, __version__ as bencode_version
except Exception, e:
    print("xpra.bencode is missing: %s", e)
has_bencode = bencode is not None and bdecode is not None
use_bencode = has_bencode and os.environ.get("XPRA_USE_BENCODER", "1")=="1"


#stupid python version breakage:
if sys.version > '3':
    long = int          #@ReservedAssignment
    unicode = str           #@ReservedAssignment
    def zcompress(packet, level):
        return level + ZLIB_FLAG, compress(bytes(packet, 'UTF-8'), level)
else:
    def zcompress(packet, level):
        return level + ZLIB_FLAG, compress(str(packet), level)

if sys.version_info[:2]>=(2,5):
    def unpack_header(buf):
        return struct.unpack_from('!cBBBL', buf)
else:
    def unpack_header(buf):
        return struct.unpack('!cBBBL', "".join(buf))


#'P' + protocol-flags + compression_level + packet_index + data_size
def pack_header(proto_flags, level, index, payload_size):
    return struct.pack('!BBBBL', ord("P"), proto_flags, level, index, payload_size)

pack_header_and_data = None
if sys.version_info[0]<3:
    #before v3, python does the right thing without hassle:
    def pack_header_and_data(actual_size, proto_flags, level, index, payload_size, data):
        return struct.pack('!BBBBL%ss' % actual_size, ord("P"), proto_flags, level, index, payload_size, data)


USE_ALIASES = os.environ.get("XPRA_USE_ALIASES", "1")=="1"
#merge header and packet if packet is smaller than:
PACKET_JOIN_SIZE = int(os.environ.get("XPRA_PACKET_JOIN_SIZE", 32768))
LARGE_PACKET_SIZE = 4096
#inline compressed data in packet if smaller than:
INLINE_SIZE = int(os.environ.get("XPRA_INLINE_SIZE", 2048))
FAKE_JITTER = int(os.environ.get("XPRA_FAKE_JITTER", "0"))


def new_cipher_caps(proto, cipher, encryption_key):
    iv = get_hex_uuid()[:16]
    key_salt = get_hex_uuid()+get_hex_uuid()
    iterations = 1000
    proto.set_cipher_in(cipher, iv, encryption_key, key_salt, iterations)
    return {
                 "cipher"           : cipher,
                 "cipher.iv"        : iv,
                 "cipher.key_salt"  : key_salt,
                 "cipher.key_stretch_iterations" : iterations
                 }

def get_network_caps():
    caps = {
                "raw_packets"           : True,
                "chunked_compression"   : True,
                "digest"                : ("hmac", "xor"),
                "rencode"               : use_rencode,
                "bencode"               : use_bencode,
                "lz4"                   : use_lz4,
                "zlib"                  : True,
               }
    try:
        import Crypto
        caps["pycrypto.version"] = Crypto.__version__
        try:
            from Crypto.PublicKey import _fastmath
        except:
            _fastmath = None
        caps["pycrypto.fastmath"] = _fastmath is not None
    except:
        pass

    if has_rencode:
        caps["rencode.version"] = rencode_version
    if has_bencode:
        caps["bencode.version"] = bencode_version
    return caps


def repr_ellipsized(obj, limit=100):
    if isinstance(obj, str) and len(obj) > limit:
        try:
            s = repr(obj[:limit])
            if len(obj)>limit:
                s += "..."
            return s
        except:
            return binascii.hexlify(obj[:limit])
    else:
        return repr(obj)


class ConnectionClosedException(Exception):
    pass


class Compressed(object):
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)
    def __str__(self):
        return  "Compressed(%s: %s bytes)" % (self.datatype, len(self.data))

class LevelCompressed(Compressed):
    def __init__(self, datatype, data, level, algo):
        Compressed.__init__(self, datatype, data)
        self.algorithm = algo
        self.level = level
    def __len__(self):
        return len(self.data)
    def __str__(self):
        return  "LevelCompressed(%s: %s bytes as %s/%s)" % (self.datatype, len(self.data), self.algorithm, self.level)

def compressed_wrapper(datatype, data, level=5, lz4=False):
    if lz4:
        assert use_lz4, "cannot use lz4"
        algo = "lz4"
        cl, cdata = lz4_compress(data, level & LZ4_FLAG)
    else:
        algo = "zlib"
        cl, cdata = zcompress(data, level)
    return LevelCompressed(datatype, cdata, cl, algo)


class Protocol(object):
    CONNECTION_LOST = "connection-lost"
    GIBBERISH = "gibberish"

    FLAGS_RENCODE = 0x1
    FLAGS_CIPHER = 0x2
    FLAGS_NOHEADER = 0x40

    def __init__(self, scheduler, conn, process_packet_cb, get_packet_cb=None):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert scheduler is not None
        assert conn is not None
        self.scheduler = scheduler
        self._conn = conn
        if FAKE_JITTER>0:
            fj = FakeJitter(self.scheduler, process_packet_cb)
            self._process_packet_cb =  fj.process_packet_cb
        else:
            self._process_packet_cb = process_packet_cb
        self._write_queue = Queue(1)
        self._read_queue = Queue(20)
        # Invariant: if .source is None, then _source_has_more == False
        self._get_packet_cb = get_packet_cb
        #counters:
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        #initial value which may get increased by client/server after handshake:
        self.max_packet_size = 32*1024
        self.abs_max_packet_size = 32*1024*1024
        self.large_packets = ["hello"]
        self.aliases = {}
        self.chunked_compression = True
        self._log_stats = None          #None here means auto-detect
        self._closed = False
        self._encoder = self.noencode
        self._compress = zcompress
        self._decompressor = decompressobj()
        self.compression_level = 0
        self.cipher_in = None
        self.cipher_in_name = None
        self.cipher_in_block_size = 0
        self.cipher_out = None
        self.cipher_out_name = None
        self.cipher_out_block_size = 0
        self._write_lock = Lock()
        self._write_thread = make_daemon_thread(self._write_thread_loop, "write")
        self._read_thread = make_daemon_thread(self._read_thread_loop, "read")
        self._read_parser_thread = make_daemon_thread(self._read_parse_thread_loop, "parse")
        self._write_format_thread = make_daemon_thread(self._write_format_thread_loop, "format")
        self._source_has_more = threading.Event()
        self.enable_default_encoder()

    STATE_FIELDS = ("max_packet_size", "large_packets", "aliases",
                    "chunked_compression",
                    "cipher_in", "cipher_in_name", "cipher_in_block_size",
                    "cipher_out", "cipher_out_name", "cipher_out_block_size",
                    "compression_level")
    def save_state(self):
        state = {}
        for x in Protocol.STATE_FIELDS:
            state[x] = getattr(self, x)
        state["zlib"] = self._compress==zcompress
        state["lz4"] = lz4_compress and self._compress==lz4_compress
        state["bencode"] = self._encoder == self.bencode
        state["rencode"] = self._encoder == self.rencode
        #state["connection"] = self._conn
        return state

    def restore_state(self, state):
        assert state is not None
        for x in Protocol.STATE_FIELDS:
            assert x in state, "field %s is missing" % x
            setattr(self, x, state[x])
        if state.get("lz4", False):
            self.enable_lz4()
        if state.get("rencode", False):
            self.enable_rencode()

    def wait_for_io_threads_exit(self, timeout=None):
        for t in (self._read_thread, self._write_thread):
            t.join(timeout)
        exited = True
        for t in (self._read_thread, self._write_thread):
            if t.isAlive():
                exited = False
                break
        return exited

    def set_packet_source(self, get_packet_cb):
        self._get_packet_cb = get_packet_cb

    def get_cipher(self, ciphername, iv, password, key_salt, iterations):
        debug("get_cipher(%s, %s, %s, %s, %s)", ciphername, iv, password, key_salt, iterations)
        if not ciphername:
            return None, 0
        assert iterations>=100
        assert ciphername=="AES"
        assert password and iv
        assert (AES and PBKDF2), "pycrypto is missing!"
        #stretch the password:
        block_size = 32         #fixme: can we derive this?
        secret = PBKDF2(password, key_salt, dkLen=block_size, count=iterations)
        debug("get_cipher(..) secret=%s, block_size=%s", secret.encode('hex'), block_size)
        return AES.new(secret, AES.MODE_CBC, iv), block_size

    def set_cipher_in(self, ciphername, iv, password, key_salt, iterations):
        if self.cipher_in_name!=ciphername:
            log.info("receiving data using %s encryption", ciphername)
            self.cipher_in_name = ciphername
        debug("set_cipher_in%s", (ciphername, iv, password, key_salt, iterations))
        self.cipher_in, self.cipher_in_block_size = self.get_cipher(ciphername, iv, password, key_salt, iterations)

    def set_cipher_out(self, ciphername, iv, password, key_salt, iterations):
        if self.cipher_out_name!=ciphername:
            log.info("sending data using %s encryption", ciphername)
            self.cipher_out_name = ciphername
        debug("set_cipher_out%s", (ciphername, iv, password, key_salt, iterations))
        self.cipher_out, self.cipher_out_block_size = self.get_cipher(ciphername, iv, password, key_salt, iterations)

    def __str__(self):
        return "Protocol(%s)" % self._conn

    def get_threads(self):
        return  [x for x in [self._write_thread, self._read_thread, self._read_parser_thread, self._write_format_thread] if x is not None]

    def add_stats(self, info, prefix="net.", suffix=""):
        info[prefix+"input.bytecount" + suffix] = self._conn.input_bytecount
        info[prefix+"input.packetcount" + suffix] = self.input_packetcount
        info[prefix+"input.raw_packetcount" + suffix] = self.input_raw_packetcount
        info[prefix+"input.cipher" + suffix] = self.cipher_in_name or ""
        info[prefix+"output.bytecount" + suffix] = self._conn.output_bytecount
        info[prefix+"output.packetcount" + suffix] = self.output_packetcount
        info[prefix+"output.raw_packetcount" + suffix] = self.output_raw_packetcount
        info[prefix+"output.cipher" + suffix] = self.cipher_out_name or ""
        info[prefix+"chunked_compression" + suffix] = self.chunked_compression
        info[prefix+"large_packets" + suffix] = self.large_packets
        info[prefix+"compression_level" + suffix] = self.compression_level
        if self._compress==zcompress:
            info[prefix+"compression" + suffix] = "zlib"
        elif self._compress==lz4_compress:
            info[prefix+"compression" + suffix] = "lz4"
        info[prefix+"max_packet_size" + suffix] = self.max_packet_size
        for k,v in self.aliases.items():
            info[prefix+"alias." + k + suffix] = v
            info[prefix+"alias." + str(v) + suffix] = k
        try:
            info[prefix+"encoder" + suffix] = self._encoder.__name__
        except:
            pass
        if self._conn:
            try:
                info[prefix+"type"+suffix] = self._conn.info
                info[prefix+"endpoint"+suffix] = self._conn.target
            except:
                log.error("failed to report connection information", exc_info=True)

    def start(self):
        def do_start():
            if not self._closed:
                self._write_thread.start()
                self._read_thread.start()
                self._read_parser_thread.start()
                self._write_format_thread.start()
        self.scheduler.idle_add(do_start)

    def send_now(self, packet):
        if self._closed:
            debug("send_now(%s ...) connection is closed already, not sending", packet[0])
            return
        debug("send_now(%s ...)", packet[0])
        assert self._get_packet_cb==None, "cannot use send_now when a packet source exists!"
        def packet_cb():
            self._get_packet_cb = None
            return (packet, )
        self._get_packet_cb = packet_cb
        self.source_has_more()

    def source_has_more(self):
        self._source_has_more.set()

    def _write_format_thread_loop(self):
        debug("write_format_thread_loop starting")
        try:
            while not self._closed:
                self._source_has_more.wait()
                if self._closed:
                    return
                self._source_has_more.clear()
                self._add_packet_to_queue(*self._get_packet_cb())
        except Exception, e:
            log.error("error in write format loop", exc_info=True)
            self._call_connection_lost("error in network packet write/format: %s" % e)

    def _add_packet_to_queue(self, packet, start_send_cb=None, end_send_cb=None, has_more=False):
        if has_more:
            self._source_has_more.set()
        if packet is None:
            return
        debug("add_packet_to_queue(%s ...)", packet[0])
        chunks, proto_flags = self.encode(packet)
        try:
            self._write_lock.acquire()
            self._add_chunks_to_queue(chunks, proto_flags, start_send_cb, end_send_cb)
        finally:
            self._write_lock.release()

    def _add_chunks_to_queue(self, chunks, proto_flags, start_send_cb=None, end_send_cb=None):
        """ the write_lock must be held when calling this function """
        counter = 0
        items = []
        for index,level,data in chunks:
            scb, ecb = None, None
            #fire the start_send_callback just before the first packet is processed:
            if counter==0:
                scb = start_send_cb
            #fire the end_send callback when the last packet (index==0) makes it out:
            if index==0:
                ecb = end_send_cb
            payload_size = len(data)
            actual_size = payload_size
            if self.cipher_out:
                proto_flags |= Protocol.FLAGS_CIPHER
                #note: since we are padding: l!=len(data)
                padding = (self.cipher_out_block_size - len(data) % self.cipher_out_block_size) * " "
                if len(padding)==0:
                    padded = data
                else:
                    padded = data+padding
                actual_size = payload_size + len(padding)
                assert len(padded)==actual_size
                data = self.cipher_out.encrypt(padded)
                assert len(data)==actual_size
                debug("sending %s bytes encrypted with %s padding", payload_size, len(padding))
            if proto_flags & Protocol.FLAGS_NOHEADER:
                #for plain/text packets (ie: gibberish response)
                items.append((data, scb, ecb))
            elif pack_header_and_data is not None and actual_size<PACKET_JOIN_SIZE:
                if type(data)==unicode:
                    data = str(data)
                header_and_data = pack_header_and_data(actual_size, proto_flags, level, index, payload_size, data)
                items.append((header_and_data, scb, ecb))
            else:
                header = pack_header(proto_flags, level, index, payload_size)
                items.append((header, scb, None))
                items.append((strtobytes(data), None, ecb))
            counter += 1
        self._write_queue.put(items)
        self.output_packetcount += 1

    def verify_packet(self, packet):
        """ look for None values which may have caused the packet to fail encoding """
        if type(packet)!=list:
            return
        assert len(packet)>0
        tree = ["'%s' packet" % packet[0]]
        self.do_verify_packet(tree, packet)

    def do_verify_packet(self, tree, packet):
        def err(msg):
            log.error("%s in %s", msg, "->".join(tree))
        def new_tree(append):
            nt = tree[:]
            nt.append(append)
            return nt
        if packet is None:
            return err("None value")
        if type(packet)==list:
            i = 0
            for x in packet:
                self.do_verify_packet(new_tree("[%s]" % i), x)
                i += 1
        elif type(packet)==dict:
            for k,v in packet.items():
                self.do_verify_packet(new_tree("key for value='%s'" % str(v)), k)
                self.do_verify_packet(new_tree("value for key='%s'" % str(k)), v)

    def enable_default_encoder(self):
        if has_bencode:
            self.enable_bencode()
        else:
            self.enable_rencode()

    def enable_bencode(self):
        assert has_bencode, "bencode cannot be enabled: the module failed to load!"
        debug("enable_bencode()")
        self._encoder = self.bencode

    def enable_rencode(self):
        assert has_rencode, "rencode cannot be enabled: the module failed to load!"
        debug("enable_rencode()")
        self._encoder = self.rencode

    def enable_zlib(self):
        debug("enable_zlib()")
        self._compress = zcompress

    def enable_lz4(self):
        assert has_lz4, "lz4 cannot be enabled: the module failed to load!"
        assert self.chunked_compression, "cannot enable lz4 without chunked compression"
        debug("enable_lz4()")
        self._compress = lz4_compress

    def noencode(self, data):
        #just send data as a string for clients that don't understand xpra packet format:
        return ": ".join([str(x) for x in data])+"\n", Protocol.FLAGS_NOHEADER

    def bencode(self, data):
        return bencode(data), 0

    def rencode(self, data):
        return  rencode_dumps(data), Protocol.FLAGS_RENCODE

    def encode(self, packet_in):
        """
        Given a packet (tuple or list of items), converts it for the wire.
        This method returns all the binary packets to send, as an array of:
        (index, compression_level, binary_data)
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
        min_comp_size = 378
        for i in range(1, len(packet)):
            item = packet[i]
            ti = type(item)
            if ti in (int, long, bool, dict, list, tuple):
                continue
            elif ti==Compressed:
                #already compressed data (usually pixels), send it as-is
                if len(item)>INLINE_SIZE:
                    packets.append((i, 0, item.data))
                    packet[i] = ''
                else:
                    #data is small enough, inline it:
                    packet[i] = item.data
                    min_comp_size += len(item)
            elif ti==LevelCompressed:
                #already compressed data as zlib or lz4, send as-is with compression marker
                assert item.level>0
                packets.append((i, item.level, item.data))
                packet[i] = ''
            elif ti==str and level>0 and len(item)>LARGE_PACKET_SIZE:
                log.warn("found a large uncompressed item in packet '%s' at position %s: %s bytes", packet[0], i, len(item))
                #add new binary packet with large item:
                cl, cdata = self._compress(item, level)
                packets.append((i, cl, cdata))
                #replace this item with an empty string placeholder:
                packet[i] = ''
            elif ti!=str:
                log.warn("unexpected data type in %s packet: %s", packet[0], ti)
        #now the main packet (or what is left of it):
        packet_type = packet[0]
        if USE_ALIASES and self.aliases and packet_type in self.aliases:
            #replace the packet type with the alias:
            packet[0] = self.aliases[packet_type]
        try:
            main_packet, proto_version = self._encoder(packet)
        except Exception, e:
            if self._closed:
                return [], 0
            log.error("failed to encode packet: %s", packet, exc_info=True)
            #make the error a bit nicer to parse: undo aliases:
            packet[0] = packet_type
            self.verify_packet(packet)
            raise e
        if len(main_packet)>LARGE_PACKET_SIZE and packet_in[0] not in self.large_packets:
            log.warn("found large packet (%s bytes): %s, argument types:%s, sizes: %s, packet head=%s",
                     len(main_packet), packet_in[0], [type(x) for x in packet[1:]], [len(str(x)) for x in packet[1:]], repr_ellipsized(packet))
        #compress, but don't bother for small packets:
        if level>0 and len(main_packet)>min_comp_size:
            cl, cdata = self._compress(main_packet, level)
            packets.append((0, cl, cdata))
        else:
            packets.append((0, 0, main_packet))
        return packets, proto_version

    def set_compression_level(self, level):
        #this may be used next time encode() is called
        self.compression_level = level

    def _io_thread_loop(self, name, callback):
        try:
            debug("io_thread_loop(%s, %s) loop starting", name, callback)
            while not self._closed:
                callback()
            debug("io_thread_loop(%s, %s) loop ended, closed=%s", name, callback, self._closed)
        except KeyboardInterrupt, e:
            raise e
        except ConnectionClosedException, e:
            if not self._closed:
                #log it at debug level
                #(rely on location where we raise to provide better logging)
                debug("%s connection closed for %s", name, self._conn)
                self._call_connection_lost("%s connection closed: %s" % (name, e))
        except (OSError, IOError, socket_error), e:
            if not self._closed:
                if e.args[0] in (errno.ECONNRESET, errno.EPIPE):
                    log.error("%s connection reset for %s", name, self._conn)
                    self._call_connection_lost("%s connection reset: %s" % (name, e))
                else:
                    log.error("%s error for %s", name, self._conn, exc_info=True)
                    self._call_connection_lost("%s error on connection: %s" % (name, e))
        except Exception, e:
            #can happen during close(), in which case we just ignore:
            if not self._closed:
                log.error("%s error on %s", name, self._conn, exc_info=True)
                self.close()

    def _write_thread_loop(self):
        self._io_thread_loop("write", self._write)
    def _write(self):
        items = self._write_queue.get()
        # Used to signal that we should exit:
        if items is None:
            debug("write thread: empty marker, exiting")
            self.close()
            return
        for buf, start_cb, end_cb in items:
            if start_cb:
                try:
                    start_cb(self._conn.output_bytecount)
                except:
                    log.error("error on %s", start_cb, exc_info=True)
            while buf and not self._closed:
                written = self._conn.write(buf)
                if written:
                    buf = buf[written:]
                    self.output_raw_packetcount += 1
            if end_cb:
                try:
                    end_cb(self._conn.output_bytecount)
                except:
                    if not self._closed:
                        log.error("error on %s", end_cb, exc_info=True)

    def _read_thread_loop(self):
        self._io_thread_loop("read", self._read)
    def _read(self):
        buf = self._conn.read(8192)
        #log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
        self._read_queue.put(buf)
        if not buf:
            debug("read thread: eof")
            self.close()
            return
        self.input_raw_packetcount += 1

    def _call_connection_lost(self, message="", exc_info=False):
        debug("will call connection lost: %s", message)
        self.scheduler.idle_add(self._connection_lost, message, exc_info)

    def _connection_lost(self, message="", exc_info=False):
        log.info("connection lost: %s", message, exc_info=exc_info)
        self.close()
        return False

    def gibberish(self, msg, data):
        self.scheduler.idle_add(self._process_packet_cb, self, [Protocol.GIBBERISH, data])
        # Then hang up:
        self.scheduler.timeout_add(1000, self._connection_lost, msg)

    def _invalid_header(self, data):
        self.invalid_header(self, data)

    def invalid_header(self, proto, data):
        err = "invalid packet header byte: '%s'" % hex(ord(data[0]))
        if len(data)>1:
            err += " read buffer=0x%s" % repr_ellipsized(data)
        self.gibberish(err, data)

    def _read_parse_thread_loop(self):
        debug("read_parse_thread_loop starting")
        try:
            self.do_read_parse_thread_loop()
        except Exception, e:
            log.error("error in read parse loop", exc_info=True)
            self._call_connection_lost("error in network packet reading/parsing: %s" % e)

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
        payload_size = -1
        padding = None
        packet_index = 0
        compression_level = False
        raw_packets = {}
        while not self._closed:
            buf = self._read_queue.get()
            if not buf:
                debug("read thread: empty marker, exiting")
                self.scheduler.idle_add(self.close)
                return
            if read_buffer:
                read_buffer = read_buffer + buf
            else:
                read_buffer = buf
            bl = len(read_buffer)
            while not self._closed:
                bl = len(read_buffer)
                if bl<=0:
                    break
                if payload_size<0:
                    head = read_buffer[:8]
                    if read_buffer[0] not in ("P", ord("P")):
                        self._invalid_header(read_buffer)
                        return
                    if bl<8:
                        break   #packet still too small
                    #packet format: struct.pack('cBBBL', ...) - 8 bytes
                    #debug("packet header: %s", binascii.hexlify(head))
                    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(head)

                    #sanity check size (will often fail if not an xpra client):
                    if data_size>self.abs_max_packet_size:
                        self._invalid_header(read_buffer)
                        return

                    bl = len(read_buffer)-8
                    if protocol_flags & Protocol.FLAGS_CIPHER:
                        if self.cipher_in_block_size==0 or not self.cipher_in_name:
                            log.warn("received cipher block but we don't have a cipher do decrypt it with, not an xpra client?")
                            self._invalid_header(read_buffer)
                            return
                        padding = (self.cipher_in_block_size - data_size % self.cipher_in_block_size) * " "
                        payload_size = data_size + len(padding)
                    else:
                        #no cipher, no padding:
                        padding = None
                        payload_size = data_size
                    assert payload_size>0
                    read_buffer = read_buffer[8:]

                if payload_size>self.max_packet_size:
                    #this packet is seemingly too big, but check again from the main UI thread
                    #this gives 'set_max_packet_size' a chance to run from "hello"
                    def check_packet_size(size_to_check, packet_header):
                        if not self._closed:
                            debug("check_packet_size(%s, 0x%s) limit is %s", size_to_check, repr_ellipsized(packet_header), self.max_packet_size)
                            if size_to_check>self.max_packet_size:
                                self._call_connection_lost("invalid packet: size requested is %s (maximum allowed is %s - packet header: 0x%s), dropping this connection!" %
                                                              (size_to_check, self.max_packet_size, repr_ellipsized(packet_header)))
                        return False
                    self.scheduler.timeout_add(1000, check_packet_size, payload_size, read_buffer[:32])

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
                #decrypt if needed:
                data = raw_string
                if self.cipher_in and protocol_flags & Protocol.FLAGS_CIPHER:
                    debug("received %s encrypted bytes with %s padding", payload_size, len(padding))
                    data = self.cipher_in.decrypt(raw_string)
                    if padding:
                        def debug_str(s):
                            try:
                                return list(bytearray(s))
                            except:
                                return list(str(s))
                        if not data.endswith(padding):
                            log("decryption failed: string does not end with '%s': %s (%s) -> %s (%s)",
                            padding, debug_str(raw_string), type(raw_string), debug_str(data), type(data))
                            self._connection_lost("encryption error (wrong key?)")
                            return
                        data = data[:-len(padding)]
                #uncompress if needed:
                if compression_level>0:
                    try:
                        if self.chunked_compression:
                            if compression_level & LZ4_FLAG:
                                assert has_lz4
                                data = LZ4_uncompress(data)
                            else:
                                data = decompress(data)
                        else:
                            data = self._decompressor.decompress(data)
                    except Exception, e:
                        if self.cipher_in:
                            return self._call_connection_lost("decompression failed (invalid encryption key?): %s" % e)
                        return self._call_connection_lost("decompression failed: %s" % e)

                if self.cipher_in and not (protocol_flags & Protocol.FLAGS_CIPHER):
                    return self._call_connection_lost("unencrypted packet dropped: %s" % repr_ellipsized(data))

                if self._closed:
                    return
                if packet_index>0:
                    #raw packet, store it and continue:
                    raw_packets[packet_index] = data
                    payload_size = -1
                    packet_index = 0
                    if len(raw_packets)>=4:
                        return self._call_connection_lost("too many raw packets: %s" % len(raw_packets))
                    continue
                #final packet (packet_index==0), decode it:
                try:
                    if protocol_flags & Protocol.FLAGS_RENCODE:
                        assert has_rencode, "we don't support rencode mode but the other end sent us a rencoded packet! not an xpra client?"
                        packet = list(rencode_loads(data))
                    else:
                        #if sys.version>='3':
                        #    data = data.decode("latin1")
                        packet, l = bdecode(data)
                        assert l==len(data)
                except ValueError, e:
                    log.error("value error reading packet: %s", e, exc_info=True)
                    if self._closed:
                        return
                    debug("failed to parse packet: %s", binascii.hexlify(data))
                    msg = "gibberish received: %s, packet index=%s, packet size=%s, buffer size=%s, error=%s" % (repr_ellipsized(data), packet_index, payload_size, bl, e)
                    self.gibberish(msg, data)
                    return

                if self._closed:
                    return
                payload_size = -1
                padding = None
                #add any raw packets back into it:
                if raw_packets:
                    for index,raw_data in raw_packets.items():
                        #replace placeholder with the raw_data packet data:
                        packet[index] = raw_data
                    raw_packets = {}

                self.input_packetcount += 1
                debug("processing packet %s", packet[0])
                self._process_packet_cb(self, packet)

    def flush_then_close(self, last_packet):
        """ Note: this is best effort only
            the packet may not get sent.

            We try to get the write lock,
            we try to wait for the write queue to flush
            we queue our last packet,
            we wait again for the queue to flush,
            then no matter what, we close the connection and stop the threads.
        """
        if self._closed:
            return
        def wait_for_queue(timeout=10):
            #IMPORTANT: if we are here, we have the write lock held!
            if not self._write_queue.empty():
                #write queue still has stuff in it..
                if timeout<=0:
                    debug("flush_then_close: queue still busy, closing without sending the last packet")
                    self._write_lock.release()
                    self.close()
                else:
                    debug("flush_then_close: still waiting for queue to flush")
                    self.scheduler.timeout_add(100, wait_for_queue, timeout-1)
            else:
                debug("flush_then_close: queue is now empty, sending the last packet and closing")
                chunks, proto_flags = self.encode(last_packet)
                def close_cb(*args):
                    self.close()
                self._add_chunks_to_queue(chunks, proto_flags, start_send_cb=None, end_send_cb=close_cb)
                self._write_lock.release()
                self.scheduler.timeout_add(5*1000, self.close)

        def wait_for_write_lock(timeout=100):
            if not self._write_lock.acquire(False):
                if timeout<=0:
                    debug("flush_then_close: timeout waiting for the write lock")
                    self.close()
                else:
                    debug("flush_then_close: write lock is busy, will retry %s more times", timeout)
                    self.scheduler.timeout_add(10, wait_for_write_lock, timeout-1)
            else:
                debug("flush_then_close: acquired the write lock")
                #we have the write lock - we MUST free it!
                wait_for_queue()
        #normal codepath:
        # -> wait_for_write_lock
        # -> wait_for_queue
        # -> _add_chunks_to_queue
        # -> close
        wait_for_write_lock()

    def close(self):
        debug("close() closed=%s", self._closed)
        if self._closed:
            return
        self._closed = True
        self.scheduler.idle_add(self._process_packet_cb, self, [Protocol.CONNECTION_LOST])
        if self._conn:
            try:
                self._conn.close()
                if self._log_stats is None and self._conn.input_bytecount==0 and self._conn.output_bytecount==0:
                    #no data sent or received, skip logging of stats:
                    self._log_stats = False
                if self._log_stats:
                    log.info("connection closed after %s packets received (%s bytes) and %s packets sent (%s bytes)",
                         std_unit(self.input_packetcount), std_unit_dec(self._conn.input_bytecount),
                         std_unit(self.output_packetcount), std_unit_dec(self._conn.output_bytecount)
                         )
            except:
                log.error("error closing %s", self._conn, exc_info=True)
            self._conn = None
        self.terminate_queue_threads()
        self.scheduler.idle_add(self.clean)

    def steal_connection(self):
        #so we can re-use this connection somewhere else
        #(frees all protocol threads and resources)
        assert not self._closed
        conn = self._conn
        self._closed = True
        self._conn = None
        self.terminate_queue_threads()
        return conn

    def clean(self):
        #clear all references to ensure we can get garbage collected quickly:
        self._get_packet_cb = None
        self._encoder = None
        self._write_thread = None
        self._read_thread = None
        self._read_parser_thread = None
        self._process_packet_cb = None

    def terminate_queue_threads(self):
        log("terminate_queue_threads()")
        #the format thread will exit since closed is set too:
        self._source_has_more.set()
        #make the threads exit by adding the empty marker:
        try:
            self._write_queue.put_nowait(None)
        except:
            pass
        try:
            self._read_queue.put_nowait(None)
        except:
            pass


class FakeJitter(object):

    def __init__(self, scheduler, process_packet_cb):
        self.scheduler = scheduler
        self.real_process_packet_cb = process_packet_cb
        self.delay = FAKE_JITTER
        self.ok_delay = 10*1000
        self.switch_time = time.time()
        self.delaying = False
        self.pending = []
        self.lock = Lock()
        self.flush()

    def start_buffering(self):
        log.info("FakeJitter.start_buffering() will buffer for %s ms", FAKE_JITTER)
        self.delaying = True
        self.scheduler.timeout_add(FAKE_JITTER, self.flush)

    def flush(self):
        log.info("FakeJitter.flush() processing %s delayed packets", len(self.pending))
        try:
            self.lock.acquire()
            for proto, packet in self.pending:
                self.real_process_packet_cb(proto, packet)
            self.pending = []
            self.delaying = False
        finally:
            self.lock.release()
        self.scheduler.timeout_add(self.ok_delay, self.start_buffering)
        log.info("FakeJitter.flush() will start buffering again in %s ms", self.ok_delay)

    def process_packet_cb(self, proto, packet):
        try:
            self.lock.acquire()
            if self.delaying:
                self.pending.append((proto, packet))
            else:
                self.real_process_packet_cb(proto, packet)
        finally:
            self.lock.release()
