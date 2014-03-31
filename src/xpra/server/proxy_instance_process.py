# This file is part of Xpra.
# Copyright (C) 2013-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import socket
import os
import signal
import gobject
gobject.threads_init()
from threading import Timer

from xpra.log import Logger
log = Logger("proxy")


from xpra.server.server_core import get_server_info, get_thread_info
from xpra.scripts.server import deadly_signal
from xpra.net.protocol import Protocol, Compressed, compressed_wrapper, new_cipher_caps, get_network_caps
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.video_helper import getVideoHelper, PREFERRED_ENCODER_ORDER
from xpra.os_util import Queue, SIGNAMES
from xpra.util import typedict
from xpra.daemon_thread import make_daemon_thread
from xpra.scripts.config import parse_number, parse_bool
from xpra.scripts.server import create_unix_domain_socket
from xpra.scripts.main import SOCKET_TIMEOUT
from xpra.dotxpra import DotXpra
from xpra.net.bytestreams import SocketConnection
from multiprocessing import Process


PROXY_QUEUE_SIZE = int(os.environ.get("XPRA_PROXY_QUEUE_SIZE", "10"))
#for testing only: passthrough as RGB:
PASSTHROUGH = False
MAX_CONCURRENT_CONNECTIONS = 20
VIDEO_TIMEOUT = 5                  #destroy video encoder after N seconds of idle state


