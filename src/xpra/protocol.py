# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# oh gods it's threads

# but it works on win32, for whatever that's worth.

import gobject
gobject.threads_init()
import os
import socket # for socket.error
import zlib
import errno

try:
    from queue import Queue     #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue     #@Reimport
from threading import Thread, Lock

from xpra.bencode import bencode, bdecode

from wimpiggy.log import Logger
log = Logger()

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
        #initial value which may get increased by client/server after handshake:
        self.max_packet_size = 32*1024
        self._recv_counter = 0
        self._closed = False
        self._read_buffer = ""
        self._compressor = None
        self._decompressor = None
        self._write_thread = Thread(target=self._write_thread_loop)
        self._write_thread.name = "write_loop"
        self._write_thread.daemon = True
        self._write_thread.start()
        self._write_lock = Lock()
        self._read_thread = Thread(target=self._read_thread_loop)
        self._read_thread.name = "read_loop"
        self._read_thread.daemon = True
        self._read_thread.start()
        self._read_parser_thread = Thread(target=self._read_parse_thread_loop)
        self._read_parser_thread.name = "read_parse_loop"
        self._read_parser_thread.deamon = True
        self._read_parser_thread.start()
        self._maybe_queue_more_writes()

    def source_has_more(self):
        assert self.source is not None
        self._source_has_more = True
        self._maybe_queue_more_writes()

    def _maybe_queue_more_writes(self):
        if self._write_queue.empty() and self._source_has_more:
            self._flush_one_packet_into_buffer()
        return False

    def _queue_write(self, data, flush=False):
        if len(data)==0:
            return
        if self._compressor is None:
            self._write_queue.put(data)
            return
        c = self._compressor.compress(data)
        if c:
            self._write_queue.put(c)
        if not flush:
            return
        c = self._compressor.flush(zlib.Z_SYNC_FLUSH)
        if c:
            self._write_queue.put(c)

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
        packet, self._source_has_more = self.source.next_packet()
        if packet is not None:
            self._add_packet_to_queue(packet)

    def _add_packet_to_queue(self, packet):
        try:
            data = bencode(packet)
        except KeyError or TypeError, e:
            self.verify_packet(packet)
            raise e
        l = len(data)
        self._write_lock.acquire()
        try:
            try:
                if l<=8192:
                    #send size and data together (low copy overhead):
                    self._queue_write("PS%014d%s" % (l, data), True)
                    return
                self._queue_write("PS%014d" % l)
                self._queue_write(data, True)
            finally:
                if packet[0]=="set_deflate":
                    level = packet[1]
                    log("set_deflate packet, changing compressor to level=%s", level)
                    if level==0:
                        self._compressor = None
                    else:
                        self._compressor = zlib.compressobj(level)
        finally:
            self._write_lock.release()

    def _write_thread_loop(self):
        try:
            while True:
                buf = self._write_queue.get()
                # Used to signal that we should exit:
                if buf is None:
                    log("write thread: empty marker, exiting")
                    break
                try:
                    while buf and not self._closed:
                        written = untilConcludes(self._conn.write, buf)
                        buf = buf[written:]
                except (OSError, IOError, socket.error), e:
                    self._call_connection_lost("Error writing to connection: %s" % e)
                    break
                except TypeError:
                    assert self._closed
                    break
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
                log("read thread: got data %s", repr_ellipsized(buf))
                self._recv_counter += len(buf)
                self._read_queue.put(buf)
                if not buf:
                    log("read thread: eof")
                    break
        finally:
            log("read thread: ended, closing socket")
            self.close()

    def _call_connection_lost(self, message="", exc_info=False):
        gobject.idle_add(self._connection_lost, message, exc_info)

    def _connection_lost(self, message="", exc_info=False):
        log.info("connection lost: %s", message, exc_info=exc_info)
        self.close()
        self._process_packet_cb(self, [Protocol.CONNECTION_LOST])
        return False

    def _read_parse_thread_loop(self):
        try:
            current_packet_size = -1
            while not self._closed:
                buf = self._read_queue.get()
                if not buf:
                    return self._call_connection_lost("empty marker in read queue")
                if self._decompressor is not None:
                    buf = self._decompressor.decompress(buf)
                if self._read_buffer:
                    self._read_buffer = self._read_buffer + buf
                else:
                    self._read_buffer = buf
                bl = len(self._read_buffer)
                if self.max_packet_size>0 and bl>self.max_packet_size:
                    return self._call_connection_lost("read buffer too big: %s (maximum is %s), dropping this connection!" % (bl, self.max_packet_size))
                while not self._closed:
                    bl = len(self._read_buffer)
                    if bl<=0:
                        break
                    try:
                        if current_packet_size<0 and bl>0 and self._read_buffer[0]=="P":
                            #spotted packet size header
                            if bl<16:
                                break   #incomplete
                            current_packet_size = int(self._read_buffer[2:16])
                            self._read_buffer = self._read_buffer[16:]
                            bl = len(self._read_buffer)

                        if current_packet_size>0 and bl<current_packet_size:
                            log.debug("incomplete packet: only %s of %s bytes received", bl, current_packet_size)
                            break

                        result = bdecode(self._read_buffer)
                    except ValueError, e:
                        #could be a partial packet (without size header)
                        #or could be just a broken packet...
                        def packet_error(buf, packet_size, data_size, value_error):
                            if self._closed:
                                return
                            # Peek at the data we got, in case we can make sense of it:
                            self._process_packet([Protocol.GIBBERISH, buf])
                            # Then hang up:
                            return self._connection_lost("gibberish received: %s, packet size=%s, buffer size=%s, error=%s" % (repr_ellipsized(buf), packet_size, data_size, value_error))

                        if current_packet_size>0:
                            #we had the size, so the packet should have been valid!
                            packet_error(self._read_buffer, current_packet_size, bl, e)
                            return
                        else:
                            #wait a little before deciding
                            #unsized packets are either old clients (don't really care about them)
                            #or hello packets (small-ish)
                            def check_error_state(old_buffer, packet_size, data_size, value_error):
                                log.info("check_error_state old_buffer=%s, read buffer=%s", old_buffer, self._read_buffer)
                                if old_buffer==self._read_buffer:
                                    packet_error(self._read_buffer, packet_size, data_size, value_error)
                            log.info("error parsing packet without a size header: %s, current_packet_size=%s, will check again in 1 second", e, current_packet_size)
                            gobject.timeout_add(1000, check_error_state, self._read_buffer, current_packet_size, bl, e)
                            break

                    current_packet_size = -1
                    if result is None or self._closed:
                        break
                    packet, l = result
                    gobject.idle_add(self._process_packet, packet)
                    unprocessed = self._read_buffer[l:]
                    if packet[0]=="set_deflate":
                        had_deflate = (self._decompressor is not None)
                        level = packet[1]
                        log("set_deflate packet, changing decompressor to level=%s", level)
                        if level==0:
                            self._decompressor = None
                        else:
                            self._decompressor = zlib.decompressobj()
                        if not had_deflate and (self._decompressor is not None):
                            # deflate was just enabled: so decompress the unprocessed
                            # data
                            unprocessed = self._decompressor.decompress(unprocessed)
                    self._read_buffer = unprocessed
        finally:
            log("read parse thread: ended")

    def _process_packet(self, decoded):
        if self._closed:
            log.warn("Ignoring stray packet read after connection"
                     " allegedly closed (%s)", dump_packet(decoded))
            return
        try:
            self._process_packet_cb(self, decoded)
        except KeyboardInterrupt:
            raise
        except:
            log.warn("Unhandled error while processing packet from peer",
                     exc_info=True)
            # Ignore and continue, maybe things will work out anyway
        return False


    def enable_deflate(self, level):
        assert self._compressor is None and self._decompressor is None
        # Flush everything out of the source
        while self._source_has_more:
            self._flush_one_packet_into_buffer()
        # Now enable compression
        self._compressor = zlib.compressobj(level)
        self._decompressor = zlib.decompressobj()

    def flush_then_close(self, last_packet):
        self._add_packet_to_queue(last_packet)
        self.terminate_io_threads()
        #wait for last_packet to be sent:
        def wait_for_end_of_write(timeout=15):
            log.debug("wait_for_end_of_write(%s) closed=%s, size=%s", timeout, self._closed, self._write_queue.qsize())
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
        self._closed = True
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
