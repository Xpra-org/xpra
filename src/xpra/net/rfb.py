# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from socket import error as socket_error
import binascii
from threading import Lock


from xpra.log import Logger
log = Logger("network", "protocol", "rfb")

from xpra.os_util import Queue
from xpra.util import repr_ellipsized, envint
from xpra.make_thread import make_thread, start_thread
from xpra.net.common import ConnectionClosedException          #@UndefinedVariable (pydev false positive)
from xpra.net.bytestreams import ABORT

READ_BUFFER_SIZE = envint("XPRA_READ_BUFFER_SIZE", 65536)
#merge header and packet if packet is smaller than:
PIXEL_FORMAT = "BBBBHHHBBBBBB"

RFB_SETPIXELFORMAT = 0
RFB_SETENCODINGS = 2
RFB_FRAMEBUFFERUPDATEREQUEST = 3
RFB_KEYEVENT = 4
RFB_POINTEREVENT = 5
RFB_CLIENTCUTTEXT = 6
PACKET_TYPE = {
    RFB_SETPIXELFORMAT              : "SetPixelFormat",
    RFB_SETENCODINGS                : "SetEncodings",
    RFB_FRAMEBUFFERUPDATEREQUEST    : "FramebufferUpdateRequest",
    RFB_KEYEVENT                    : "KeyEvent",
    RFB_POINTEREVENT                : "PointerEvent",
    RFB_CLIENTCUTTEXT               : "ClientCutText",
    }
PACKET_FMT = {
    RFB_SETPIXELFORMAT              : "!BBBB"+PIXEL_FORMAT,
    RFB_SETENCODINGS                : "!BBH",
    RFB_FRAMEBUFFERUPDATEREQUEST    : "!BBHHHH",
    RFB_KEYEVENT                    : "!BBBBi",
    RFB_POINTEREVENT                : "!BBHH",
    RFB_CLIENTCUTTEXT               : "!BBBBi",
    }
PACKET_STRUCT = {}
for ptype, fmt in PACKET_FMT.items():
    PACKET_STRUCT[ptype] = struct.Struct(fmt)


