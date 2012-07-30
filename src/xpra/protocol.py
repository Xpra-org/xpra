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
import os
import socket # for socket.error
import zlib
import errno
import struct

try:
    from queue import Queue     #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue     #@Reimport
from threading import Thread, Lock

from wimpiggy.log import Logger
log = Logger()

from xpra.bencode import bencode, bdecode
has_rencode = False
try:
    from xpra.rencode import dumps as rencode_dumps  #@UnresolvedImport
    from xpra.rencode import loads as rencode_loads  #@UnresolvedImport
    has_rencode = True
except Exception, e:
    log.error("xpra.rencode is missing: %s" % e)
    rencode_dumps, rencode_loads = None, None


# A simple, portable abstraction for a blocking, low-level
# (os.read/os.write-style interface) two-way byte stream:

class TwoFileConnection(object):
    def __init__(self, writeable, readable, abort_test=None, target=None):
        self._writeable = writeable
        self._readable = readable
        self._abort_test = abort_test
        self.target = target

    def may_abort(self, action):
        """ if abort_test is defined, run it """
        if self._abort_test:
            self._abort_test(action)

    def read(self, n):
        self.may_abort("read")
        return os.read(self._readable.fileno(), n)

    def write(self, buf):
        self.may_abort("write")
        return os.write(self._writeable.fileno(), buf)

    def close(self):
        self._writeable.close()
        self._readable.close()

    def __str__(self):
        return "TwoFileConnection(%s)" % str(self.target)

class SocketConnection(object):
    def __init__(self, s, target):
        self._s = s
        self.target = target

    def read(self, n):
        return self._s.recv(n)

    def write(self, buf):
        return self._s.send(buf)

    def close(self):
        return self._s.close()

    def __str__(self):
        return "SocketConnection(%s)" % str(self.target)

def repr_ellipsized(obj, limit=100):
    if isinstance(obj, str) and len(obj) > limit:
        return repr(obj[:limit]) + "..."
    else:
        return repr(obj)

def dump_packet(packet):
    return "[" + ", ".join([repr_ellipsized(str(x), 50) for x in packet]) + "]"

def untilConcludes(f, *a, **kw):
    while True:
        try:
            return f(*a, **kw)
        except (IOError, OSError), e:
            if e.args[0] == errno.EINTR:
                continue
            raise

class Compressible(object):
    def __init__(self, datatype, data):
        self.datatype = datatype
        self.data = data
    def __len__(self):
        return len(self.data)