class ProxyInstanceProcess(Process):

    def __init__(self, uid, gid, env_options, session_options, socket_dir,
                 video_encoder_modules, csc_modules,
                 client_conn, client_state, cipher, encryption_key, server_conn, caps, message_queue):
        Process.__init__(self, name=str(client_conn))
        self.uid = uid
        self.gid = gid
        self.env_options = env_options
        self.session_options = self.sanitize_session_options(session_options)
        self.socket_dir = socket_dir
        self.video_encoder_modules = video_encoder_modules
        self.csc_modules = csc_modules
        self.client_conn = client_conn
        self.client_state = client_state
        self.cipher = cipher
        self.encryption_key = encryption_key
        self.server_conn = server_conn
        self.caps = caps
        log("ProxyProcess%s", (uid, gid, client_conn, client_state, cipher, encryption_key, server_conn, "{..}"))
        self.client_protocol = None
        self.server_protocol = None
        self.exit = False
        self.main_queue = None
        self.message_queue = message_queue
        self.encode_queue = None            #holds draw packets to encode
        self.encode_thread = None
        self.video_encoding_defs = None
        self.video_encoders = None
        self.video_encoders_last_used_time = None
        self.video_encoder_types = None
        self.video_helper = None
        self.lost_windows = None
        #for handling the local unix domain socket:
        self.control_socket = None
        self.control_socket_thread = None
        self.control_socket_path = None
        self.potential_protocols = []
        self.max_connections = MAX_CONCURRENT_CONNECTIONS

    def server_message_queue(self):
        while True:
            log("waiting for server message on %s", self.message_queue)
            m = self.message_queue.get()
            log.info("proxy server message: %s", m)
            if m=="stop":
                self.stop("proxy server request")
                return

    def signal_quit(self, signum, frame):
        log.info("")
        log.info("proxy process pid %s got signal %s, exiting", os.getpid(), SIGNAMES.get(signum, signum))
        self.exit = True
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.stop(SIGNAMES.get(signum, signum))

    def idle_add(self, fn, *args, **kwargs):
        #we emulate gobject's idle_add using a simple queue
        self.main_queue.put((fn, args, kwargs))

    def timeout_add(self, timeout, fn, *args, **kwargs):
        #emulate gobject's timeout_add using idle add and a Timer
        #using custom functions to cancel() the timer when needed
        def idle_exec():
            v = fn(*args, **kwargs)
            if bool(v):
                self.timeout_add(timeout, fn, *args, **kwargs)
            return False
        def timer_exec():
            #just run via idle_add:
            self.idle_add(idle_exec)
        Timer(timeout/1000.0, timer_exec).start()

    def run(self):
        log("ProxyProcess.run() pid=%s, uid=%s, gid=%s", os.getpid(), os.getuid(), os.getgid())
        #change uid and gid:
        if os.getgid()!=self.gid:
            os.setgid(self.gid)
        if os.getuid()!=self.uid:
            os.setuid(self.uid)
        log("ProxyProcess.run() new uid=%s, gid=%s", os.getuid(), os.getgid())

        if self.env_options:
            #TODO: whitelist env update?
            os.environ.update(self.env_options)
        self.video_init()

        log.info("new proxy started for client %s and server %s", self.client_conn, self.server_conn)

        signal.signal(signal.SIGTERM, self.signal_quit)
        signal.signal(signal.SIGINT, self.signal_quit)
        log("registered signal handler %s", self.signal_quit)

        make_daemon_thread(self.server_message_queue, "server message queue").start()

        if self.create_control_socket():
            self.control_socket_thread = make_daemon_thread(self.control_socket_loop, "control")
            self.control_socket_thread.start()

        self.main_queue = Queue()
        #setup protocol wrappers:
        self.server_packets = Queue(PROXY_QUEUE_SIZE)
        self.client_packets = Queue(PROXY_QUEUE_SIZE)
        self.client_protocol = Protocol(self, self.client_conn, self.process_client_packet, self.get_client_packet)
        self.client_protocol.restore_state(self.client_state)
        self.server_protocol = Protocol(self, self.server_conn, self.process_server_packet, self.get_server_packet)
        #server connection tweaks:
        self.server_protocol.large_packets.append("draw")
        self.server_protocol.large_packets.append("window-icon")
        self.server_protocol.large_packets.append("keymap-changed")
        self.server_protocol.large_packets.append("server-settings")
        self.server_protocol.set_compression_level(self.session_options.get("compression_level", 0))

        self.lost_windows = set()
        self.encode_queue = Queue()
        self.encode_thread = make_daemon_thread(self.encode_loop, "encode")
        self.encode_thread.start()

        log("starting network threads")
        self.server_protocol.start()
        self.client_protocol.start()

        #forward the hello packet:
        hello_packet = ("hello", self.filter_client_caps(self.caps))
        self.queue_server_packet(hello_packet)
        self.timeout_add(VIDEO_TIMEOUT*1000, self.timeout_video_encoders)

        try:
            try:
                self.run_queue()
            except KeyboardInterrupt, e:
                self.stop(str(e))
        finally:
            log("ProxyProcess.run() ending %s", os.getpid())

    def video_init(self):
        log("video_init() will try video encoders: %s", self.video_encoder_modules)
        self.video_helper = getVideoHelper()
        #only use video encoders (no CSC supported in proxy)
        self.video_helper.set_modules(video_encoders=self.video_encoder_modules)
        self.video_helper.init()

        self.video_encoding_defs = {}
        self.video_encoders = {}
        self.video_encoders_dst_formats = []
        self.video_encoders_last_used_time = {}
        self.video_encoder_types = []

        #figure out which encoders we want to proxy for (if any):
        encoder_types = set()
        for encoding in self.video_helper.get_encodings():
            colorspace_specs = self.video_helper.get_encoder_specs(encoding)
            for colorspace, especs in colorspace_specs.items():
                if colorspace not in ("BGRX", "BGRA", "RGBX", "RGBA"):
                    #only deal with encoders that can handle plain RGB directly
                    continue

                for spec in especs:                             #ie: codec_spec("x264")
                    spec_props = spec.to_dict()
                    del spec_props["codec_class"]               #not serializable!
                    spec_props["score_boost"] = 50              #we want to win scoring so we get used ahead of other encoders
                    spec_props["max_instances"] = 3             #limit to 3 video streams we proxy for (we really want 2,
                                                                # but because of races with garbage collection, we need to allow more)
                    #store it in encoding defs:
                    self.video_encoding_defs.setdefault(encoding, {}).setdefault(colorspace, []).append(spec_props)
                    encoder_types.add(spec.codec_type)

        log("encoder types found: %s", encoder_types)
        #remove duplicates and use preferred order:
        order = PREFERRED_ENCODER_ORDER[:]
        for x in list(encoder_types):
            if x not in order:
                order.append(x)
        self.video_encoder_types = [x for x in order if x in encoder_types]
        log.info("proxy video encoders: %s", self.video_encoder_types)


    def create_control_socket(self):
        dotxpra = DotXpra(self.socket_dir)
        name = "proxy-%s" % os.getpid()
        sockpath = dotxpra.norm_make_path(name, dotxpra.sockdir())
        state = dotxpra.get_server_state(sockpath)
        if state in (DotXpra.LIVE, DotXpra.UNKNOWN):
            log.warn("You already have a proxy server running at %s, the control socket will not be created!", sockpath)
            return False
        try:
            sock = create_unix_domain_socket(sockpath, None)
            sock.listen(5)
        except Exception, e:
            log.warn("failed to setup control socket %s: %s", sockpath, e)
            return False
        self.control_socket = sock
        self.control_socket_path = sockpath
        log.info("proxy instance now also available using unix domain socket: %s", self.control_socket_path)
        return True

    def control_socket_loop(self):
        while not self.exit:
            log("waiting for connection on %s", self.control_socket_path)
            sock, address = self.control_socket.accept()
            self.new_control_connection(sock, address)

    def new_control_connection(self, sock, address):
        if len(self.potential_protocols)>=self.max_connections:
            log.error("too many connections (%s), ignoring new one", len(self.potential_protocols))
            sock.close()
            return  True
        try:
            peername = sock.getpeername()
        except:
            peername = str(address)
        sockname = sock.getsockname()
        target = peername or sockname
        #sock.settimeout(0)
        log("new_control_connection() sock=%s, sockname=%s, address=%s, peername=%s", sock, sockname, address, peername)
        sc = SocketConnection(sock, sockname, address, target, "unix-domain")
        log.info("New proxy instance control connection received: %s", sc)
        protocol = Protocol(self, sc, self.process_control_packet)
        protocol.large_packets.append("info-response")
        self.potential_protocols.append(protocol)
        protocol.start()
        self.timeout_add(SOCKET_TIMEOUT*1000, self.verify_connection_accepted, protocol)
        return True

    def verify_connection_accepted(self, protocol):
        if not protocol._closed and protocol in self.potential_protocols:
            log.error("connection timedout: %s", protocol)
            self.send_disconnect(protocol, "login timeout")

    def process_control_packet(self, proto, packet):
        try:
            self.do_process_control_packet(proto, packet)
        except:
            log.error("error processing control packet", exc_info=True)
            self.send_disconnect(proto, "error processing request")

    def do_process_control_packet(self, proto, packet):
        log("process_control_packet(%s, %s)", proto, packet)
        packet_type = packet[0]
        if packet_type==Protocol.CONNECTION_LOST:
            log.info("Connection lost")
            if proto in self.potential_protocols:
                self.potential_protocols.remove(proto)
            return
        if packet_type=="hello":
            caps = typedict(packet[1])
            if caps.boolget("challenge"):
                self.send_disconnect(proto, "this socket does not use authentication")
                return
            if caps.get("info_request", False):
                proto.send_now(("hello", self.get_proxy_info(proto)))
                self.timeout_add(5*1000, self.send_disconnect, proto, "info sent")
                return
            elif caps.get("stop_request", False):
                self.stop("socket request", None)
                return
            elif caps.get("version_request", False):
                from xpra import __version__
                proto.send_now(("hello", {"version" : __version__}))
                self.timeout_add(5*1000, self.send_disconnect, proto, "version sent")
                return
        self.send_disconnect(proto, "this socket only handles 'info', 'version' and 'stop' requests")

    def send_disconnect(self, proto, reason):
        log("send_disconnect(%s, %s)", proto, reason)
        if proto._closed:
            return
        proto.send_now(["disconnect", reason])
        self.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto):
        proto.close()


    def get_proxy_info(self, proto):
        info = {}
        info.update(get_server_info("proxy."))
        info.update(get_thread_info("proxy.", proto))
        info.update(self.get_encoder_info())
        return info


    def sanitize_session_options(self, options):
        d = {}
        def number(k, v):
            return parse_number(int, k, v)
        OPTION_WHITELIST = {"compression_level" : number,
                            "lz4"               : parse_bool}
        for k,v in options.items():
            parser = OPTION_WHITELIST.get(k)
            if parser:
                log("trying to add %s=%s using %s", k, v, parser)
                try:
                    d[k] = parser(k, v)
                except Exception, e:
                    log.warn("failed to parse value %s for %s using %s: %s", v, k, parser, e)
        return d

    def filter_client_caps(self, caps):
        fc = self.filter_caps(caps, ("cipher", "digest", "aliases", "compression", "lz4"))
        #update with options provided via config if any:
        fc.update(self.session_options)
        #add video proxies if any:
        fc["encoding.proxy.video"] = len(self.video_encoding_defs)>0
        if self.video_encoding_defs:
            fc["encoding.proxy.video.encodings"] = self.video_encoding_defs
        return fc

    def filter_server_caps(self, caps):
        if caps.get("rencode", False):
            self.server_protocol.enable_rencode()
        return self.filter_caps(caps, ("aliases", ))

    def filter_caps(self, caps, prefixes):
        #removes caps that the proxy overrides / does not use:
        #(not very pythonic!)
        pcaps = {}
        removed = []
        for k in caps.keys():
            skip = len([e for e in prefixes if k.startswith(e)])
            if skip==0:
                pcaps[k] = caps[k]
            else:
                removed.append(k)
        log("filtered out %s matching %s", removed, prefixes)
        #replace the network caps with the proxy's own:
        pcaps.update(get_network_caps())
        #then add the proxy info:
        pcaps.update(get_server_info("proxy."))
        pcaps["proxy"] = True
        pcaps["proxy.hostname"] = socket.gethostname()
        return pcaps


    def run_queue(self):
        log("run_queue() queue has %s items already in it", self.main_queue.qsize())
        #process "idle_add"/"timeout_add" events in the main loop:
        while not self.exit:
            log("run_queue() size=%s", self.main_queue.qsize())
            v = self.main_queue.get()
            log("run_queue() item=%s", v)
            if v is None:
                break
            fn, args, kwargs = v
            try:
                v = fn(*args, **kwargs)
                if bool(v):
                    #re-run it
                    self.main_queue.put(v)
            except:
                log.error("error during main loop callback %s", fn, exc_info=True)
        self.exit = True
        log.info("proxy instance %s stopped", os.getpid())

    def stop(self, reason="proxy terminating", skip_proto=None):
        log("stop(%s, %s)", reason, skip_proto)
        self.exit = True
        if self.control_socket_path:
            try:
                os.unlink(self.control_socket_path)
            except:
                pass
        self.main_queue.put(None)
        #empty the main queue:
        q = Queue()
        q.put(None)
        self.main_queue = q
        #empty the encode queue:
        q = Queue()
        q.put(None)
        self.encode_queue = q
        for proto in (self.client_protocol, self.server_protocol):
            if proto and proto!=skip_proto:
                proto.flush_then_close(["disconnect", reason])


    def queue_client_packet(self, packet):
        log("queueing client packet: %s", packet[0])
        self.client_packets.put(packet)
        self.client_protocol.source_has_more()

    def get_client_packet(self):
        #server wants a packet
        p = self.client_packets.get()
        log("sending to client: %s", p[0])
        return p, None, None, self.client_packets.qsize()>0

    def process_client_packet(self, proto, packet):
        packet_type = packet[0]
        log("process_client_packet: %s", packet_type)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("client connection lost", proto)
            return
        elif packet_type=="set_deflate":
            #echo it back to the client:
            self.client_packets.put(packet)
            self.client_protocol.source_has_more()
            return
        elif packet_type=="hello":
            log.warn("invalid hello packet received after initial authentication (dropped)")
            return
        self.queue_server_packet(packet)


    def queue_server_packet(self, packet):
        log("queueing server packet: %s", packet[0])
        self.server_packets.put(packet)
        self.server_protocol.source_has_more()

    def get_server_packet(self):
        #server wants a packet
        p = self.server_packets.get()
        log("sending to server: %s", p[0])
        return p, None, None, self.server_packets.qsize()>0

    def process_server_packet(self, proto, packet):
        packet_type = packet[0]
        log("process_server_packet: %s", packet_type)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("server connection lost", proto)
            return
        elif packet_type=="hello":
            c = typedict(packet[1])
            maxw, maxh = c.intpair("max_desktop_size", (4096, 4096))
            proto.max_packet_size = maxw*maxh*4

            caps = self.filter_server_caps(c)
            #add new encryption caps:
            if self.cipher:
                auth_caps = new_cipher_caps(self.client_protocol, self.cipher, self.encryption_key)
                caps.update(auth_caps)
            packet = ("hello", caps)
        elif packet_type=="info-response":
            #adds proxy info:
            #note: this is only seen by the client application
            #"xpra info" is a new connection, which talks to the proxy server...
            info = packet[1]
            info.update(self.get_proxy_info(proto))
        elif packet_type=="lost-window":
            wid = packet[1]
            #mark it as lost so we can drop any current/pending frames
            self.lost_windows.add(wid)
            #queue it so it gets cleaned safely (for video encoders mostly):
            self.encode_queue.put(packet)
            #and fall through so tell the client immediately
        elif packet_type=="draw":
            #use encoder thread:
            self.encode_queue.put(packet)
            #which will queue the packet itself when done:
            return
        elif packet_type=="cursor":
            #packet = ["cursor", x, y, width, height, xhot, yhot, serial, pixels, name]
            #or:
            #packet = ["cursor", ""]
            if len(packet)>=9:
                pixels = packet[8]
                if len(pixels)<512:
                    packet[8] = str(pixels)
                else:
                    packet[8] = compressed_wrapper("cursor", pixels)
        self.queue_client_packet(packet)


    def encode_loop(self):
        """ thread for slower encoding related work """
        while not self.exit:
            packet = self.encode_queue.get()
            if packet is None:
                return
            try:
                packet_type = packet[0]
                if packet_type=="lost-window":
                    wid = packet[1]
                    self.lost_windows.remove(wid)
                    ve = self.video_encoders.get(wid)
                    if ve:
                        del self.video_encoders[wid]
                        del self.video_encoders_last_used_time[wid]
                        ve.clean()
                elif packet_type=="draw":
                    #modify the packet with the video encoder:
                    if self.process_draw(packet):
                        #then send it as normal:
                        self.queue_client_packet(packet)
                elif packet_type=="check-video-timeout":
                    #not a real packet, this is added by the timeout check:
                    wid = packet[1]
                    ve = self.video_encoders.get(wid)
                    now = time.time()
                    idle_time = now-self.video_encoders_last_used_time.get(wid)
                    if ve and idle_time>VIDEO_TIMEOUT:
                        log("timing out the video encoder context for window %s", wid)
                        #timeout is confirmed, we are in the encoding thread,
                        #so it is now safe to clean it up:
                        ve.clean()
                        del self.video_encoders[wid]
                        del self.video_encoders_last_used_time[wid]
                else:
                    log.warn("unexpected encode packet: %s", packet_type)
            except:
                log.warn("error encoding packet", exc_info=True)


    def process_draw(self, packet):
        wid, x, y, width, height, encoding, pixels, _, rowstride, client_options = packet[1:11]
        #never modify mmap packets
        if encoding=="mmap":
            return True

        if not self.video_encoder_types or not client_options or not client_options.get("proxy", False):
            #ensure we don't try to re-compress the pixel data in the network layer:
            #(re-add the "compressed" marker that gets lost when we re-assemble packets)
            packet[7] = Compressed("%s pixels" % encoding, packet[7])
            return True

        #we have a proxy video packet:
        rgb_format = client_options.get("rgb_format", "")
        log("proxy draw: client_options=%s", client_options)

        def send_updated(encoding, compressed_data, client_options):
            #update the packet with actual encoding data used:
            packet[6] = encoding
            packet[7] = compressed_data
            packet[10] = client_options
            log("returning %s bytes from %s", len(compressed_data), len(pixels))
            return (wid not in self.lost_windows)

        def passthrough():
            #passthrough as plain RGB:
            newdata = bytearray(pixels)
            #force alpha (and assume BGRX..) for now:
            for i in range(len(pixels)/4):
                newdata[i*4+3] = chr(255)
            packet[9] = client_options.get("rowstride", 0)
            return send_updated("rgb32", str(newdata), {"rgb_format" : rgb_format})

        if PASSTHROUGH:
            passthrough()
            return

        #video encoding: find existing encoder
        ve = self.video_encoders.get(wid)
        if ve:
            if ve in self.lost_windows:
                #we cannot clean the video encoder here, there may be more frames queue up
                #"lost-window" in encode_loop will take care of it safely
                return  False
            #we must verify that the encoder is still valid
            #and scrap it if not (ie: when window is resized)
            if ve.get_width()!=width or ve.get_height()!=height:
                log("closing existing video encoder %s because dimensions have changed from %sx%s to %sx%s", ve, ve.get_width(), ve.get_height(), width, height)
                ve.clean()
                ve = None
            elif ve.get_encoding()!=encoding:
                log("closing existing video encoder %s because encoding has changed from %s to %s", ve.get_encoding(), encoding)
                ve.clean()
                ve = None
        #scaling and depth are proxy-encoder attributes:
        scaling = client_options.get("scaling", (1, 1))
        depth   = client_options.get("depth", 24)
        rowstride = client_options.get("rowstride", rowstride)
        quality = client_options.get("quality", -1)
        speed   = client_options.get("speed", -1)
        timestamp = client_options.get("timestamp")

        image = ImageWrapper(x, y, width, height, pixels, rgb_format, depth, rowstride, planes=ImageWrapper.PACKED)
        if timestamp is not None:
            image.set_timestamp(timestamp)

        #the encoder options are passed through:
        encoder_options = client_options.get("options", {})
        if not ve:
            #make a new video encoder:
            spec = self._find_video_encoder(encoding, rgb_format)
            if spec is None:
                #no video encoder!
                from xpra.server.picture_encode import PIL_encode, PIL, warn_encoding_once
                if PIL is None:
                    warn_encoding_once("no-video-no-PIL", "no video encoder found for rgb format %s, sending as plain RGB!" % rgb_format)
                    passthrough()
                    return
                log("no video encoder available: sending as jpeg")
                coding, compressed_data, client_options, _, _, _, _ = PIL_encode("jpeg", image, quality, speed, False)
                return send_updated(coding, compressed_data, client_options)

            log("creating new video encoder %s for window %s", spec, wid)
            ve = spec.make_instance()
            #dst_formats is specified with first frame only:
            dst_formats = client_options.get("dst_formats")
            if dst_formats is not None:
                #save it in case we timeout the video encoder,
                #so we can instantiate it again, even from a frame no>1
                self.video_encoders_dst_formats = dst_formats
            else:
                assert self.video_encoders_dst_formats, "BUG: dst_formats not specified for proxy and we don't have it either"
                dst_formats = self.video_encoders_dst_formats
            ve.init_context(width, height, rgb_format, dst_formats, encoding, quality, speed, scaling, {})
            self.video_encoders[wid] = ve
            self.video_encoders_last_used_time[wid] = time.time()       #just to make sure this is always set
        else:
            if quality>=0:
                ve.set_encoding_quality(quality)
            if speed>=0:
                ve.set_encoding_speed(speed)
        #actual video compression:
        log("proxy compression using %s with quality=%s, speed=%s", ve, quality, speed)
        data, client_options = ve.compress_image(image, encoder_options)
        self.video_encoders_last_used_time[wid] = time.time()
        return send_updated(ve.get_encoding(), Compressed(encoding, data), client_options)

    def timeout_video_encoders(self):
        #have to be careful as another thread may come in...
        #so we just ask the encode thread (which deals with encoders already)
        #to do what may need to be done if we find a timeout:
        now = time.time()
        for wid in list(self.video_encoders_last_used_time.keys()):
            idle_time = int(now-self.video_encoders_last_used_time.get(wid))
            if idle_time is None:
                continue
            log("timeout_video_encoders() wid=%s, idle_time=%s", wid, idle_time)
            if idle_time and idle_time>VIDEO_TIMEOUT:
                self.encode_queue.put(["check-video-timeout", wid])
        return True     #run again

    def _find_video_encoder(self, encoding, rgb_format):
        #try the one specified first, then all the others:
        try_encodings = [encoding] + [x for x in self.video_helper.get_encodings() if x!=encoding]
        for encoding in try_encodings:
            colorspace_specs = self.video_helper.get_encoder_specs(encoding)
            especs = colorspace_specs.get(rgb_format)
            if len(especs)==0:
                continue
            for etype in self.video_encoder_types:
                for spec in especs:
                    if etype==spec.codec_type:
                        return spec
        return None

    def get_encoder_info(self):
        info = {}
        now = time.time()
        for wid, encoder in list(self.video_encoders.items()):
            ipath = "window[%s].proxy.encoder" % wid
            info[ipath] = encoder.get_type()
            idle_time = now-self.video_encoders_last_used_time.get(wid, 0)
            info[ipath+".idle_time"] = int(idle_time)
            vi = encoder.get_info()
            for k,v in vi.items():
                info[ipath+"."+k] = v
        return info
