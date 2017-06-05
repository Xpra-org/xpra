# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import os
import signal
from threading import Timer
from time import sleep

from xpra.log import Logger
log = Logger("proxy")
enclog = Logger("encoding")


from xpra.server.server_core import get_server_info, get_thread_info
from xpra.scripts.server import deadly_signal
from xpra.net import compression
from xpra.net.compression import Compressed, compressed_wrapper
from xpra.net.protocol import Protocol, get_network_caps
from xpra.codecs.loader import load_codecs, get_codec
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.video_helper import getVideoHelper, PREFERRED_ENCODER_ORDER
from xpra.os_util import Queue, SIGNAMES, strtobytes, memoryview_to_bytes, getuid, getgid, monotonic_time, get_username_for_uid, setuidgid
from xpra.util import flatten_dict, typedict, updict, repr_ellipsized, xor, std, envint, envbool, csv, \
    LOGIN_TIMEOUT, CONTROL_COMMAND_ERROR, AUTHENTICATION_ERROR, CLIENT_EXIT_TIMEOUT, SERVER_SHUTDOWN
from xpra.version_util import XPRA_VERSION
from xpra.make_thread import start_thread
from xpra.scripts.config import parse_number, parse_bool
from xpra.server.socket_util import create_unix_domain_socket
from xpra.platform.dotxpra import DotXpra
from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT
from multiprocessing import Process

try:
    from xpra.codecs.xor.cyxor import xor_str           #@UnresolvedImport
    xor = xor_str
except:
    pass


PROXY_QUEUE_SIZE = envint("XPRA_PROXY_QUEUE_SIZE", 10)
#for testing only: passthrough as RGB:
PASSTHROUGH = envbool("XPRA_PROXY_PASSTHROUGH", False)
MAX_CONCURRENT_CONNECTIONS = 20
VIDEO_TIMEOUT = 5                  #destroy video encoder after N seconds of idle state


def set_blocking(conn):
    #Note: importing set_socket_timeout from xpra.net.bytestreams
    #fails in mysterious ways, so we duplicate the code here instead
    log("set_blocking(%s)", conn)
    try:
        log("calling %s.setblocking(1)", conn._socket)
        conn._socket.setblocking(1)
    except:
        log("cannot set %s to blocking mode", conn)


