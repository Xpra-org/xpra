# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods it's threads

# but it works on win32, for whatever that's worth.

from wimpiggy.gobject_compat import import_gobject
gobject = import_gobject()
gobject.threads_init()
import sys
import socket # for socket.error
import zlib
import struct
import os
import threading

PACKET_JOIN_SIZE = int(os.environ.get("XPRA_PACKET_JOIN_SIZE", 16384))

try:
    from queue import Queue     #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue     #@Reimport
from threading import RLock

from wimpiggy.log import Logger
log = Logger()

from xpra.daemon_thread import make_daemon_thread
from xpra.bytestreams import untilConcludes
from xpra.bencode import bencode, bdecode
rencode_dumps, rencode_loads = None, None
try:
    try:
        from xpra.rencode import dumps as rencode_dumps  #@UnresolvedImport
        from xpra.rencode import loads as rencode_loads  #@UnresolvedImport
    except ImportError:
        pass
except Exception, e:
    log.error("xpra.rencode is missing: %s", e)
has_rencode = rencode_dumps is not None and rencode_loads is not None
use_rencode = has_rencode and not os.environ.get("XPRA_USE_BENCODER", "0")=="1"


def repr_ellipsized(obj, limit=100):
    if isinstance(obj, str) and len(obj) > limit:
        return repr(obj[:limit]) + "..."
    else:
        return repr(obj)

class Compressed(object):
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)

class ZLibCompressed(object):
    def __init__(self, datatype, data, level):
        self.datatype = datatype
        self.data = data
        self.level = level
    def __len__(self):
        return len(self.data)

def zlib_compress(datatype, data, level=5):
    cdata = zlib.compress(data, level)
    return ZLibCompressed(datatype, cdata, level)


