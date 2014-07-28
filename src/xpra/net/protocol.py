# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods it's threads

# but it works on win32, for whatever that's worth.

import sys
from socket import error as socket_error
import os
import threading
import binascii
from threading import Lock


from xpra.log import Logger
log = Logger("network", "protocol")
debug = log.debug
from xpra.os_util import Queue, strtobytes
from xpra.util import repr_ellipsized
from xpra.net.bytestreams import ABORT
from xpra.net import compression
from xpra.net.compression import nocompress, zcompress, bzcompress, lz4_compress, Compressed, LevelCompressed, get_compression_caps, InvalidCompressionException
from xpra.net.header import unpack_header, pack_header, pack_header_and_data, FLAGS_RENCODE, FLAGS_YAML, FLAGS_CIPHER, FLAGS_NOHEADER
from xpra.net.crypto import get_crypto_caps, get_cipher
from xpra.net import packet_encoding
from xpra.net.packet_encoding import InvalidPacketEncodingException, get_packet_encoding_caps, rencode_dumps, decode, has_rencode, \
                              bencode, has_bencode, yaml_encode, has_yaml


#stupid python version breakage:
if sys.version > '3':
    long = int              #@ReservedAssignment
    unicode = str           #@ReservedAssignment


USE_ALIASES = os.environ.get("XPRA_USE_ALIASES", "1")=="1"

READ_BUFFER_SIZE = int(os.environ.get("XPRA_READ_BUFFER_SIZE", 65536))
#merge header and packet if packet is smaller than:
PACKET_JOIN_SIZE = int(os.environ.get("XPRA_PACKET_JOIN_SIZE", READ_BUFFER_SIZE))
LARGE_PACKET_SIZE = 4096
#inline compressed data in packet if smaller than:
INLINE_SIZE = int(os.environ.get("XPRA_INLINE_SIZE", 2048))
FAKE_JITTER = int(os.environ.get("XPRA_FAKE_JITTER", "0"))


def get_network_caps(legacy=True):
    try:
        from xpra.net.mmap_pipe import can_use_mmap
        mmap = can_use_mmap()
    except:
        mmap = False
    caps = {
                "digest"                : ("hmac", "xor"),
                "rencode"               : packet_encoding.use_rencode,
                "bencode"               : packet_encoding.use_bencode,
                "yaml"                  : packet_encoding.use_yaml,
                "mmap"                  : mmap,
               }
    if legacy:
        #for backwards compatibility only:
        caps.update({
                "raw_packets"           : True,
                "chunked_compression"   : True
                })
    caps.update(get_crypto_caps())
    caps.update(get_compression_caps())
    caps.update(get_packet_encoding_caps())
    return caps


class ConnectionClosedException(Exception):
    pass