class Protocol(object):
    CONNECTION_LOST = "connection-lost"
    GIBBERISH = "gibberish"

    def __init__(self, conn, process_packet_cb):
        assert conn is not None
        self._conn = conn
        self._process_packet_cb = process_packet_cb
        self._write_queue = Queue()
        self._read_queue = Queue(5)
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self._source_has_more = False
        #counters:
        self.input_bytecount = 0
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_bytecount = 0
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        #initial value which may get increased by client/server after handshake:
        self.max_packet_size = 32*1024
        self._closed = False
        self._encoder = self.bencode
        self._compressor = None
        self._decompressor = zlib.decompressobj()
        self._compression_level = 0
        def make_daemon_thread(target, name):
            daemon_thread = Thread(target=target, name=name)
            daemon_thread.setDaemon(True)
            return daemon_thread
        self._write_lock = Lock()
        self._write_thread = make_daemon_thread(self._write_thread_loop, "write_loop")
        self._read_thread = make_daemon_thread(self._read_thread_loop, "read_loop")
        self._read_parser_thread = make_daemon_thread(self._read_parse_thread_loop, "read_parse_loop")

    def __str__(self):
        return "Protocol(%s)" % self._conn

    def start(self):
        self._write_thread.start()
        self._read_thread.start()
        self._read_parser_thread.start()
        self._maybe_queue_more_writes()

    def source_has_more(self):
        assert self.source is not None
        self._source_has_more = True
        if self._write_queue.empty():
            self._flush_one_packet_into_buffer()

    def _maybe_queue_more_writes(self):
        if self._write_queue.empty() and self._source_has_more:
            self._flush_one_packet_into_buffer()
        return False

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

    def _flush_one_packet_into_buffer(self):
        if not self.source:
            return
        packet, start_send_cb, end_send_cb, self._source_has_more = self.source.next_packet()
        if packet is not None:
            self._add_packet_to_queue(packet, start_send_cb, end_send_cb)

    def enable_rencode(self):
        assert rencode_dumps is not None, "rencode cannot be enabled: the module failed to load!"
        log("enable_rencode()")
        self._encoder = self.rencode

    def bencode(self, data):
        return  bencode(data), 0

    def rencode(self, data):
        return  rencode_dumps(data), 1

    def encode(self, packet):
        """
        Given a packet (tuple or list of items), converts it for the wire.
        This method returns all the binary packets to send, as an array of:
        (index, may_compress, binary_data)
        The index, if positive indicates the item to populate in the packet
        whose index is zero.
        ie: ["blah", [large binary data], "hello", 200]
        may get converted to:
        [
            (1, False, [large binary data]),
            (0, True, bencoded/rencoded(["blah", '', "hello", 200]))
        ]
        """
        packets = []
        for i in range(len(packet)):
            item = packet[i]
            if type(item)==str and len(item)>=4096:
                #add new binary packet with large item:
                if sys.version>='3':
                    item = item.encode("latin1")
                packets.append((i, False, item))
                #replace this item with an empty string placeholder:
                packet[i] = ''
            elif type(item)==Compressible:
                #this is binary, but we *DO* want to compress it since it isn't compressed yet!
                packets.append((i, True, item.data))
                packet[i] = ''
        #now the main packet (or what is left of it):
        try:
            main_packet, proto_version = self._encoder(packet)
        except KeyError or TypeError, e:
            import traceback
            traceback.print_exc()
            self.verify_packet(packet)
            raise e
        if sys.version>='3':
            main_packet = main_packet.encode("latin1")
        packets.append((0, True, main_packet))
        return packets, proto_version

    def _add_packet_to_queue(self, packet, start_send_cb=None, end_send_cb=None):
        packets, proto_version = self.encode(packet)
        try:
            self._write_lock.acquire()
            counter = 0
            for index,compress,udata in packets:
                if compress and self._compression_level>0:
                    #make a reference copy
                    #(as another thread could clear it - see set_compression)
                    compressor = self._compressor
                    level = self._compression_level
                    if compressor is None:
                        self._compressor = zlib.compressobj(level)
                        compressor = self._compressor
                    cdata = compressor.compress(udata)+compressor.flush(zlib.Z_SYNC_FLUSH)
                else:
                    level = 0
                    cdata = udata
                l = len(cdata)
                #'p' + protocol-version + compression_level + packet_index + packet_size
                header = struct.pack('!cBBBL', "P", proto_version, level, index, l)
                scb, ecb = None, None
                #fire the start_send_callback just before the first packet is processed:
                if counter==0:
                    scb = start_send_cb
                #fire the end_send callback when the last packet (index==0) makes it out:
                if index==0:
                    ecb = end_send_cb
                self._write_queue.put((header, scb, None))
                self._write_queue.put((cdata, None, ecb))
                counter += 1
        finally:
            self.output_packetcount += 1
            self._write_lock.release()

    def set_compression_level(self, level):
        #we just clear it, and let _add_packet_to_queue re-initialize it
        self._compressor = None
        self._compression_level = level

    def _write_thread_loop(self):
        try:
            while True:
                item = self._write_queue.get()
                # Used to signal that we should exit:
                if item is None:
                    log("write thread: empty marker, exiting")
                    break
                buf, start_cb, end_cb = item
                try:
                    if start_cb:
                        start_cb(self.output_bytecount)
                    while buf and not self._closed:
                        written = untilConcludes(self._conn.write, buf)
                        if written:
                            buf = buf[written:]
                            self.output_raw_packetcount += 1
                            self.output_bytecount += written
                    if end_cb:
                        end_cb(self.output_bytecount)
                except (OSError, IOError, socket.error), e:
                    self._call_connection_lost("Error writing to connection: %s" % e)
                    break
                except TypeError:
                    #can happen during close(), in which case we just ignore:
                    if self._closed:
                        break
                    raise
                if self._write_queue.empty():
                    gobject.idle_add(self._maybe_queue_more_writes)
        finally:
            log("write thread: ended, closing socket")
            self.close()

    def _read_thread_loop(self):
        try:
            while not self._closed:
                try:
                    buf = untilConcludes(self._conn.read, 8192)
                except (ValueError, OSError, IOError, socket.error), e:
                    self._call_connection_lost("Error reading from connection: %s" % e)
                    return
                except TypeError:
                    assert self._closed
                    return
                log("read thread: got data of size %s: %s", len(buf), repr_ellipsized(buf))
                self._read_queue.put(buf)
                if not buf:
                    log("read thread: eof")
                    break
                self.input_raw_packetcount += 1
                self.input_bytecount += len(buf)
        finally:
            log("read thread: ended, closing socket")
            self.close()

    def _call_connection_lost(self, message="", exc_info=False):
        gobject.idle_add(self._connection_lost, message, exc_info)

    def _connection_lost(self, message="", exc_info=False):
        log.info("connection lost: %s", message, exc_info=exc_info)
        self.close()
        return False

    def _read_parse_thread_loop(self):
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
        current_packet_size = -1
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
                if current_packet_size<0:
                    if read_buffer[0] not in ["P", ord("P")]:
                        return self._call_connection_lost("invalid packet header: ('%s...'), not an xpra client?" % read_buffer[:32])
                    if bl<8:
                        break   #packet still too small
                    if read_buffer[1] in ["S", ord("S")]:
                        #old packet format: "PS%02d%012d" - 16 bytes
                        #can be dropped when we drop compatibility with clients older than 0.5
                        #0.3 and 0.4 still send the initial "hello" packet using this old format..
                        if bl<16:
                            break
                        current_packet_size = int(read_buffer[2:16])
                        packet_index = 0
                        compression_level = 0
                        protocol_version = 0        #only bencode supported with old protocol
                        read_buffer = read_buffer[16:]
                    else:
                        #packet format: struct.pack('cBBBL', ...) - 8 bytes
                        try:
                            (_, protocol_version, compression_level, packet_index, current_packet_size) = struct.unpack_from('!cBBBL', read_buffer)
                        except Exception, e:
                            raise Exception("invalid packet format: %s", e)
                        read_buffer = read_buffer[8:]
                    bl = len(read_buffer)

                if current_packet_size>self.max_packet_size:
                    #this packet is seemingly too big, but check again from the main UI thread
                    #this gives 'set_max_packet_size' a chance to run
                    def check_packet_size(size_to_check):
                        log("check_packet_size(%s) limit is %s", size_to_check, self.max_packet_size)
                        if size_to_check>self.max_packet_size:
                            return self._call_connection_lost("invalid packet: size requested is %s (maximum allowed is %s), dropping this connection!" %
                                                              (size_to_check, self.max_packet_size))
                    gobject.idle_add(check_packet_size, current_packet_size)

                if current_packet_size>0 and bl<current_packet_size:
                    # incomplete packet, wait for the rest to arrive
                    break

                #chop this packet from the buffer:
                if len(read_buffer)==current_packet_size:
                    raw_string = read_buffer
                    read_buffer = ''
                else:
                    raw_string = read_buffer[:current_packet_size]
                    read_buffer = read_buffer[current_packet_size:]
                if compression_level>0:
                    raw_string = self._decompressor.decompress(raw_string)
                if sys.version>='3':
                    raw_string = raw_string.decode("latin1")

                if self._closed:
                    return
                if packet_index>0:
                    #raw packet, store it and continue:
                    raw_packets[packet_index] = raw_string
                    current_packet_size = -1
                    packet_index = 0
                    continue
                result = None
                try:
                    #final packet (packet_index==0), decode it:
                    if protocol_version==0:
                        result = bdecode(raw_string)
                        if result is None:
                            break
                        packet, l = result
                        assert l==len(raw_string)
                    elif protocol_version==1:
                        assert has_rencode, "we don't support rencode mode but the other end sent us an rencoded packet!"
                        packet = list(rencode_loads(raw_string))
                    else:
                        raise Exception("unsupported protocol version: %s" % protocol_version)
                except ValueError, e:
                    import traceback
                    traceback.print_exc()
                    log.error("value error reading packet: %s", e)
                    if self._closed:
                        return
                    def gibberish(buf):
                        # Peek at the data we got, in case we can make sense of it:
                        self._process_packet([Protocol.GIBBERISH, buf])
                        # Then hang up:
                        return self._connection_lost("gibberish received: %s, packet index=%s, packet size=%s, buffer size=%s, error=%s" % (repr_ellipsized(raw_string), packet_index, current_packet_size, bl, e))
                    gobject.idle_add(gibberish, raw_string)
                    return

                if self._closed:
                    return
                current_packet_size = -1
                #add any raw packets back into it:
                if raw_packets:
                    for index,raw_data in raw_packets.items():
                        #replace placeholder with the raw_data packet data:
                        packet[index] = raw_data
                    raw_packets = {}
                gobject.idle_add(self._process_packet, packet)

    def _process_packet(self, decoded):
        if self._closed:
            log.warn("Ignoring stray packet read after connection"
                     " allegedly closed (%s)", dump_packet(decoded))
            return
        try:
            self._process_packet_cb(self, decoded)
            self.input_packetcount += 1
        except KeyboardInterrupt:
            raise
        except:
            log.warn("Unhandled error while processing packet from peer",
                     exc_info=True)
            # Ignore and continue, maybe things will work out anyway
        return False

    def flush_then_close(self, last_packet):
        self._add_packet_to_queue(last_packet)
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
                self._conn = None
            except:
                log.error("error closing %s", self._conn, exc_info=True)
        self.terminate_io_threads()

    def terminate_io_threads(self):
        #make the threads exit by adding the empty marker:
        self._write_queue.put(None)
        try:
            self._read_queue.put_nowait(None)
        except:
            pass
