# This file is part of Parti.
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

from Queue import Queue, Empty
from threading import Thread

from xpra.bencode import bencode, IncrBDecode

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
    return "[" + ", ".join([repr_ellipsized(x, 50) for x in packet]) + "]"

def main_thread_call(fn, *args, **kwargs):
    log("Queueing main thread call to %s" % (fn,))
    def cb(*foo):
        fn(*args, **kwargs)
        return False
    gobject.timeout_add(0, cb)

class Protocol(object):
    CONNECTION_LOST = object()
    GIBBERISH = object()

    def __init__(self, conn, process_packet_cb):
        self._conn = conn
        self._process_packet_cb = process_packet_cb
        self._write_queue = Queue()
        self._read_queue = Queue()
        # Invariant: if .source is None, then _source_has_more == False
        self.source = None
        self.jpegquality = 0
        self._source_has_more = False
        self._closed = False
        self._read_decoder = IncrBDecode()
        self._compressor = None
        self._decompressor = None
        self._write_thread = Thread(target=self._write_thread_loop)
        self._write_thread.daemon = True
        self._write_thread.start()
        self._read_thread = Thread(target=self._read_thread_loop)
        self._read_thread.daemon = True
        self._read_thread.start()
        self._maybe_queue_more_writes()

    def source_has_more(self):
        assert self.source is not None
        self._source_has_more = True
        self._maybe_queue_more_writes()

    def _maybe_queue_more_writes(self):
        if self._write_queue.empty() and self._source_has_more:
            self._flush_one_packet_into_buffer()

    def _flush_one_packet_into_buffer(self):
        if not self.source:
            return
        packet, self._source_has_more = self.source.next_packet()
        if packet is not None:
            log("writing %s", dump_packet(packet), type="raw.write")
            data_payload = bencode(packet)
            data = data_payload
            if self._compressor is not None:
                self._write_queue.put(self._compressor.compress(data))
                self._write_queue.put(self._compressor.flush(zlib.Z_SYNC_FLUSH))
            else:
                self._write_queue.put(data)

    def _write_thread_loop(self):
        while not self._closed:
            log("write thread: waiting for data to write")
            buf = self._write_queue.get()
            # Used to signal that we should exit:
            if buf is None:
                return
            try:
                while buf:
                    log("write thread: writing %s", repr_ellipsized(buf))
                    buf = buf[self._conn.write(buf):]
            except (OSError, IOError, socket.error), e:
                log.info("Error writing to connection: %s", e)
                main_thread_call(self._connection_lost)
                return
            except TypeError:
                assert self._closed
                return
            if self._write_queue.empty():
                main_thread_call(self._maybe_queue_more_writes)
        return False

    def _read_thread_loop(self):
        while not self._closed:
            log("read thread: waiting for data to arrive")
            try:
                buf = self._conn.read(8192)
            except (ValueError, OSError, IOError, socket.error), e:
                log.info("Error reading from connection: %s", e)
                main_thread_call(self._connection_lost)
                return
            except TypeError:
                assert self._closed
                return
            log("read thread: got data %s", repr_ellipsized(buf))
            self._read_queue.put(buf)
            main_thread_call(self._handle_read)

    def _connection_lost(self):
        log("_connection_lost")
        if not self._closed:
            self._process_packet_cb(self, [Protocol.CONNECTION_LOST])
            self.close()

    def _handle_read(self):
        log("main thread: woken to handle read data")
        while True:
            try:
                buf = self._read_queue.get(block=False)
                log("main thread: found read data %s", repr_ellipsized(buf))
            except Empty:
                log("main thread: processed all read data")
                return
            if not buf:
                self._connection_lost()
                return
            if self._decompressor is not None:
                buf = self._decompressor.decompress(buf)
            self._read_decoder.add(buf)
            while True:
                had_deflate = (self._decompressor is not None)
                try:
                    result = self._read_decoder.process()
                except ValueError:
                    # Peek at the data we got, in case we can make sense of it:
                    self._process_packet([Protocol.GIBBERISH,
                                          self._read_decoder.unprocessed()])
                    # Then hang up:
                    self._connection_lost()
                    return
                if result is None:
                    break
                packet, unprocessed = result
                self._process_packet(packet)
                if not had_deflate and (self._decompressor is not None):
                    # deflate was just enabled: so decompress the unprocessed
                    # data
                    unprocessed = self._decompressor.decompress(unprocessed)
                self._read_decoder = IncrBDecode(unprocessed)
        return False

    def _process_packet(self, decoded):
        if self._closed:
            log.warn("Ignoring stray packet read after connection"
                     " allegedly closed (%s)", dump_packet(decoded))
            return
        try:
            log("got %s", dump_packet(decoded), type="raw.read")
            self._process_packet_cb(self, decoded)
        except KeyboardInterrupt:
            raise
        except:
            log.warn("Unhandled error while processing packet from peer",
                     exc_info=True)
            # Ignore and continue, maybe things will work out anyway

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
            self._write_queue.put(None)
            self._closed = True
            self._conn.close()