class Protocol(object):
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
        self._conn = conn
        if FAKE_JITTER>0:
            from xpra.net.fake_jitter import FakeJitter
            fj = FakeJitter(self.timeout_add, process_packet_cb)
            self._process_packet_cb =  fj.process_packet_cb
        else:
            self._process_packet_cb = process_packet_cb
        self._write_queue = Queue(1)
        self._read_queue = Queue(20)
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
        self.abs_max_packet_size = 32*1024*1024
        self.large_packets = ["hello"]
        self.send_aliases = {}
        self.receive_aliases = {}
        self._log_stats = None          #None here means auto-detect
        self._closed = False
        self._encoder = self.noencode
        self._compress = nocompress
        self.compression_level = 0
        self.cipher_in = None
        self.cipher_in_name = None
        self.cipher_in_block_size = 0
        self.cipher_out = None
        self.cipher_out_name = None
        self.cipher_out_block_size = 0
        self._write_lock = Lock()
        from xpra.daemon_thread import make_daemon_thread
        self._write_thread = make_daemon_thread(self._write_thread_loop, "write")
        self._read_thread = make_daemon_thread(self._read_thread_loop, "read")
        self._read_parser_thread = make_daemon_thread(self._read_parse_thread_loop, "parse")
        self._write_format_thread = make_daemon_thread(self._write_format_thread_loop, "format")
        self._source_has_more = threading.Event()

    STATE_FIELDS = ("max_packet_size", "large_packets", "send_aliases", "receive_aliases",
                    "cipher_in", "cipher_in_name", "cipher_in_block_size",
                    "cipher_out", "cipher_out_name", "cipher_out_block_size",
                    "compression_level")
    def save_state(self):
        state = {
                 "zlib"     : self._compress==zcompress,
                 "bz2"      : self._compress==bzcompress,
                 "lz4"      : lz4_compress and self._compress==lz4_compress,
                 "bencode"  : self._encoder == self.bencode,
                 "rencode"  : self._encoder == self.rencode,
                 "yaml"     : self._encoder == self.yaml
                 }
        for x in Protocol.STATE_FIELDS:
            state[x] = getattr(self, x)
        return state

    def restore_state(self, state):
        assert state is not None
        for x in Protocol.STATE_FIELDS:
            assert x in state, "field %s is missing" % x
            setattr(self, x, state[x])
        if state.get("lz4"):
            self.enable_lz4()
        elif state.get("bz2"):
            self.enable_bz2()
        elif state.get("zlib"):
            self.enable_zlib()
        else:
            self.enable_nocompress()

        if state.get("rencode"):
            self.enable_rencode()
        elif state.get("bencode"):
            self.enable_bencode()
        elif state.get("yaml"):
            self.enable_yaml()
        else:
            raise Exception("invalid state: no encoder specified!")

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


    def set_cipher_in(self, ciphername, iv, password, key_salt, iterations):
        if self.cipher_in_name!=ciphername:
            log.info("receiving data using %s encryption", ciphername)
            self.cipher_in_name = ciphername
        log("set_cipher_in%s", (ciphername, iv, password, key_salt, iterations))
        self.cipher_in, self.cipher_in_block_size = get_cipher(ciphername, iv, password, key_salt, iterations)

    def set_cipher_out(self, ciphername, iv, password, key_salt, iterations):
        if self.cipher_out_name!=ciphername:
            log.info("sending data using %s encryption", ciphername)
            self.cipher_out_name = ciphername
        log("set_cipher_out%s", (ciphername, iv, password, key_salt, iterations))
        self.cipher_out, self.cipher_out_block_size = get_cipher(ciphername, iv, password, key_salt, iterations)


    def __repr__(self):
        return "Protocol(%s)" % self._conn

    def get_threads(self):
        return  [x for x in [self._write_thread, self._read_thread, self._read_parser_thread, self._write_format_thread] if x is not None]


    def get_info(self):
        info = {
            "input.count"           : self.input_stats,
            "input.packetcount"     : self.input_packetcount,
            "input.raw_packetcount" : self.input_raw_packetcount,
            "input.cipher"          : self.cipher_in_name or "",
            "output.count"          : self.output_stats,
            "output.packetcount"    : self.output_packetcount,
            "output.raw_packetcount": self.output_raw_packetcount,
            "output.cipher"         : self.cipher_out_name or "",
            "large_packets"         : self.large_packets,
            "compression_level"     : self.compression_level,
            "max_packet_size"       : self.max_packet_size}
        if self._compress==zcompress:
            info["compression"] = "zlib"
        elif self._compress==lz4_compress:
            info["compression"] = "lz4"
        elif self._compress==bzcompress:
            info["compression"] = "bz2"
        elif self._compress==nocompress:
            info["compression"] = "none"
        for k,v in self.send_aliases.items():
            info["send_alias." + str(k)] = v
            info["send_alias." + str(v)] = k
        for k,v in self.receive_aliases.items():
            info["receive_alias." + str(k)] = v
            info["receive_alias." + str(v)] = k
        try:
            info["encoder"] = self._encoder.__name__
        except:
            log.error("no __name__ defined on %s (type: %s)", self._encoder, type(self._encoder))
        c = self._conn
        if c:
            try:
                info.update(self._conn.get_info())
            except:
                log.error("error collecting connection information on %s", self._conn, exc_info=True)
        return info


    def start(self):
        def do_start():
            if not self._closed:
                self._write_thread.start()
                self._read_thread.start()
                self._read_parser_thread.start()
                self._write_format_thread.start()
        self.idle_add(do_start)

    def send_now(self, packet):
        if self._closed:
            log("send_now(%s ...) connection is closed already, not sending", packet[0])
            return
        log("send_now(%s ...)", packet[0])
        assert self._get_packet_cb==None, "cannot use send_now when a packet source exists!"
        def packet_cb():
            self._get_packet_cb = None
            return (packet, )
        self._get_packet_cb = packet_cb
        self.source_has_more()

    def source_has_more(self):
        self._source_has_more.set()

    def _write_format_thread_loop(self):
        log("write_format_thread_loop starting")
        try:
            while not self._closed:
                self._source_has_more.wait()
                if self._closed:
                    return
                self._source_has_more.clear()
                self._add_packet_to_queue(*self._get_packet_cb())
        except:
            self._internal_error("error in network packet write/format", True)

    def _add_packet_to_queue(self, packet, start_send_cb=None, end_send_cb=None, has_more=False):
        if has_more:
            self._source_has_more.set()
        if packet is None:
            return
        log("add_packet_to_queue(%s ...)", packet[0])
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
                proto_flags |= FLAGS_CIPHER
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
                log("sending %s bytes encrypted with %s padding", payload_size, len(padding))
            if proto_flags & FLAGS_NOHEADER:
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
        if packet_encoding.use_bencode:
            self.enable_bencode()
        elif packet_encoding.use_rencode:
            self.enable_rencode()
        else:
            assert packet_encoding.use_yaml, "no packet encoders available!"
            self.enable_yaml()

    def enable_encoder_from_caps(self, caps):
        if packet_encoding.use_rencode and caps.boolget("rencode"):
            self.enable_rencode()
        elif packet_encoding.use_yaml and caps.boolget("yaml"):
            self.enable_yaml()
        elif packet_encoding.use_bencode and caps.boolget("bencode", True):
            self.enable_bencode()
        else:
            log.error("no matching packet encoder found!")
            return False
        return True

    def enable_bencode(self):
        assert has_bencode, "bencode cannot be enabled: the module failed to load!"
        log("enable_bencode()")
        self._encoder = self.bencode

    def enable_rencode(self):
        assert has_rencode, "rencode cannot be enabled: the module failed to load!"
        log("enable_rencode()")
        self._encoder = self.rencode

    def enable_yaml(self):
        assert has_yaml, "yaml cannot be enabled: the module failed to load!"
        log("enable_yaml()")
        self._encoder = self.yaml


    def enable_default_compressor(self):
        if compression.use_zlib:
            self.enable_zlib()
        elif compression.use_lz4:
            self.enable_lz4()
        elif compression.use_bz2:
            self.enable_bz2()
        else:
            self.enable_nocompress()

    def enable_compressor_from_caps(self, caps):
        if self.compression_level==0:
            self.enable_nocompress()
            return
        if caps.boolget("lz4") and compression.use_lz4 and self.compression_level==1:
            self.enable_lz4()
        elif caps.boolget("zlib") and compression.use_zlib:
            self.enable_zlib()
        elif caps.boolget("bz2") and compression.use_bz2:
            self.enable_bz2()
        #retry lz4 (without level check)
        elif caps.boolget("lz4") and compression.use_lz4:
            self.enable_lz4()
        else:
            log.error("no matching compressor found!")
            self.enable_nocompress()

    def enable_nocompress(self):
        log("nocompress()")
        self._compress = nocompress

    def enable_zlib(self):
        log("enable_zlib()")
        self._compress = zcompress

    def enable_lz4(self):
        assert compression.use_lz4, "lz4 cannot be enabled: the module failed to load!"
        log("enable_lz4()")
        self._compress = lz4_compress

    def enable_bz2(self):
        log("enable_bz2()")
        self._compress = bzcompress        



    def noencode(self, data):
        #just send data as a string for clients that don't understand xpra packet format:
        return ": ".join([str(x) for x in data])+"\n", FLAGS_NOHEADER

    def bencode(self, data):
        return bencode(data), 0

    def rencode(self, data):
        return  rencode_dumps(data), FLAGS_RENCODE

    def yaml(self, data):
        return yaml_encode(data), FLAGS_YAML


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
        self.output_stats[packet_type] = self.output_stats.get(packet_type, 0)+1
        if USE_ALIASES and self.send_aliases and packet_type in self.send_aliases:
            #replace the packet type with the alias:
            packet[0] = self.send_aliases[packet_type]
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
        assert level>=0 and level<=10, "invalid compression level: %s (must be between 0 and 10" % level
        self.compression_level = level

    def _io_thread_loop(self, name, callback):
        try:
            log("io_thread_loop(%s, %s) loop starting", name, callback)
            while not self._closed:
                callback()
            log("io_thread_loop(%s, %s) loop ended, closed=%s", name, callback, self._closed)
        except KeyboardInterrupt, e:
            raise e
        except ConnectionClosedException, e:
            if not self._closed:
                self._internal_error("%s connection %s closed: %s" % (name, self._conn, e))
        except (OSError, IOError, socket_error), e:
            if not self._closed:
                self._internal_error("%s connection %s reset: %s" % (name, self._conn, e), exc_info=e.args[0] in ABORT)
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
            log("write thread: empty marker, exiting")
            self.close()
            return
        for buf, start_cb, end_cb in items:
            con = self._conn
            if not con:
                return
            if start_cb:
                try:
                    start_cb(con.output_bytecount)
                except:
                    if not self._closed:
                        log.error("error on %s", start_cb, exc_info=True)
            while buf and not self._closed:
                written = con.write(buf)
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
        buf = self._conn.read(READ_BUFFER_SIZE)
        #log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
        self._read_queue.put(buf)
        if not buf:
            log("read thread: eof")
            self.close()
            return
        self.input_raw_packetcount += 1

    def _internal_error(self, message="", exc_info=False):
        log.error("internal error: %s", message)
        self.idle_add(self._connection_lost, message, exc_info=exc_info)

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
    def _invalid_header(self, data):
        #call via idle_add gives the client time
        #to disconnect (and so we don't bother with it)
        self.idle_add(self.invalid_header, self, data)

    def invalid_header(self, proto, data):
        err = "invalid packet header: '%s'" % binascii.hexlify(data[:8])
        if len(data)>1:
            err += " read buffer=%s" % repr_ellipsized(data)
        self.gibberish(err, data)


    def _read_parse_thread_loop(self):
        log("read_parse_thread_loop starting")
        try:
            self.do_read_parse_thread_loop()
        except:
            self._internal_error("error in network packet reading/parsing", True)

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
                log("read thread: empty marker, exiting")
                self.idle_add(self.close)
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
                    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(head)

                    #sanity check size (will often fail if not an xpra client):
                    if data_size>self.abs_max_packet_size:
                        self._invalid_header(read_buffer)
                        return

                    bl = len(read_buffer)-8
                    if protocol_flags & FLAGS_CIPHER:
                        if self.cipher_in_block_size==0 or not self.cipher_in_name:
                            log.warn("received cipher block but we don't have a cipher to decrypt it with, not an xpra client?")
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
                #decrypt if needed:
                data = raw_string
                if self.cipher_in and protocol_flags & FLAGS_CIPHER:
                    log("received %s encrypted bytes with %s padding", payload_size, len(padding))
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
                            self._internal_error("encryption error (wrong key?)")
                            return
                        data = data[:-len(padding)]
                #uncompress if needed:
                if compression_level>0:
                    try:
                        data = compression.decompress(data, compression_level)
                    except InvalidCompressionException, e:
                        self.invalid("invalid compression: %s" % e, data)
                        return
                    except Exception, e:
                        ctype = compression.get_compression_type(compression_level)
                        log("%s packet decompression failed", ctype, exc_info=True)
                        msg = "%s packet decompression failed" % ctype
                        if self.cipher_in:
                            msg += " (invalid encryption key?)"
                        msg = "msg: %s" % e
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
                except InvalidPacketEncodingException, e:
                    self.invalid("invalid packet encoding: %s" % e, data)
                    return
                except ValueError, e:
                    etype = packet_encoding.get_packet_encoding_type(protocol_flags)
                    log.error("failed to parse %s packet: %s", etype, e, exc_info=not self._closed)
                    if self._closed:
                        return
                    log("failed to parse %s packet: %s", etype, binascii.hexlify(data))
                    msg = "packet index=%s, packet size=%s, buffer size=%s, error=%s" % (packet_index, payload_size, bl, e)
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

                packet_type = packet[0]
                if self.receive_aliases and type(packet_type)==int and packet_type in self.receive_aliases:
                    packet_type = self.receive_aliases.get(packet_type)
                    packet[0] = packet_type
                self.input_stats[packet_type] = self.output_stats.get(packet_type, 0)+1

                self.input_packetcount += 1
                log("processing packet %s", packet_type)
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
                    log("flush_then_close: queue still busy, closing without sending the last packet")
                    self._write_lock.release()
                    self.close()
                else:
                    log("flush_then_close: still waiting for queue to flush")
                    self.timeout_add(100, wait_for_queue, timeout-1)
            else:
                log("flush_then_close: queue is now empty, sending the last packet and closing")
                chunks, proto_flags = self.encode(last_packet)
                def close_cb(*args):
                    self.close()
                self._add_chunks_to_queue(chunks, proto_flags, start_send_cb=None, end_send_cb=close_cb)
                self._write_lock.release()
                self.timeout_add(5*1000, self.close)

        def wait_for_write_lock(timeout=100):
            if not self._write_lock.acquire(False):
                if timeout<=0:
                    log("flush_then_close: timeout waiting for the write lock")
                    self.close()
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
        # -> close
        wait_for_write_lock()

    def close(self):
        log("close() closed=%s", self._closed)
        if self._closed:
            return
        self._closed = True
        self.idle_add(self._process_packet_cb, self, [Protocol.CONNECTION_LOST])
        if self._conn:
            try:
                self._conn.close()
                if self._log_stats is None and self._conn.input_bytecount==0 and self._conn.output_bytecount==0:
                    #no data sent or received, skip logging of stats:
                    self._log_stats = False
                if self._log_stats:
                    from xpra.simple_stats import std_unit, std_unit_dec
                    log.info("connection closed after %s packets received (%s bytes) and %s packets sent (%s bytes)",
                         std_unit(self.input_packetcount), std_unit_dec(self._conn.input_bytecount),
                         std_unit(self.output_packetcount), std_unit_dec(self._conn.output_bytecount)
                         )
            except:
                log.error("error closing %s", self._conn, exc_info=True)
            self._conn = None
        self.terminate_queue_threads()
        self.idle_add(self.clean)

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