class RFBProtocol(object):
    CONNECTION_LOST = "connection-lost"
    INVALID = "invalid"

    def __init__(self, scheduler, conn, process_packet_cb, get_rfb_pixelformat, session_name="Xpra"):
        """
            You must call this constructor and source_has_more() from the main thread.
        """
        assert scheduler is not None
        assert conn is not None
        self.timeout_add = scheduler.timeout_add
        self.idle_add = scheduler.idle_add
        self._conn = conn
        self._process_packet_cb = process_packet_cb
        self._get_rfb_pixelformat = get_rfb_pixelformat
        self.session_name = session_name
        self._write_queue = Queue(1)
        self._buffer = b""
        #counters:
        self.input_packetcount = 0
        self.input_raw_packetcount = 0
        self.output_packetcount = 0
        self.output_raw_packetcount = 0
        self._protocol_version = ()
        self._closed = False
        self._packet_parser = self._parse_protocol_handshake
        self._write_lock = Lock()
        self._write_thread = None
        self._read_thread = make_thread(self._read_thread_loop, "read", daemon=True)


    def send_protocol_handshake(self):
        self.raw_write(b"RFB 003.008\n")

    def _parse_invalid(self, packet):
        return len(packet)

    def _parse_protocol_handshake(self, packet):
        if len(packet)<12:
            return 0
        if not packet.startswith(b'RFB '):
            self._invalid_header(packet, "invalid RFB protocol handshake packet header")
            return 0
        #ie: packet==b'RFB 003.008\n'
        self._protocol_version = tuple(int(x) for x in packet[4:11].split("."))
        log.info("RFB version %s", b".".join(str(x) for x in self._protocol_version))
        #reply with Security Handshake:
        self._packet_parser = self._parse_security_handshake
        self.send(struct.pack("BB", 1, 1))
        return 12

    def _parse_security_handshake(self, packet):
        if packet!=b"\1":
            self._invalid_header(packet, "invalid security handshake response")
            return 0
        #Security Handshake, send SecurityResult Handshake
        self._packet_parser = self._parse_security_result
        self.send(struct.pack("BBBB", 0, 0, 0, 0))
        return 1

    def _parse_security_result(self, packet):
        if packet!=b"\0":
            self._invalid_header(packet, "invalid security result")
            return 0
        #send ClientInit
        self._packet_parser = self._parse_rfb
        w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift = self._get_rfb_pixelformat()
        packet =  struct.pack("!HH"+PIXEL_FORMAT+"I", w, h, bpp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, bshift, gshift, 0, 0, 0, len(self.session_name))+self.session_name
        self.send(packet)
        self._process_packet_cb(self, [b"authenticated"])
        return 1

    def _parse_rfb(self, packet):
        try:
            ptype = ord(packet[0])
        except:
            ptype = packet[0]
        packet_type = PACKET_TYPE.get(ptype)
        if not packet_type:
            self.invalid("unknown RFB packet type: %#x" % ptype, packet)
            return 0
        s = PACKET_STRUCT[ptype]        #ie: Struct("!BBBB")
        if len(packet)<s.size:
            return 0
        size = s.size
        values = list(s.unpack(packet[:size]))
        values[0] = packet_type
        #some packets require parsing extra data:
        if ptype==RFB_SETENCODINGS:
            N = values[2]
            estruct = struct.Struct("!"+"i"*N)
            size += estruct.size
            if len(packet)<size:
                return 0
            encodings = estruct.unpack(packet[s.size:size])
            values.append(encodings)
        elif ptype==RFB_CLIENTCUTTEXT:
            l = values[4]
            size += l
            if len(packet)<size:
                return 0
            text = packet[s.size:size]
            values.append(text)
        self.input_packetcount += 1
        #log("RFB packet: %s", values)
        #now trigger the callback:
        self._process_packet_cb(self, values)
        #return part of packet not consumed:
        return size


    def wait_for_io_threads_exit(self, timeout=None):
        for t in (self._read_thread, self._write_thread):
            if t and t.isAlive():
                t.join(timeout)
        exited = True
        cinfo = self._conn or "cleared connection"
        for t in (self._read_thread, self._write_thread):
            if t and t.isAlive():
                log.warn("Warning: %s thread of %s is still alive (timeout=%s)", t.name, cinfo, timeout)
                exited = False
        return exited

    def __repr__(self):
        return "RFBProtocol(%s)" % self._conn

    def get_threads(self):
        return  [x for x in [self._write_thread, self._read_thread] if x is not None]


    def get_info(self, *_args):
        info = {"protocol" : self._protocol_version}
        for t in (self._write_thread, self._read_thread):
            if t:
                info.setdefault("thread", {})[t.name] = t.is_alive()
        return info


    def start(self):
        def start_network_read_thread():
            if not self._closed:
                self._read_thread.start()
        self.idle_add(start_network_read_thread)

    def send(self, packet):
        if self._closed:
            log("send(%s ...) connection is closed already, not sending", packet[0])
            return
        log("send(%s ...)", packet[0])
        with self._write_lock:
            if self._closed:
                return
            self.raw_write(packet)

    def start_write_thread(self):
        self._write_thread = start_thread(self._write_thread_loop, "write", daemon=True)

    def raw_write(self, contents):
        """ Warning: this bypasses the compression and packet encoder! """
        if self._write_thread is None:
            self.start_write_thread()
        self._write_queue.put(contents)

    def _io_thread_loop(self, name, callback):
        try:
            log("io_thread_loop(%s, %s) loop starting", name, callback)
            while not self._closed and callback():
                pass
            log("io_thread_loop(%s, %s) loop ended, closed=%s", name, callback, self._closed)
        except ConnectionClosedException as e:
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
        buf = self._write_queue.get()
        # Used to signal that we should exit:
        if buf is None:
            log("write thread: empty marker, exiting")
            self.close()
            return False
        con = self._conn
        if not con:
            return False
        while buf and not self._closed:
            written = con.write(buf)
            if written:
                buf = buf[written:]
                self.output_raw_packetcount += 1
        self.output_packetcount += 1
        return True

    def _read_thread_loop(self):
        self._io_thread_loop("read", self._read)
    def _read(self):
        buf = self._conn.read(READ_BUFFER_SIZE)
        #log("read()=%s", repr_ellipsized(buf))
        if not buf:
            log("read thread: eof")
            #give time to the parse thread to call close itself
            #so it has time to parse and process the last packet received
            self.timeout_add(1000, self.close)
            return False
        self.input_raw_packetcount += 1
        self._buffer += buf
        #log("calling %s(%s)", self._packet_parser, repr_ellipsized(self._buffer))
        while self._buffer:
            consumed = self._packet_parser(self._buffer)
            if consumed==0:
                break
            self._buffer = self._buffer[consumed:]
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
        self.idle_add(self._connection_lost, message)

    def _connection_lost(self, message="", exc_info=False):
        log("connection lost: %s", message, exc_info=exc_info)
        self.close()
        return False


    def invalid(self, msg, data):
        self._packet_parser = self._parse_invalid
        self.idle_add(self._process_packet_cb, self, [RFBProtocol.INVALID, msg, data])
        # Then hang up:
        self.timeout_add(1000, self._connection_lost, msg)


    #delegates to invalid_header()
    #(so this can more easily be intercepted and overriden
    # see tcp-proxy)
    def _invalid_header(self, data, msg=""):
        self.invalid_header(self, data, msg)

    def invalid_header(self, _proto, data, msg="invalid packet header"):
        self._packet_parser = self._parse_invalid
        err = "%s: '%s'" % (msg, binascii.hexlify(data[:8]))
        if len(data)>1:
            err += " read buffer=%s (%i bytes)" % (repr_ellipsized(data), len(data))
        self.invalid(err, data)


    def flush_then_close(self, _last_packet, done_callback=None):
        """ Note: this is best effort only
            the packet may not get sent.

            We try to get the write lock,
            we try to wait for the write queue to flush
            we queue our last packet,
            we wait again for the queue to flush,
            then no matter what, we close the connection and stop the threads.
        """
        log("flush_then_close(%s) closed=%s", done_callback, self._closed)
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
                    self._write_lock.release()
                    self.close()
                    done()
                else:
                    log("flush_then_close: still waiting for queue to flush")
                    self.timeout_add(100, wait_for_queue, timeout-1)
            else:
                log("flush_then_close: queue is now empty, sending the last packet and closing")
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
                self.timeout_add(100, wait_for_packet_sent)
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
        # -> wait_for_packet_sent
        # -> close_and_release
        log("flush_then_close: wait_for_write_lock()")
        wait_for_write_lock()


    def close(self):
        log("Protocol.close() closed=%s, connection=%s", self._closed, self._conn)
        if self._closed:
            return
        self._closed = True
        #self.idle_add(self._process_packet_cb, self, [Protocol.CONNECTION_LOST])
        c = self._conn
        if c:
            try:
                log("Protocol.close() calling %s", c.close)
                c.close()
            except:
                log.error("error closing %s", self._conn, exc_info=True)
            self._conn = None
        self.terminate_queue_threads()
        self.idle_add(self.clean)
        log("Protocol.close() done")

    def clean(self):
        #clear all references to ensure we can get garbage collected quickly:
        self._write_thread = None
        self._read_thread = None
        self._process_packet_cb = None

    def terminate_queue_threads(self):
        log("terminate_queue_threads()")
        #make all the queue based threads exit by adding the empty marker:
        exit_queue = Queue()
        for _ in range(10):     #just 2 should be enough!
            exit_queue.put(None)
        try:
            owq = self._write_queue
            self._write_queue = exit_queue
            #discard all elements in the old queue and push the None marker:
            try:
                while owq.qsize()>0:
                    owq.read(False)
            except:
                pass
            owq.put_nowait(None)
        except:
            pass
        try:
            orq = self._read_queue
            self._read_queue = exit_queue
            #discard all elements in the old queue and push the None marker:
            try:
                while orq.qsize()>0:
                    orq.read(False)
            except:
                pass
            orq.put_nowait(None)
        except:
            pass
