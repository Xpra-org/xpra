# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import struct
import random

from xpra.os_util import LINUX, monotonic_time, memoryview_to_bytes
from xpra.util import envint, repr_ellipsized
from xpra.make_thread import start_thread
from xpra.net.protocol import Protocol, READ_BUFFER_SIZE
from xpra.net.bytestreams import SocketConnection, can_retry
from xpra.log import Logger

try:
    import errno
    EMSGSIZE = errno.EMSGSIZE
except ImportError:
    EMSGSIZE = None

log = Logger("network", "protocol", "udp")

DROP_PCT = envint("XPRA_UDP_DROP_PCT", 0)
DROP_FIRST = envint("XPRA_UDP_DROP_FIRST", 0)
MIN_MTU = envint("XPRA_UDP_MIN_MTU", 576)
MAX_MTU = envint("XPRA_UDP_MAX_MTU", 65536)
assert MAX_MTU>MIN_MTU

def clamp_mtu(mtu):
    return max(MIN_MTU, min(MAX_MTU, mtu))


#UUID, seqno, synchronous, chunk, chunks
_header_struct = struct.Struct(b'!QQHHH')
_header_size = _header_struct.size


class PendingPacket(object):
    def __init__(self, seqno, start_time, chunks=None):
        self.seqno = seqno
        self.start_time = start_time
        self.last_time = start_time
        self.chunk_gap = 0
        self.chunks = chunks
    def __repr__(self):
        return ("PendingPacket(%i: %s chunks)" % (self.seqno, len(self.chunks or [])))


class UDPListener(object):
    """
        This class is used by servers to receive UDP packets,
        it parses the header and then exposes the data received via process_packet_cb.
    """

    def __init__(self, sock, process_packet_cb):
        assert sock is not None
        self._closed = False
        self._socket = sock
        self._process_packet_cb =  process_packet_cb
        self._read_thread = start_thread(self._read_thread_loop, "read", daemon=True)

    def __repr__(self):
        return "UDPListener(%s)" % self._socket

    def _read_thread_loop(self):
        log.info("udp read thread loop starting")
        try:
            while not self._closed:
                try:
                    buf, bfrom = self._socket.recvfrom(READ_BUFFER_SIZE)
                except Exception as e:
                    log("_read_thread_loop() buffer=%s, from=%s", repr_ellipsized(buf), bfrom, exc_info=True)
                    if can_retry(e):
                        continue
                    raise
                if not buf:
                    log("read thread: eof")
                    break
                values = list(_header_struct.unpack_from(buf[:_header_size])) + [buf[_header_size:], bfrom]
                try:
                    self._process_packet_cb(self, *values)
                except Exception as e:
                    log("_read_thread_loop() buffer=%s, from=%s", repr_ellipsized(buf), bfrom, exc_info=True)
                    if not self._closed:
                        log.error("Error: UDP packet processing error:")
                        log.error(" %s", e)
                    del e
        except Exception as e:
            #can happen during close(), in which case we just ignore:
            if not self._closed:
                log.error("Error: read on %s failed: %s", self._socket, type(e), exc_info=True)
        log("udp read thread loop ended")
        self.close()

    def close(self):
        s = self._socket
        log("UDPListener.close() closed=%s, socket=%s", self._closed, s)
        if self._closed:
            return
        self._closed = True
        if s:
            try:
                log("Protocol.close() calling %s", s.close)
                s.close()
            except (OSError, IOError):
                log.error("error closing %s", s, exc_info=True)
            self._socket = None
        log("UDPListener.close() done")


