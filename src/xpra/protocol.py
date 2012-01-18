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

from Queue import Queue
from threading import Thread, Lock

from xpra.bencode import bencode, bdecode

from wimpiggy.log import Logger
log = Logger()

# A simple, portable abstraction for a blocking, low-level
# (os.read/os.write-style interface) two-way byte stream:

class TwoFileConnection(object):
    def __init__(self, writeable, readable):
        self._writeable = writeable
        self._readable = readable

    def read(self, n):
        return os.read(self._readable.fileno(), n)

    def write(self, buf):
        return os.write(self._writeable.fileno(), buf)

    def close(self):
        self._writeable.close()
        self._readable.close()

class SocketConnection(object):
    def __init__(self, s):
        self._s = s

    def read(self, n):
        return self._s.recv(n)

    def write(self, buf):
        return self._s.send(buf)

    def close(self):
        return self._s.close()
        
def repr_ellipsized(obj, limit=100):
    if isinstance(obj, str) and len(obj) > limit:
        return repr(obj[:limit]) + "..."
    else:
        return repr(obj)

def dump_packet(packet):
    return "[" + ", ".join([repr_ellipsized(str(x), 50) for x in packet]) + "]"


class Protocol(object):
    CONNECTION_LOST = object()
    GIBBERISH = object()

    def __init__(self, conn, process_packet_cb):
        self._conn = conn
        self._process_packet_cb = process_packet_cb
        self._write_queue = Queue()
        self._read_queue = Queue(5)
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self._source_has_more = False
        self._recv_counter = 0
        self._send_size = False
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

    def _flush_one_packet_into_buffer(self):
        if not self.source:
            return
        packet, self._source_has_more = self.source.next_packet()
        if packet is not None:
            data = bencode(packet)
            l = len(data)
            self._write_lock.acquire()
            try:
                try:
                    if self._send_size:
                        if l<=1024:
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
                        buf = buf[self._conn.write(buf):]
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
            self._conn.close()

    def _read_thread_loop(self):
        try:
            while not self._closed:
                try:
                    buf = self._conn.read(8192)
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
            self._conn.close()

    def _call_connection_lost(self, message="", exc_info=False):
        gobject.idle_add(self._connection_lost, message, exc_info)

    def _connection_lost(self, message="", exc_info=False):
        log.info("connection lost: %s", message, exc_info=exc_info)
        if not self._closed:
            self._process_packet_cb(self, [Protocol.CONNECTION_LOST])
            self.close()
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
                while not self._closed and len(self._read_buffer)>0:
                    had_deflate = (self._decompressor is not None)
                    try:
                        if current_packet_size<0 and len(self._read_buffer)>0 and self._read_buffer[0]=="P":
                            #spotted packet size header
                            if len(self._read_buffer)<16:
                                break   #incomplete
                            current_packet_size = int(self._read_buffer[2:16])
                            self._read_buffer = self._read_buffer[16:]

                        if current_packet_size>0 and len(self._read_buffer)<current_packet_size:
                            log.debug("incomplete packet: only %s of %s bytes received", len(self._read_buffer), current_packet_size)
                            break

                        result = bdecode(self._read_buffer)
                    except ValueError:
                        #could be a partial packet (without size header)
                        #or could be just a broken packet...
                        def packet_error(buf):
                            if self._closed:
                                return
                            # Peek at the data we got, in case we can make sense of it:
                            self._process_packet([Protocol.GIBBERISH, buf])
                            # Then hang up:
                            return self._connection_lost("gibberish received: %s" % repr_ellipsized(buf))

                        if current_packet_size>0:
                            #we had the size, so the packet should have been valid!
                            packet_error(self._read_buffer)
                            return
                        else:
                            #wait a little before deciding
                            #unsized packets are either old clients (don't really care about them)
                            #or hello packets (small-ish)
                            def check_error_state(old_buffer):
                                if old_buffer==self._read_buffer:
                                    packet_error(self._read_buffer)
                            gobject.timeout_add_seconds(1000, check_error_state, self._read_buffer)
                            break

                    current_packet_size = -1
                    if result is None or self._closed:
                        break
                    packet, l = result
                    gobject.idle_add(self._process_packet, packet)
                    unprocessed = self._read_buffer[l:]
                    if packet[0]=="set_deflate":
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

    def close(self):
        if not self._closed:
            self._closed = True
        #make the threads exit by adding the empty marker:
        self._write_queue.put(None)
        try:
            self._read_queue.put_nowait(None)
        except:
            pass