class Protocol(object):
    CONNECTION_LOST = "connection-lost"
    GIBBERISH = "gibberish"

    FLAGS_RENCODE = 0x1
    FLAGS_CIPHER = 0x2

    def __init__(self, conn, process_packet_cb, get_packet_cb=None):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert conn is not None
        self._conn = conn
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
        self.large_packets = ["hello"]
        self.chunked_compression = True
        self._closed = False
        self._encoder = self.bencode
        self._decompressor = zlib.decompressobj()
        self._compression_level = 0
        self.cipher_in = None
        self.cipher_in_name = None
        self.cipher_in_block_size = 0
        self.cipher_out = None
        self.cipher_out_name = None
        self.cipher_out_block_size = 0
        self._write_lock = RLock()
        self._write_thread = make_daemon_thread(self._write_thread_loop, "write")
        self._read_thread = make_daemon_thread(self._read_thread_loop, "read")
        self._read_parser_thread = make_daemon_thread(self._read_parse_thread_loop, "parse")
        self._write_format_thread = make_daemon_thread(self._write_format_thread_loop, "format")
        self._source_has_more = threading.Event()

    def set_packet_source(self, get_packet_cb):
        self._get_packet_cb = get_packet_cb

    def get_cipher(self, ciphername, iv, password, key_salt, iterations):
        log("get_cipher_in(%s, %s, %s, %s, %s)", ciphername, iv, password, key_salt, iterations)
        if not ciphername:
            return None, 0
        assert iterations>=100
        assert ciphername=="AES"
        assert password and iv
        from Crypto.Cipher import AES
        from Crypto.Protocol.KDF import PBKDF2
        #stretch the password:
        block_size = 32         #fixme: can we derive this?
        secret = PBKDF2(password, key_salt, dkLen=block_size, count=iterations)
        #secret = (password+password+password+password+password+password+password+password)[:32]
        log("get_cipher(%s, %s, %s) secret=%s, block_size=%s", ciphername, iv, password, secret.encode('hex'), block_size)
        return AES.new(secret, AES.MODE_CBC, iv), block_size

    def set_cipher_in(self, ciphername, iv, password, key_salt, iterations):
        if self.cipher_in_name!=ciphername:
            log.info("receiving data using %s encryption", ciphername)
            self.cipher_in_name = ciphername
        self.cipher_in, self.cipher_in_block_size = self.get_cipher(ciphername, iv, password, key_salt, iterations)

    def set_cipher_out(self, ciphername, iv, password, key_salt, iterations):
        if self.cipher_out_name!=ciphername:
            log.info("sending data using %s encryption", ciphername)
            self.cipher_out_name = ciphername
        self.cipher_out, self.cipher_out_block_size = self.get_cipher(ciphername, iv, password, key_salt, iterations)

    def __str__(self):
        return "Protocol(%s)" % self._conn

    def get_threads(self):
        return  [x for x in [self._write_thread, self._read_thread, self._read_parser_thread] if x is not None]

    def add_stats(self, info,  suffix=""):
        info["input_bytecount%s" % suffix] = self._conn.input_bytecount
        info["input_packetcount%s" % suffix] = self.input_packetcount
        info["input_raw_packetcount%s" % suffix] = self.input_raw_packetcount
        info["output_bytecount%s" % suffix] = self._conn.output_bytecount
        info["output_packetcount%s" % suffix] = self.output_packetcount
        info["output_raw_packetcount%s" % suffix] = self.output_raw_packetcount

    def start(self):
        def do_start():
            if not self._closed:
                self._write_thread.start()
                self._read_thread.start()
                self._read_parser_thread.start()
                self._write_format_thread.start()
        gobject.idle_add(do_start)

    def source_has_more(self):
        self._source_has_more.set()

    def _write_format_thread_loop(self):
        while not self._closed:
            self._source_has_more.wait()
            if self._closed:
                return
            self._source_has_more.clear()
            self._add_packet_to_queue(*self._get_packet_cb())

    def _add_packet_to_queue(self, packet, start_send_cb=None, end_send_cb=None, has_more=False):
        if has_more:
            self._source_has_more.set()
        if packet is None:
            return
        packets, proto_flags = self.encode(packet)
        try:
            self._write_lock.acquire()
            counter = 0
            items = []
            for index,level,data in packets:
                payload_size = len(data)
                actual_size = payload_size
                scb, ecb = None, None
                #fire the start_send_callback just before the first packet is processed:
                if counter==0:
                    scb = start_send_cb
                #fire the end_send callback when the last packet (index==0) makes it out:
                if index==0:
                    ecb = end_send_cb
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
                    log("sending %s bytes encrypted with %s padding", payload_size, len(padding))
                if actual_size<PACKET_JOIN_SIZE:
                    #'p' + protocol-flags + compression_level + packet_index + data_size
                    if type(data)==unicode:
                        data = str(data)
                    header_and_data = struct.pack('!BBBBL%ss' % actual_size, ord("P"), proto_flags, level, index, payload_size, data)
                    items.append((header_and_data, scb, ecb))
                else:
                    header = struct.pack('!BBBBL', ord("P"), proto_flags, level, index, payload_size)
                    items.append((header, scb, None))
                    items.append((data, None, ecb))
                counter += 1
            self._write_queue.put(items)
        finally:
            self.output_packetcount += 1
            self._write_lock.release()

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

    def enable_rencode(self):
        assert rencode_dumps is not None, "rencode cannot be enabled: the module failed to load!"
        log("enable_rencode()")
        self._encoder = self.rencode

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
        level = self._compression_level
        for i in range(1, len(packet)):
            item = packet[i]
            ti = type(item)
            if ti in (int, long, bool, dict, list, tuple):
                continue
            elif ti==Compressed:
                #already compressed data (but not using zlib), send as-is
                packets.append((i, 0, item.data))
                packet[i] = ''
            elif ti==ZLibCompressed:
                #already compressed data as zlib, send as-is with zlib level marker
                assert item.level>0
                packets.append((i, item.level, item.data))
                packet[i] = ''
            elif ti==str and level>0 and len(item)>=4096:
                log.warn("found a large uncompressed item in packet '%s' at position %s: %s bytes", packet[0], i, len(item))
                #add new binary packet with large item:
                if sys.version>='3':
                    item = item.encode("latin1")
                packets.append((i, level, zlib.compress(item, level)))
                #replace this item with an empty string placeholder:
                packet[i] = ''
            elif ti!=str:
                log.info("unexpected data type in %s packet: %s", packet[0], ti)
        #now the main packet (or what is left of it):
        try:
            main_packet, proto_version = self._encoder(packet)
        except (KeyError, TypeError), e:
            if self._closed:
                return [], 0
            log.error("failed to encode packet: %s", packet)
            import traceback
            traceback.print_exc()
            self.verify_packet(packet)
            raise e
        if len(main_packet)>=1024 and packet_in[0] not in self.large_packets:
            log.warn("found large packet (%s bytes): %s, argument types:%s, sizes: %s, packet head=%s",
                     len(main_packet), packet_in[0], [type(x) for x in packet[1:]], [len(str(x)) for x in packet[1:]], repr_ellipsized(packet))
        if level>0:
            data = zlib.compress(main_packet, level)
            packets.append((0, level, data))
        else:
            packets.append((0, 0, main_packet))
        return packets, proto_version

    def set_compression_level(self, level):
        #this may be used next time encode() is called
        self._compression_level = level

    def _write_thread_loop(self):
        try:
            while not self._closed:
                items = self._write_queue.get()
                # Used to signal that we should exit:
                if items is None:
                    log("write thread: empty marker, exiting")
                    break
                for buf, start_cb, end_cb in items:
                    if start_cb:
                        try:
                            start_cb(self._conn.output_bytecount)
                        except:
                            log.error("error on %s", start_cb, exc_info=True)
                    while buf and not self._closed:
                        written = untilConcludes(self._conn.write, buf)
                        if written:
                            buf = buf[written:]
                            self.output_raw_packetcount += 1
                    if end_cb:
                        try:
                            end_cb(self._conn.output_bytecount)
                        except:
                            log.error("error on %s", end_cb, exc_info=True)
            log("write thread: ended")
        except (OSError, IOError, socket.error), e:
            self._call_connection_lost("Error writing to connection: %s" % e)
        except Exception, e:
            #can happen during close(), in which case we just ignore:
            if not self._closed:
                self.close()
                raise e

    def _read_thread_loop(self):
        try:
            while not self._closed:
                try:
                    buf = untilConcludes(self._conn.read, 8192)
                except (ValueError, OSError, IOError, socket.error), e:
                    self._call_connection_lost("Error reading from connection: %s" % e)
                    return
                except Exception, e:
                    if self._closed:
                        return
                    raise e
                #log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
                self._read_queue.put(buf)
                if not buf:
                    log("read thread: eof")
                    break
                self.input_raw_packetcount += 1
        finally:
            log("read thread: ended, closing socket")
            self.close()

    def _call_connection_lost(self, message="", exc_info=False):
        log("will call connection lost: %s", message)
        gobject.idle_add(self._connection_lost, message, exc_info)

    def _connection_lost(self, message="", exc_info=False):
        log.info("connection lost: %s", message, exc_info=exc_info)
        self.close()
        return False

    def _read_parse_thread_loop(self):
        try:
            self.do_read_parse_thread_loop()
        except Exception, e:
            log.error("error in read parse loop", exc_info=True)
            self._call_connection_lost("error in network packet reading/parsing: %s" % e)

    def do_read_parse_thread_loop(self):
        """
            Process the individual network packets placed in _read_queue.
            We concatenate them, then try to parse them.
            We extract the individual packets from the potentially large buffer,
            saving the rest of the buffer for later, and optionally decompress this data
            and re-construct the one python-object-packet from potentially multiple packets (see packet_index).
            The 8 bytes packet header gives us information on the packet index, packet size and compression.
            The actual processing of the packet is done in the main thread via gobject.idle_add
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
                gobject.idle_add(self.close)
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
                    if read_buffer[0] not in ["P", ord("P")]:
                        return self._call_connection_lost("invalid packet header: ('%s...'), not an xpra client?" % read_buffer[:32])
                    if bl<8:
                        break   #packet still too small
                    #packet format: struct.pack('cBBBL', ...) - 8 bytes
                    try:
                        _, protocol_flags, compression_level, packet_index, data_size = struct.unpack_from('!cBBBL', read_buffer)
                    except Exception, e:
                        raise Exception("invalid packet header: %s" % list(read_buffer[:8]), e)
                    read_buffer = read_buffer[8:]
                    bl = len(read_buffer)
                    if protocol_flags & Protocol.FLAGS_CIPHER:
                        assert self.cipher_in_block_size>0, "received cipher block but we don't have a cipher do decrypt it with"
                        padding = (self.cipher_in_block_size - data_size % self.cipher_in_block_size) * " "
                        payload_size = data_size + len(padding)
                    else:
                        #no cipher, no padding:
                        padding = None
                        payload_size = data_size
                    assert payload_size>0

                if payload_size>self.max_packet_size:
                    #this packet is seemingly too big, but check again from the main UI thread
                    #this gives 'set_max_packet_size' a chance to run from "hello"
                    def check_packet_size(size_to_check, packet_header):
                        log("check_packet_size(%s, %s) limit is %s", size_to_check, packet_header, self.max_packet_size)
                        if size_to_check>self.max_packet_size:
                            return self._call_connection_lost("invalid packet: size requested is %s (maximum allowed is %s - packet header: '%s'), dropping this connection!" %
                                                              (size_to_check, self.max_packet_size, packet_header))
                    gobject.timeout_add(1000, check_packet_size, payload_size, read_buffer[:32])

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
                    log("received %s encrypted bytes with %s padding", payload_size, len(padding))
                    data = self.cipher_in.decrypt(raw_string)
                    if padding:
                        assert data.endswith(padding), "decryption failed: string does not end with '%s': %s (%s) -> %s (%s)" % (padding, list(bytearray(raw_string)), type(raw_string), list(bytearray(data)), type(data))
                        data = data[:-len(padding)]
                #uncompress if needed:
                if compression_level>0:
                    if self.chunked_compression:
                        data = zlib.decompress(data)
                    else:
                        data = self._decompressor.decompress(data)
                if sys.version>='3':
                    data = data.decode("latin1")

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
                        assert has_rencode, "we don't support rencode mode but the other end sent us a rencoded packet!"
                        packet = list(rencode_loads(data))
                    else:
                        packet, l = bdecode(data)
                        assert l==len(data)
                except ValueError, e:
                    import traceback
                    traceback.print_exc()
                    log.error("value error reading packet: %s", e)
                    if self._closed:
                        return
                    def gibberish(buf):
                        # Peek at the data we got, in case we can make sense of it:
                        self._process_packet_cb(self, [Protocol.GIBBERISH, buf])
                        # Then hang up:
                        return self._connection_lost("gibberish received: %s, packet index=%s, packet size=%s, buffer size=%s, error=%s" % (repr_ellipsized(data), packet_index, payload_size, bl, e))
                    gobject.idle_add(gibberish, data)
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
                try:
                    self._process_packet_cb(self, packet)
                    self.input_packetcount += 1
                except KeyboardInterrupt:
                    raise
                except:
                    log.warn("Unhandled error while processing a '%s' packet from peer", packet[0], exc_info=True)

    def flush_then_close(self, last_packet):
        try:
            self._write_lock.acquire()
            #try to wait for the queue to empty with the lock held
            try:
                import time
                i = 0
                while not self._closed and not self._write_queue.empty() and i<5:
                    time.sleep(0.1)
                    i += 1
            except:
                pass
            #and send our last_packet to it:
            self._add_packet_to_queue(last_packet)
        finally:
            self._write_lock.release()
        self.terminate_io_threads()
        #wait for last_packet to be sent:
        def wait_for_end_of_write(timeout=15):
            log("wait_for_end_of_write(%s) closed=%s, size=%s", timeout, self._closed, self._write_queue.qsize())
            if self._closed:
                """ client has disconnected """
                return
            if self._write_queue.empty() or timeout<=0:
                """ threads have terminated or we timedout """
                self.close()
            else:
                """ check again soon: """
                gobject.timeout_add(200, wait_for_end_of_write, timeout-1)
        wait_for_end_of_write()

    def close(self):
        if self._closed:
            return
        self._closed = True
        gobject.idle_add(self._process_packet_cb, self, [Protocol.CONNECTION_LOST])
        if self._conn:
            try:
                self._conn.close()
                log.info("connection closed after %s packets received (%s bytes) and %s packets sent (%s bytes)",
                         self.input_packetcount, self._conn.input_bytecount,
                         self.output_packetcount, self._conn.output_bytecount
                         )
            except:
                log.error("error closing %s", self._conn, exc_info=True)
            self._conn = None
        self.terminate_io_threads()
        gobject.idle_add(self.clean)

    def clean(self):
        #clear all references to ensure we can get garbage collected quickly:
        self._get_packet_cb = None
        self._encoder = None
        self._write_thread = None
        self._read_thread = None
        self._read_parser_thread = None
        self._process_packet_cb = None

    def terminate_io_threads(self):
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