class UDPProtocol(Protocol):
    """
        This class extends the Protocol class with UDP encapsulation.
        A single packet may end up being fragmented into multiple UDP frames
        to fit in the MTU.
        We keep track of the function which can be used to handle send failures
        (or the packet data if no function is supplied).
        "udp-control" packets are used to synchronize both ends.
    """

    def __init__(self, *args, **kwargs):
        Protocol.__init__(self, *args)
        self.mtu = 0
        self.last_sequence = -1     #the most recent packet sequence we processed in full
        self.highest_sequence = -1
        self.jitter = 20            #20ms
        self.uuid = kwargs.get("uuid", 0)
        self.fail_cb = {}
        self.resend_cache = {}
        self.pending_packets = {}
        self.can_skip = set()       #processed already, or cancelled
        self.cancel = set()         #tell the other end to forget those
        self.control_timer = None
        self.control_timer_due = 0
        self.asynchronous_send_enabled = False
        self.asynchronous_receive_enabled = False
        self._process_read = self.process_read
        self.enable_encoder("bencode")

    def close(self):
        Protocol.close(self)
        self.cancel_control_timer()

    def accept(self):
        log("accept() enabling asynchronous packet reception")
        #this flag will be sent to the other end so it knows
        #it is allowed to use synchronous=False on more packets than just "udp-control"
        self.asynchronous_receive_enabled = True


    def schedule_control(self, delay=1000):
        """ make sure that we send a udp-control packet within the delay given """
        due = monotonic_time()+delay/1000.0
        #log("schedule_control(%i) due=%s, current due=%s", delay, due, self.control_timer_due)
        if self.control_timer_due and self.control_timer_due<=due:
            #due already
            return
        ct = self.control_timer
        if ct:
            self.source_remove(ct)
        self.control_timer = self.timeout_add(delay, self.send_control)
        self.control_timer_due = due

    def cancel_control_timer(self):
        ct = self.control_timer
        if ct:
            self.control_timer = None
            self.source_remove(ct)

    def send_control(self):
        self.control_timer = None
        self.control_timer_due = 0
        if self._closed:
            return False
        missing = self._get_missing()
        packet = ("udp-control", self.mtu, self.asynchronous_receive_enabled, self.last_sequence, self.highest_sequence, missing, tuple(self.cancel))
        log("send_control() packet(%s)=%s", self.pending_packets, packet)
        def send_control_failed():
            #resend a new one
            self.cancel_control_timer()
            self.send_control()
        self._add_packet_to_queue(packet, fail_cb=send_control_failed, synchronous=False)
        self.cancel = set()
        self.schedule_control()
        return False

    def _get_missing(self):
        """ the packets and chunks we are missing """
        if not self.pending_packets:
            return {}
        now = monotonic_time()
        max_time = now-self.jitter/1000.0
        missing = {}
        for seqno, ip in self.pending_packets.items():
            start = ip.start_time
            if start>=max_time:
                continue        #too recent, may still arrive
            missing_chunks = []     #by default, we don't know what is missing
            if ip.chunks is not None:
                #we have some chunks already,
                #so we know how many we are expecting in total,
                #and which ones should have arrived by now
                chunks = [i for i,x in enumerate(ip.chunks) if x is None]
                if not chunks:
                    continue
                #re-use the chunk_gap calculated previously,
                #so re-sent chunks don't skew the value!
                chunk_gap = ip.chunk_gap
                if chunk_gap==0:
                    highest = max(chunks)
                    if highest>0:
                        chunk_gap = (ip.last_time - start) / highest
                        ip.chunk_gap = chunk_gap
                for index in chunks:
                    #when should it have been received
                    eta = start + chunk_gap*index
                    if eta<=max_time:
                        missing_chunks.append(index)
                if not missing_chunks:
                    #nothing is overdue yet, so don't request anything:
                    continue
            missing[seqno] = missing_chunks
        return missing

    def process_control(self, mtu, remote_async_receive, last_seq, high_seq, missing, cancel):
        log("process_control(%i, %i, %i, %i, %s, %s) current seq=%i", mtu, remote_async_receive, last_seq, high_seq, missing, cancel, self.output_packetcount)
        con = self._conn
        if not con:
            return
        if mtu and self.mtu==0:
            self.mtu = clamp_mtu(mtu)
        self.asynchronous_send_enabled = remote_async_receive
        #first, we can free all the packets that have been processed by the other end:
        #(resend cache and fail callback)
        if last_seq>=0:
            done = [x for x in self.fail_cb.keys() if x<=last_seq]
            for x in done:
                try:
                    del self.fail_cb[x]
                except KeyError:
                    pass
            done = [x for x in self.resend_cache.keys() if x<=last_seq]
            for x in done:
                try:
                    del self.resend_cache[x]
                except KeyError:
                    pass
        #next we can forget about sequence numbers that have been cancelled:
        #we don't need to request a re-send, and we can skip over them:
        if cancel:
            for seqno in cancel:
                if seqno>self.last_sequence:
                    self.can_skip.add(seqno)
                try:
                    del self.pending_packets[seqno]
                except KeyError:
                    pass
            #we may now be able to move forward a bit:
            if self.pending_packets and (self.last_sequence+1) in self.can_skip:
                self.process_pending()
        #re-send the missing ones:
        for seqno, missing_chunks in missing.items():
            resend_cache = self.resend_cache.get(seqno)
            fail_cb_seq = self.fail_cb.get(seqno)
            if fail_cb_seq is None and not resend_cache:
                log("cannot resend packet sequence %i - assuming we cancelled it already", seqno)
                #hope for the best, and tell the other end to stop asking:
                self.cancel.add(seqno)
                continue
            if not missing_chunks:
                #the other end only knows it is missing the seqno,
                #not how many chunks are missing, so send them all
                missing_chunks = resend_cache.keys()
            if fail_cb_seq:
                log("fail_cb[%i]=%s, missing_chunks=%s, len(resend_cache)=%i",
                    seqno, repr_ellipsized(str(fail_cb_seq)), missing_chunks, len(resend_cache))
                #we have a fail callback for this packet,
                #we have to decide if we send the missing chunks or use the callback,
                #resend if the other end is missing less than 25% of the chunks:
                #TODO: if the latency is low, resending becomes cheaper..
                if len(missing_chunks)>=len(resend_cache)//4:
                    #too many are missing, forget about it
                    try:
                        del self.resend_cache[seqno]
                    except KeyError:
                        pass
                    try:
                        del self.fail_cb[seqno]
                    except KeyError:
                        pass
                    self.cancel.add(seqno)
                    fail_cb_seq()
                    continue
            for c in missing_chunks:
                data = resend_cache.get(c)
                log("resend data[%i][%i]=%s", seqno, c, repr_ellipsized(str(data)))
                if data is None:
                    log.error("Error: cannot resend chunk %i of packet sequence %i", c, seqno)
                    log.error(" data missing from packet resend cache")
                    continue
                #send it again:
                #TODO: if the mtu is now lower, we should re-send the whole packet,
                # with the new chunk size..
                con.write(data)
        #make sure we keep telling the client it has packets to catch up on:
        if high_seq<self.output_packetcount:
            self.schedule_control()


    def process_udp_data(self, uuid, seqno, synchronous, chunk, chunks, data, _bfrom):
        """
            process a udp chunk:
            * if asynchronous or if this is the next sequence: process it immediately
              and keep processing any queued packets, if any
            * otherwise queue it up and keep track of any missing sequence numbers,
              schedule a udp-control packet to notify the other end of what we're missing
        """
        #log("process_udp_data%s %i bytes", (uuid, seqno, synchronous, chunk, chunks, repr_ellipsized(data), bfrom), len(data))
        assert uuid==self.uuid
        if seqno<=self.last_sequence:
            log("skipping duplicate packet %5i.%i", seqno, chunk)
            return
        global DROP_FIRST, DROP_PCT
        if DROP_FIRST>0 and seqno==0 and chunk==0:
            DROP_FIRST -= 1
            log.warn("Warning: dropping first udp packet %5i.%i (%i more times)", seqno, chunk, DROP_FIRST)
            return
        if DROP_PCT>0:
            if random.randint(0, 100) <= DROP_PCT:
                log.warn("Warning: dropping udp packet %5i.%i", seqno, chunk)
                return
        self.highest_sequence = max(self.highest_sequence, seqno)
        if self.pending_packets or (synchronous and seqno!=self.last_sequence+1) or chunk!=0 or chunks!=1:
            assert chunk>=0 and chunks>0 and chunk<chunks, "invalid chunk: %i/%i" % (chunk, chunks)
            #slow path: add chunk to incomplete packet
            now = monotonic_time()
            ip = self.pending_packets.get(seqno)
            #first time we see this sequence, or the number of chunks has changed (new MTU)
            if not ip or not ip.chunks or len(ip.chunks)!=chunks:
                chunks_array = [None for _ in range(chunks)]
                ip = PendingPacket(seqno, now, chunks_array)
                self.pending_packets[seqno] = ip
            else:
                ip.last_time = now
            ip.chunks[chunk] = data
            if seqno>self.last_sequence+1:
                #we're waiting for a packet and this is not it,
                #make sure any gaps are marked as incomplete:
                for i in range(self.last_sequence+1, seqno):
                    if i not in self.pending_packets and i not in self.can_skip:
                        self.pending_packets[i] = PendingPacket(i, now)
                #make sure we request the missing packets:
                mcount = seqno-self.last_sequence
                self.schedule_control(self.jitter//mcount)
                if synchronous:
                    #we have to wait for the missing chunks / packets
                    log("process_udp_data: queuing %i as we're still waiting for %i", seqno, self.last_sequence+1)
                    return
            if any(x is None for x in ip.chunks):
                #one of the chunks is still missing
                log("process_udp_data: sequence %i, got chunk %i but still missing: %s",
                    seqno, chunk, [i for i,x in enumerate(ip.chunks) if x is None])
                self.schedule_control(self.jitter)
                return
            #all the data is here!
            del self.pending_packets[seqno]
            data = b"".join(ip.chunks)
        log("process_udp_data: adding packet sequence %5i to read queue (got final chunk %i, synchronous=%s)",
            seqno, chunk, synchronous!=0)
        if seqno==self.last_sequence+1:
            self.last_sequence = seqno
        else:
            assert not synchronous
            self.can_skip.add(seqno)
        self._read_queue_put(data)
        #if self.pending_packets or (seqno+1) in self.can_skip:
        self.process_pending()

    def process_pending(self):
        """
            because of a new packet (bumped sequence number),
            or of sequence numbers added to the skip list,
            we may be able to empty the incomplete packet queue.
        """
        #maybe we can send the next one(s) now?
        seqno = self.last_sequence
        log("process_pending() last_sequence=%i, can skip=%s", seqno, self.can_skip)
        while True:
            seqno += 1
            if seqno in self.can_skip:
                try:
                    del self.pending_packets[seqno]
                except KeyError:
                    pass
                self.can_skip.remove(seqno)
                self.last_sequence = seqno
                continue
            ip = self.pending_packets.get(seqno)
            if not ip or not ip.chunks:
                #it's missing, we just don't know how many chunks
                return
            if any(x is None for x in ip.chunks):
                #one of the chunks is still missing
                return
            #all the data is here!
            del self.pending_packets[seqno]
            data = b"".join(ip.chunks)
            log("process_pending: adding packet sequence %5i to read queue", seqno)
            self.last_sequence = seqno
            self._read_queue_put(data)


    def raw_write(self, packet_type, items, start_cb=None, end_cb=None, fail_cb=None, synchronous=True, _more=False):
        """ make sure we don't enable asynchronous mode until the other end is read """
        if packet_type!="udp-control" and not self.asynchronous_send_enabled:
            synchronous = True
        Protocol.raw_write(self, packet_type, items, start_cb, end_cb, fail_cb, synchronous)

    def write_buffers(self, buf_data, fail_cb, synchronous):
        """
            send the buffers to the other end,
            if we exceed the MTU, start again with a lower value
        """
        buf = b"".join(memoryview_to_bytes(x) for x in buf_data)
        #if not isinstance(buf, JOIN_TYPES):
        #    buf = memoryview_to_bytes(buf)
        while True:
            try:
                seqno = self.output_packetcount
                return self.write_buf(seqno, buf, fail_cb, synchronous)
            except MTUExceeded as e:
                log.warn("%s: %s", e, self.mtu)
                if self.mtu>MIN_MTU:
                    self.mtu = clamp_mtu(self.mtu//2)
                raise

    def write_buf(self, seqno, data, fail_cb, synchronous):
        con = self._conn
        if not con:
            return 0
        #TODO: bump to 1280 for IPv6
        #mtu = max(576, self.mtu)
        mtu = self.mtu or MIN_MTU
        l = len(data)
        maxpayload = mtu-_header_size
        chunks = l // maxpayload
        if l % maxpayload > 0:
            chunks += 1
        log("UDP.write_buf(%s, %i bytes, %s, %s) seq=%i, mtu=%s, maxpayload=%i, chunks=%i, data=%s",
            con, l, fail_cb, synchronous, seqno, mtu, maxpayload, chunks, repr_ellipsized(data))
        chunk = 0
        offset = 0
        if fail_cb:
            self.fail_cb[seqno] = fail_cb
        chunk_resend_cache = self.resend_cache.setdefault(seqno, {})
        while offset<l:
            assert chunk<chunks
            pl = min(maxpayload, l-offset)
            data_chunk = data[offset:offset+pl]
            udp_data = _header_struct.pack(self.uuid, seqno, synchronous, chunk, chunks) + data_chunk
            assert len(udp_data)<=mtu, "invalid payload size: %i greater than mtu %i" % (len(udp_data), mtu)
            con.write(udp_data)
            self.output_raw_packetcount += 1
            offset += pl
            if chunk_resend_cache is not None:
                chunk_resend_cache[chunk] = udp_data
            chunk += 1
        assert chunk==chunks, "wrote %i chunks but expected %i" % (chunk, chunks)
        self.output_packetcount += 1
        if not self.control_timer:
            self.schedule_control()
        return offset


    def get_info(self, alias_info=True):
        i = Protocol.get_info(self, alias_info)
        i.update({
            "mtu"   : {
                ""      : clamp_mtu(self.mtu),
                "min"   : MIN_MTU,
                "max"   : MAX_MTU,
                },
            })
        return i


class UDPServerProtocol(UDPProtocol):

    def _read_thread_loop(self):
        #server protocol is not used to read,
        #we rely on the listener to dispatch packets instead
        pass

class UDPClientProtocol(UDPProtocol):

    def __init__(self, *args, **kwargs):
        UDPProtocol.__init__(self, *args, uuid = random.randint(0, 2**64-1))

    def con_write(self, data, fail_cb):
        """ After successfully writing some data, update the mtu value """
        r = UDPProtocol.con_write(self, data, fail_cb)
        if r>0 and LINUX:
            IP_MTU = 14
            con = self._conn
            if con:
                try:
                    self.mtu = clamp_mtu(con._socket.getsockopt(socket.IPPROTO_IP, IP_MTU))
                    #log("mtu=%s", self.mtu)
                except IOError:
                    pass
        return r

    def process_read(self, buf):
        """
            Splits and parses the UDP frame header from the packet,
            then process the packed using process_udp_data
        """
        #log.info("UDPClientProtocol.read_queue_put(%s)", repr_ellipsized(buf))
        uuid, seqno, synchronous, chunk, chunks = _header_struct.unpack_from(buf[:_header_size])
        data = buf[_header_size:]
        bfrom = None        #not available here..
        self.process_udp_data(uuid, seqno, synchronous, chunk, chunks, data, bfrom)


class UDPSocketConnection(SocketConnection):
    """
        This class extends SocketConnection to use socket.sendto
        to send data to the correct destination.
        (servers use a single socket to talk to multiple clients,
        they do not call connect() and so we have to specify the remote target every time)
    """

    def __init__(self, *args):
        SocketConnection.__init__(self, *args)

    def write(self, buf):
        #log("UDPSocketConnection: sending %i bytes to %s", len(buf), self.remote)
        try:
            return self._socket.sendto(buf, self.remote)
        except IOError as e:
            if e.errno==EMSGSIZE:
                raise MTUExceeded("invalid UDP payload size, cannot send %i bytes: %s" % (len(buf), e))
            raise

    def close(self):
        """
            don't close the socket, we don't own it
        """
        pass

class MTUExceeded(IOError):
    pass