class ProxyInstanceProcess(Process):

    def __init__(self, uid, gid, env_options, session_options, socket_dir,
                 video_encoder_modules, csc_modules,
                 client_conn, client_state, cipher, encryption_key, server_conn, caps, message_queue):
        Process.__init__(self, name=str(client_conn))
        self.uid = uid
        self.gid = gid
        self.env_options = env_options
        self.session_options = session_options
        self.socket_dir = socket_dir
        self.video_encoder_modules = video_encoder_modules
        self.csc_modules = csc_modules
        self.client_conn = client_conn
        self.client_state = client_state
        self.cipher = cipher
        self.encryption_key = encryption_key
        self.server_conn = server_conn
        self.caps = caps
        log("ProxyProcess%s", (uid, gid, env_options, session_options, socket_dir,
                               video_encoder_modules, csc_modules,
                               client_conn, repr_ellipsized(str(client_state)), cipher, encryption_key, server_conn,
                               "%s: %s.." % (type(caps), repr_ellipsized(str(caps))), message_queue))
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
        self.control_socket_cleanup = None
        self.control_socket = None
        self.control_socket_thread = None
        self.control_socket_path = None
        self.potential_protocols = []
        self.max_connections = MAX_CONCURRENT_CONNECTIONS

    def server_message_queue(self):
        while True:
            log("waiting for server message on %s", self.message_queue)
            m = self.message_queue.get()
            log("received proxy server message: %s", m)
            if m=="stop":
                self.stop("proxy server request")
                return
            elif m=="socket-handover-complete":
                log("setting sockets to blocking mode: %s", (self.client_conn, self.server_conn))
                #set sockets to blocking mode:
                set_blocking(self.client_conn)
                set_blocking(self.server_conn)
            else:
                log.error("unexpected proxy server message: %s", m)

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
        log("ProxyProcess.run() pid=%s, uid=%s, gid=%s", os.getpid(), getuid(), getgid())
        try:
            import setproctitle
            setproctitle.setproctitle("Xpra Proxy Instance for %s" % self.server_conn)
        except ImportError as e:
            log("setproctitle not installed: %s", e)
        setuidgid(self.uid, self.gid)
        if self.env_options:
            #TODO: whitelist env update?
            os.environ.update(self.env_options)
        self.video_init()

        log.info("new proxy instance started")
        log.info(" for client %s", self.client_conn)
        log.info(" and server %s", self.server_conn)

        signal.signal(signal.SIGTERM, self.signal_quit)
        signal.signal(signal.SIGINT, self.signal_quit)
        log("registered signal handler %s", self.signal_quit)

        start_thread(self.server_message_queue, "server message queue")

        if not self.create_control_socket():
            #TODO: should send a message to the client
            return
        self.control_socket_thread = start_thread(self.control_socket_loop, "control")

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
        if self.caps.boolget("file-transfer"):
            self.client_protocol.large_packets.append("send-file")
            self.client_protocol.large_packets.append("send-file-chunk")
            self.server_protocol.large_packets.append("send-file")
            self.server_protocol.large_packets.append("send-file-chunk")
        self.server_protocol.set_compression_level(self.session_options.get("compression_level", 0))
        self.server_protocol.enable_default_encoder()

        self.lost_windows = set()
        self.encode_queue = Queue()
        self.encode_thread = start_thread(self.encode_loop, "encode")

        log("starting network threads")
        self.server_protocol.start()
        self.client_protocol.start()

        self.send_hello()
        self.timeout_add(VIDEO_TIMEOUT*1000, self.timeout_video_encoders)

        try:
            self.run_queue()
        except KeyboardInterrupt as e:
            self.stop(str(e))
        finally:
            log("ProxyProcess.run() ending %s", os.getpid())

    def video_init(self):
        enclog("video_init() loading codecs")
        load_codecs(decoders=False)
        enclog("video_init() will try video encoders: %s", csv(self.video_encoder_modules) or "none")
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

                for spec in especs:                             #ie: video_spec("x264")
                    spec_props = spec.to_dict()
                    del spec_props["codec_class"]               #not serializable!
                    spec_props["score_boost"] = 50              #we want to win scoring so we get used ahead of other encoders
                    spec_props["max_instances"] = 3             #limit to 3 video streams we proxy for (we really want 2,
                                                                # but because of races with garbage collection, we need to allow more)
                    #store it in encoding defs:
                    self.video_encoding_defs.setdefault(encoding, {}).setdefault(colorspace, []).append(spec_props)
                    encoder_types.add(spec.codec_type)

        enclog("encoder types found: %s", tuple(encoder_types))
        #remove duplicates and use preferred order:
        order = PREFERRED_ENCODER_ORDER[:]
        for x in list(encoder_types):
            if x not in order:
                order.append(x)
        self.video_encoder_types = [x for x in order if x in encoder_types]
        enclog.info("proxy video encoders: %s", ", ".join(self.video_encoder_types or ["none",]))


    def create_control_socket(self):
        assert self.socket_dir
        username = get_username_for_uid(self.uid)
        dotxpra = DotXpra(self.socket_dir, actual_username=username, uid=self.uid, gid=self.gid)
        sockname = ":proxy-%s" % os.getpid()
        sockpath = dotxpra.socket_path(sockname)
        log("%s.socket_path(%s)=%s", dotxpra, sockname, sockpath)
        state = dotxpra.get_server_state(sockpath)
        log("create_control_socket: socket path='%s', uid=%i, gid=%i, state=%s", sockpath, getuid(), getgid(), state)
        if state in (DotXpra.LIVE, DotXpra.UNKNOWN):
            log.error("Error: you already have a proxy server running at '%s'", sockpath)
            log.error(" the control socket will not be created")
            return False
        d = os.path.dirname(sockpath)
        try:
            dotxpra.mksockdir(d)
        except Exception as e:
            log.warn("Warning: failed to create socket directory '%s'", d)
            log.warn(" %s", e)
        try:
            sock, self.control_socket_cleanup = create_unix_domain_socket(sockpath, None, 0o600)
            sock.listen(5)
        except Exception as e:
            log("create_unix_domain_socket failed for '%s'", sockpath, exc_info=True)
            log.error("Error: failed to setup control socket '%s':", sockpath)
            log.error(" %s", e)
            return False
        self.control_socket = sock
        self.control_socket_path = sockpath
        log.info("proxy instance now also available using unix domain socket:")
        log.info(" %s", self.control_socket_path)
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
        protocol.enable_default_encoder()
        protocol.start()
        self.timeout_add(SOCKET_TIMEOUT*1000, self.verify_connection_accepted, protocol)
        return True

    def verify_connection_accepted(self, protocol):
        if not protocol._closed and protocol in self.potential_protocols:
            log.error("connection timedout: %s", protocol)
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def process_control_packet(self, proto, packet):
        try:
            self.do_process_control_packet(proto, packet)
        except Exception as e:
            log.error("error processing control packet", exc_info=True)
            self.send_disconnect(proto, CONTROL_COMMAND_ERROR, str(e))

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
                self.send_disconnect(proto, AUTHENTICATION_ERROR, "this socket does not use authentication")
                return
            if caps.get("info_request", False):
                proto.send_now(("hello", self.get_proxy_info(proto)))
                self.timeout_add(5*1000, self.send_disconnect, proto, CLIENT_EXIT_TIMEOUT, "info sent")
                return
            elif caps.get("stop_request", False):
                self.stop("socket request", None)
                return
            elif caps.get("version_request", False):
                proto.send_now(("hello", {"version" : XPRA_VERSION}))
                self.timeout_add(5*1000, self.send_disconnect, proto, CLIENT_EXIT_TIMEOUT, "version sent")
                return
        self.send_disconnect(proto, CONTROL_COMMAND_ERROR, "this socket only handles 'info', 'version' and 'stop' requests")

    def send_disconnect(self, proto, reason, *extra):
        log("send_disconnect(%s, %s, %s)", proto, reason, extra)
        if proto._closed:
            return
        proto.send_now(["disconnect", reason]+list(extra))
        self.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto):
        proto.close()


    def get_proxy_info(self, proto):
        sinfo = {}
        sinfo.update(get_server_info())
        sinfo.update(get_thread_info(proto))
        return {
            "proxy" : {
                "version"    : XPRA_VERSION,
                ""           : sinfo,
                },
            "window" : self.get_window_info(),
            }

    def send_hello(self, challenge_response=None, client_salt=None):
        hello = self.filter_client_caps(self.caps)
        if challenge_response:
            hello.update({
                          "challenge_response"      : challenge_response,
                          "challenge_client_salt"   : client_salt,
                          })
        self.queue_server_packet(("hello", hello))


    def sanitize_session_options(self, options):
        d = {}
        def number(k, v):
            return parse_number(int, k, v)
        OPTION_WHITELIST = {"compression_level" : number,
                            "lz4"               : parse_bool,
                            "lzo"               : parse_bool,
                            "zlib"              : parse_bool,
                            "rencode"           : parse_bool,
                            "bencode"           : parse_bool,
                            "yaml"              : parse_bool}
        for k,v in options.items():
            parser = OPTION_WHITELIST.get(k)
            if parser:
                log("trying to add %s=%s using %s", k, v, parser)
                try:
                    d[k] = parser(k, v)
                except Exception as e:
                    log.warn("failed to parse value %s for %s using %s: %s", v, k, parser, e)
        return d

    def filter_client_caps(self, caps):
        fc = self.filter_caps(caps, ("cipher", "challenge", "digest", "aliases", "compression", "lz4", "lz0", "zlib"))
        #update with options provided via config if any:
        fc.update(self.sanitize_session_options(self.session_options))
        #add video proxies if any:
        fc["encoding.proxy.video"] = len(self.video_encoding_defs)>0
        if self.video_encoding_defs:
            fc["encoding.proxy.video.encodings"] = self.video_encoding_defs
        return fc

    def filter_server_caps(self, caps):
        self.server_protocol.enable_encoder_from_caps(caps)
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
        pcaps.update(flatten_dict(get_network_caps()))
        #then add the proxy info:
        updict(pcaps, "proxy", get_server_info(), flatten_dicts=True)
        pcaps["proxy"] = True
        pcaps["proxy.hostname"] = socket.gethostname()
        return pcaps


    def run_queue(self):
        log("run_queue() queue has %s items already in it", self.main_queue.qsize())
        #process "idle_add"/"timeout_add" events in the main loop:
        while not self.exit:
            log("run_queue() size=%s", self.main_queue.qsize())
            v = self.main_queue.get()
            if v is None:
                log("run_queue() None exit marker")
                break
            fn, args, kwargs = v
            log("run_queue() %s%s%s", fn, args, kwargs)
            try:
                v = fn(*args, **kwargs)
                if bool(v):
                    #re-run it
                    self.main_queue.put(v)
            except:
                log.error("error during main loop callback %s", fn, exc_info=True)
        self.exit = True
        #wait for connections to close down cleanly before we exit
        for i in range(10):
            if self.client_protocol._closed and self.server_protocol._closed:
                break
            if i==0:
                log.info("waiting for network connections to close")
            else:
                log("still waiting %i/10 - client.closed=%s, server.closed=%s", i+1, self.client_protocol._closed, self.server_protocol._closed)
            sleep(0.1)
        log.info("proxy instance %s stopped", os.getpid())

    def stop(self, reason="proxy terminating", skip_proto=None):
        log.info("stop(%s, %s)", reason, skip_proto)
        self.exit = True
        try:
            self.control_socket.close()
        except:
            pass
        csc = self.control_socket_cleanup
        if csc:
            self.control_socket_cleanup = None
            csc()
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
                log("sending disconnect to %s", proto)
                proto.flush_then_close(["disconnect", SERVER_SHUTDOWN, reason])


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
        elif packet_type=="disconnect":
            log("got disconnect from client: %s", packet[1])
            if self.exit:
                self.client_protocol.close()
            else:
                self.stop("disconnect from client: %s" % packet[1])
        elif packet_type=="set_deflate":
            #echo it back to the client:
            self.client_packets.put(packet)
            self.client_protocol.source_has_more()
            return
        elif packet_type=="hello":
            log.warn("Warning: invalid hello packet received after initial authentication (dropped)")
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


    def _packet_recompress(self, packet, index, name):
        if len(packet)>index:
            data = packet[index]
            if len(data)<512:
                packet[index] = str(data)
                return
            #FIXME: this is ugly and not generic!
            zlib = compression.use_zlib and self.caps.boolget("zlib", True)
            lz4 = compression.use_lz4 and self.caps.boolget("lz4", False)
            lzo = compression.use_lzo and self.caps.boolget("lzo", False)
            if zlib or lz4 or lzo:
                packet[index] = compressed_wrapper(name, data, zlib=zlib, lz4=lz4, lzo=lzo, can_inline=False)
            else:
                #prevent warnings about large uncompressed data
                packet[index] = Compressed("raw %s" % name, data, can_inline=True)

    def process_server_packet(self, proto, packet):
        packet_type = packet[0]
        log("process_server_packet: %s", packet_type)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("server connection lost", proto)
            return
        elif packet_type=="disconnect":
            log("got disconnect from server: %s", packet[1])
            if self.exit:
                self.server_protocol.close()
            else:
                self.stop("disconnect from server: %s" % packet[1])
        elif packet_type=="hello":
            c = typedict(packet[1])
            maxw, maxh = c.intpair("max_desktop_size", (4096, 4096))
            caps = self.filter_server_caps(c)
            #add new encryption caps:
            if self.cipher:
                from xpra.net.crypto import crypto_backend_init, new_cipher_caps, DEFAULT_PADDING
                crypto_backend_init()
                padding_options = self.caps.strlistget("cipher.padding.options", [DEFAULT_PADDING])
                auth_caps = new_cipher_caps(self.client_protocol, self.cipher, self.encryption_key, padding_options)
                caps.update(auth_caps)
            #may need to bump packet size:
            proto.max_packet_size = maxw*maxh*4*4
            file_transfer = self.caps.boolget("file-transfer") and c.boolget("file-transfer")
            file_size_limit = max(self.caps.intget("file-size-limit"), c.intget("file-size-limit"))
            file_max_packet_size = int(file_transfer) * (1024 + file_size_limit*1024*1024)
            self.client_protocol.max_packet_size = max(self.client_protocol.max_packet_size, file_max_packet_size)
            self.server_protocol.max_packet_size = max(self.server_protocol.max_packet_size, file_max_packet_size)
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
        #we do want to reformat cursor packets...
        #as they will have been uncompressed by the network layer already:
        elif packet_type=="cursor":
            #packet = ["cursor", x, y, width, height, xhot, yhot, serial, pixels, name]
            #or:
            #packet = ["cursor", "png", x, y, width, height, xhot, yhot, serial, pixels, name]
            #or:
            #packet = ["cursor", ""]
            if len(packet)>=8:
                #hard to distinguish png cursors from normal cursors...
                try:
                    int(packet[1])
                    self._packet_recompress(packet, 8, "cursor")
                except:
                    self._packet_recompress(packet, 9, "cursor")
        elif packet_type=="window-icon":
            self._packet_recompress(packet, 5, "icon")
        elif packet_type=="send-file":
            if packet[6]:
                packet[6] = Compressed("file-data", packet[6])
        elif packet_type=="send-file-chunk":
            if packet[3]:
                packet[3] = Compressed("file-chunk-data", packet[3])
        elif packet_type=="challenge":
            from xpra.net.crypto import get_salt, get_digest_module
            #client may have already responded to the challenge,
            #so we have to handle authentication from this end
            salt = packet[1]
            digest = packet[3]
            client_salt = get_salt(len(salt))
            salt = xor_str(salt, client_salt)
            digestmod = get_digest_module(digest)
            if not digestmod:
                self.stop("digest mode '%s' not supported", std(digest))
                return
            password = self.session_options.get("password")
            if not password:
                self.stop("authentication requested by the server, but no password available for this session")
                return
            import hmac
            password = strtobytes(password)
            salt = memoryview_to_bytes(salt)
            challenge_response = hmac.HMAC(password, salt, digestmod=digestmod).hexdigest()
            log.info("sending %s challenge response", digest)
            self.send_hello(challenge_response, client_salt)
            return
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
                    now = monotonic_time()
                    idle_time = now-self.video_encoders_last_used_time.get(wid)
                    if ve and idle_time>VIDEO_TIMEOUT:
                        enclog("timing out the video encoder context for window %s", wid)
                        #timeout is confirmed, we are in the encoding thread,
                        #so it is now safe to clean it up:
                        ve.clean()
                        del self.video_encoders[wid]
                        del self.video_encoders_last_used_time[wid]
                else:
                    enclog.warn("unexpected encode packet: %s", packet_type)
            except:
                enclog.warn("error encoding packet", exc_info=True)


    def process_draw(self, packet):
        wid, x, y, width, height, encoding, pixels, _, rowstride, client_options = packet[1:11]
        #never modify mmap packets
        if encoding in ("mmap", "scroll"):
            return True

        #we have a proxy video packet:
        rgb_format = client_options.get("rgb_format", "")
        enclog("proxy draw: client_options=%s", client_options)

        def send_updated(encoding, compressed_data, updated_client_options):
            #update the packet with actual encoding data used:
            packet[6] = encoding
            packet[7] = compressed_data
            packet[10] = updated_client_options
            enclog("returning %s bytes from %s, options=%s", len(compressed_data), len(pixels), updated_client_options)
            return (wid not in self.lost_windows)

        def passthrough(strip_alpha=True):
            enclog("proxy draw: %s passthrough (rowstride: %s vs %s, strip alpha=%s)", rgb_format, rowstride, client_options.get("rowstride", 0), strip_alpha)
            if strip_alpha:
                #passthrough as plain RGB:
                Xindex = rgb_format.upper().find("X")
                if Xindex>=0 and len(rgb_format)==4:
                    #force clear alpha (which may be garbage):
                    newdata = bytearray(pixels)
                    for i in range(len(pixels)/4):
                        newdata[i*4+Xindex] = chr(255)
                    packet[9] = client_options.get("rowstride", 0)
                    cdata = bytes(newdata)
                else:
                    cdata = pixels
                new_client_options = {"rgb_format" : rgb_format}
            else:
                #preserve
                cdata = pixels
                new_client_options = client_options
            wrapped = Compressed("%s pixels" % encoding, cdata)
            #FIXME: we should not assume that rgb32 is supported here...
            #(we may have to convert to rgb24..)
            return send_updated("rgb32", wrapped, new_client_options)

        proxy_video = client_options.get("proxy", False)
        if PASSTHROUGH and (encoding in ("rgb32", "rgb24") or proxy_video):
            #we are dealing with rgb data, so we can pass it through:
            return passthrough(proxy_video)
        elif not self.video_encoder_types or not client_options or not proxy_video:
            #ensure we don't try to re-compress the pixel data in the network layer:
            #(re-add the "compressed" marker that gets lost when we re-assemble packets)
            packet[7] = Compressed("%s pixels" % encoding, packet[7])
            return True

        #video encoding: find existing encoder
        ve = self.video_encoders.get(wid)
        if ve:
            if ve in self.lost_windows:
                #we cannot clean the video encoder here, there may be more frames queue up
                #"lost-window" in encode_loop will take care of it safely
                return False
            #we must verify that the encoder is still valid
            #and scrap it if not (ie: when window is resized)
            if ve.get_width()!=width or ve.get_height()!=height:
                enclog("closing existing video encoder %s because dimensions have changed from %sx%s to %sx%s", ve, ve.get_width(), ve.get_height(), width, height)
                ve.clean()
                ve = None
            elif ve.get_encoding()!=encoding:
                enclog("closing existing video encoder %s because encoding has changed from %s to %s", ve.get_encoding(), encoding)
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
                enc_pillow = get_codec("enc_pillow")
                if not enc_pillow:
                    from xpra.server.picture_encode import warn_encoding_once
                    warn_encoding_once("no-video-no-PIL", "no video encoder found for rgb format %s, sending as plain RGB!" % rgb_format)
                    return passthrough(True)
                enclog("no video encoder available: sending as jpeg")
                coding, compressed_data, client_options, _, _, _, _ = enc_pillow.encode("jpeg", image, quality, speed, False)
                return send_updated(coding, compressed_data, client_options)

            enclog("creating new video encoder %s for window %s", spec, wid)
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
            self.video_encoders_last_used_time[wid] = monotonic_time()      #just to make sure this is always set
        #actual video compression:
        enclog("proxy compression using %s with quality=%s, speed=%s", ve, quality, speed)
        data, out_options = ve.compress_image(image, quality, speed, encoder_options)
        #pass through some options if we don't have them from the encoder
        #(maybe we should also use the "pts" from the real server?)
        for k in ("timestamp", "rgb_format", "depth", "csc"):
            if k not in out_options and k in client_options:
                out_options[k] = client_options[k]
        self.video_encoders_last_used_time[wid] = monotonic_time()
        return send_updated(ve.get_encoding(), Compressed(encoding, data), out_options)

    def timeout_video_encoders(self):
        #have to be careful as another thread may come in...
        #so we just ask the encode thread (which deals with encoders already)
        #to do what may need to be done if we find a timeout:
        now = monotonic_time()
        for wid in list(self.video_encoders_last_used_time.keys()):
            idle_time = int(now-self.video_encoders_last_used_time.get(wid))
            if idle_time is None:
                continue
            enclog("timeout_video_encoders() wid=%s, idle_time=%s", wid, idle_time)
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
                        enclog("_find_video_encoder(%s, %s)=%s", encoding, rgb_format, spec)
                        return spec
        enclog("_find_video_encoder(%s, %s) not found", encoding, rgb_format)
        return None

    def get_window_info(self):
        info = {}
        now = monotonic_time()
        for wid, encoder in self.video_encoders.items():
            einfo = encoder.get_info()
            einfo["idle_time"] = int(now-self.video_encoders_last_used_time.get(wid, 0))
            info[wid] = {
                         "proxy"    : {
                                       ""           : encoder.get_type(),
                                       "encoder"    : einfo
                                       },
                         }
        enclog("get_window_info()=%s", info)
        return info
