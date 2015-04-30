# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import types
import os
import sys
import time
import socket
import signal
import threading
import thread

from xpra.log import Logger
log = Logger("server")
netlog = Logger("network")
proxylog = Logger("proxy")
commandlog = Logger("command")

import xpra
from xpra.server import ClientException
from xpra.scripts.main import SOCKET_TIMEOUT, _socket_connect
from xpra.scripts.config import ENCRYPTION_CIPHERS
from xpra.scripts.server import deadly_signal
from xpra.net.bytestreams import SocketConnection
from xpra.platform import set_application_name
from xpra.os_util import load_binary_file, get_machine_id, get_user_uuid, SIGNAMES, Queue
from xpra.version_util import version_compat_check, get_version_info, get_platform_info, get_host_info, local_version
from xpra.net.protocol import Protocol, get_network_caps, sanity_checks
from xpra.net.crypto import new_cipher_caps
from xpra.server.background_worker import stop_worker, get_worker
from xpra.daemon_thread import make_daemon_thread
from xpra.server.proxy import XpraProxy
from xpra.util import typedict, updict, repr_ellipsized, \
        SERVER_SHUTDOWN, SERVER_EXIT, LOGIN_TIMEOUT, DONE, PROTOCOL_ERROR, SERVER_ERROR, VERSION_ERROR, AUTHENTICATION_ERROR

main_thread = threading.current_thread()

MAX_CONCURRENT_CONNECTIONS = 20


def get_server_info():
    #this function is for non UI thread info
    info = {}
    info.update(get_host_info())
    def up(prefix, d):
        updict(info, prefix, d)
    up("platform",  get_platform_info())
    up("build",     get_version_info())
    return info

def get_thread_info(proto=None, protocols=[]):
    #threads:
    info_threads = proto.get_threads()
    info = {
            "count"        : threading.active_count() - len(info_threads),
            "info.count"   : len(info_threads)
            }
    thread_ident = {
            threading.current_thread().ident    : "info",
            main_thread.ident                   : "main",
            }
    w = get_worker(False)
    if w:
        thread_ident[w.ident] = "worker"

    #threads used by the "info" client:
    for i, t in enumerate(info_threads):
        info["info[%s]" % i] = t.getName()
        thread_ident[t.ident] = t.getName()
    for p in protocols:
        try:
            threads = p.get_threads()
            for t in threads:
                thread_ident[t.ident] = t.getName()
        except:
            pass
    #all non-info threads:
    for i, t in enumerate((x for x in threading.enumerate() if x not in info_threads)):
        info[str(i)] = t.getName()
    #platform specific bits:
    try:
        from xpra.platform.info import get_sys_info
        info.update(get_sys_info())
    except:
        log.error("error getting system info", exc_info=True)
    #extract frame info:
    try:
        def nn(x):
            if x is None:
                return ""
            return x
        import traceback
        frames = sys._current_frames()
        for i,frame_pair in enumerate(frames.items()):
            stack = traceback.extract_stack(frame_pair[1])
            info["frame[%s].thread" % i] = thread_ident.get(frame_pair[0], "unknown")
            #sanitize stack to prevent None values (which cause encoding errors with the bencoder)
            sanestack = []
            for e in stack:
                sanestack.append(tuple([nn(x) for x in e]))
            info["frame[%s].stack" % i] = sanestack
    except Exception as e:
        log.error("failed to get frame info: %s", e)
    return info


class ServerCore(object):
    """
        This is the simplest base class for servers.
        It only handles establishing the connection.
    """

    #magic value to distinguish exit code for upgrading (True==1)
    #and exiting:
    EXITING_CODE = 2

    def __init__(self):
        log("ServerCore.__init__()")
        self.start_time = time.time()
        self.auth_class = None
        self.tcp_auth_class = None
        self._when_ready = []
        self.child_reaper = None

        self._upgrading = False
        #networking bits:
        self._potential_protocols = []
        self._tcp_proxy_clients = []
        self._tcp_proxy = ""
        self._aliases = {}
        self._reverse_aliases = {}
        self.socket_types = {}
        self._max_connections = MAX_CONCURRENT_CONNECTIONS
        self._socket_timeout = 0.1
        self._socket_dir = None

        self.session_name = ""

        #Features:
        self.digest_modes = ("hmac", )
        self.encryption_keyfile = None
        self.password_file = None
        self.compression_level = 1
        self.exit_with_client = False

        #control mode:
        self.control_commands = ["hello"]

        self.init_packet_handlers()
        self.init_aliases()
        sanity_checks()

    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()

    def init(self, opts):
        log("ServerCore.init(%s)", opts)
        self.session_name = opts.session_name
        set_application_name(self.session_name or "Xpra")

        self._socket_dir = opts.socket_dir
        self._tcp_proxy = opts.tcp_proxy
        self.encryption_keyfile = opts.encryption_keyfile
        self.password_file = opts.password_file
        self.compression_level = opts.compression_level
        self.exit_with_client = opts.exit_with_client

        self.init_auth(opts)

    def init_auth(self, opts):
        self.auth_class = self.get_auth_module(opts.auth, opts.password_file)
        self.tcp_auth_class = self.get_auth_module(opts.tcp_auth or opts.auth, opts.password_file)
        log("init_auth(%s) auth class=%s, tcp auth class=%s", opts, self.auth_class, self.tcp_auth_class)

    def get_auth_module(self, auth, password_file):
        if not auth and password_file:
            log.warn("no authentication module specified with 'password_file', using 'file' based authentication")
            auth = "file"
        if not auth and os.environ.get('XPRA_PASSWORD'):
            log.warn("no authentication module specified with 'XPRA_PASSWORD', using 'file' based authentication")
            auth = "file"
        if auth=="":
            return None
        elif auth=="sys":
            #resolve virtual "sys" auth:
            if sys.platform.startswith("win"):
                auth = "win32"
            else:
                auth = "pam"
            log("will try to use sys auth module '%s' for %s", auth, sys.platform)
        from xpra.server.auth import fail_auth, reject_auth, allow_auth, none_auth, file_auth
        AUTH_MODULES = {
                        "fail"      : fail_auth,
                        "reject"    : reject_auth,
                        "allow"     : allow_auth,
                        "none"      : none_auth,
                        "file"      : file_auth
                        }
        try:
            from xpra.server.auth import pam_auth
            AUTH_MODULES["pam"] = pam_auth
        except Exception as e:
            log("cannot load pam auth: %s", e)
        try:
            from xpra.server.auth import win32_auth
            AUTH_MODULES["win32"] = win32_auth
        except Exception as e:
            log("cannot load win32 auth: %s", e)
        auth_module = AUTH_MODULES.get(auth.lower())
        if not auth_module:
            raise Exception("cannot find authentication module '%s' (supported: %s)", auth, AUTH_MODULES.keys())
        try:
            auth_class = getattr(auth_module, "Authenticator")
            return auth_class
        except Exception as e:
            raise Exception("Authenticator class not found in %s" % auth_module)


    def init_sockets(self, sockets):
        ### All right, we're ready to accept customers:
        for socktype, sock in sockets:
            log("init_sockets(%s) will add %s socket %s", sockets, socktype, sock)
            self.idle_add(self.add_listen_socket, socktype, sock)

    def init_when_ready(self, callbacks):
        self._when_ready = callbacks


    def init_packet_handlers(self):
        log("initializing packet handlers")
        self._default_packet_handlers = {
            "hello":                                self._process_hello,
            Protocol.CONNECTION_LOST:               self._process_connection_lost,
            Protocol.GIBBERISH:                     self._process_gibberish,
            Protocol.INVALID:                       self._process_invalid,
            }

    def init_aliases(self):
        self.do_init_aliases(self._default_packet_handlers.keys())

    def do_init_aliases(self, packet_types):
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1


    def reaper_quit(self):
        self.clean_quit()

    def signal_quit(self, signum, frame):
        log.info("")
        log.info("got signal %s, exiting", SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.idle_add(self.clean_quit)

    def clean_quit(self, upgrading=False):
        log("clean_quit(%s)", upgrading)
        #ensure the reaper doesn't call us again:
        if self.child_reaper:
            def noop():
                pass
            self.reaper_quit = noop
            log("clean_quit: reaper_quit=%s", self.reaper_quit)
        self.cleanup()
        def quit_timer(*args):
            log.debug("quit_timer()")
            self.quit(upgrading)
        #if from a signal, just force quit:
        stop_worker()
        #not from signal: use force stop worker after delay
        self.timeout_add(250, stop_worker, True)
        self.timeout_add(500, quit_timer)
        def force_quit(*args):
            log.debug("force_quit()")
            from xpra import os_util
            os_util.force_quit()
        self.timeout_add(5000, force_quit)
        log("clean_quit(..) quit timers scheduled")

    def quit(self, upgrading):
        log("quit(%s)", upgrading)
        self._upgrading = upgrading
        log.info("xpra is terminating.")
        sys.stdout.flush()
        self.do_quit()
        log("quit(%s) do_quit done!", upgrading)

    def do_quit(self):
        raise NotImplementedError()

    def get_server_mode(self):
        return "server"

    def run(self):
        try:
            from xpra.src_info import REVISION
            rev_info = " (r%s)" % REVISION
        except:
            rev_info = ""
        log.info("xpra %s version %s%s", self.get_server_mode(), local_version, rev_info)
        log.info("running with pid %s", os.getpid())
        signal.signal(signal.SIGTERM, self.signal_quit)
        signal.signal(signal.SIGINT, self.signal_quit)
        def start_ready_callbacks():
            for x in self._when_ready:
                try:
                    x()
                except Exception as e:
                    log.error("error on %s: %s", x, e)
        self.idle_add(start_ready_callbacks)
        def print_ready():
            log.info("xpra is ready.")
            sys.stdout.flush()
        self.idle_add(print_ready)
        self.do_run()
        return self._upgrading

    def do_run(self):
        raise NotImplementedError()

    def cleanup(self, *args):
        netlog("cleanup() stopping %s tcp proxy clients: %s", len(self._tcp_proxy_clients), self._tcp_proxy_clients)
        for p in list(self._tcp_proxy_clients):
            p.quit()
        netlog("cleanup will disconnect: %s", self._potential_protocols)
        if self._upgrading:
            reason = SERVER_EXIT
        else:
            reason = SERVER_SHUTDOWN
        for proto in list(self._potential_protocols):
            self.disconnect_client(proto, reason)
        self._potential_protocols = []

    def add_listen_socket(self, socktype, socket):
        raise NotImplementedError()

    def _new_connection(self, listener, *args):
        socktype = self.socket_types.get(listener)
        assert socktype, "cannot find socket type for %s" % listener
        sock, address = listener.accept()
        if len(self._potential_protocols)>=self._max_connections:
            netlog.error("too many connections (%s), ignoring new one", len(self._potential_protocols))
            sock.close()
            return  True
        try:
            peername = sock.getpeername()
        except:
            peername = str(address)
        sockname = sock.getsockname()
        target = peername or sockname
        sock.settimeout(self._socket_timeout)
        netlog("new_connection(%s) sock=%s, timeout=%s, sockname=%s, address=%s, peername=%s", args, sock, self._socket_timeout, sockname, address, peername)
        sc = SocketConnection(sock, sockname, address, target, socktype)
        netlog("socket connection: %s", sc)
        frominfo = ""
        if peername:
            frominfo = " from %s" % str(peername)
        netlog.info("New %s connection received%s", socktype, frominfo)
        protocol = Protocol(self, sc, self.process_packet)
        protocol.large_packets.append("info-response")
        protocol.authenticator = None
        if socktype=="tcp":
            protocol.auth_class = self.tcp_auth_class
        else:
            protocol.auth_class = self.auth_class
        protocol.socket_type = socktype
        protocol.invalid_header = self.invalid_header
        protocol.receive_aliases.update(self._aliases)
        self._potential_protocols.append(protocol)
        protocol.start()
        self.timeout_add(SOCKET_TIMEOUT*1000, self.verify_connection_accepted, protocol)
        return True

    def invalid_header(self, proto, data):
        netlog("invalid_header(%s, %s bytes: '%s') input_packetcount=%s, tcp_proxy=%s", proto, len(data or ""), repr_ellipsized(data), proto.input_packetcount, self._tcp_proxy)
        if proto.input_packetcount==0 and self._tcp_proxy:
            #start a new proxy in a thread
            def run_proxy():
                self.start_tcp_proxy(proto, data)
            t = make_daemon_thread(run_proxy, "web-proxy-for-%s" % proto)
            t.start()
            return
        err = "invalid packet format, not an xpra client?"
        proto.gibberish(err, data)

    def start_tcp_proxy(self, proto, data):
        proxylog("start_tcp_proxy(%s, '%s')", proto, repr_ellipsized(data))
        self._potential_protocols.remove(proto)
        proxylog("start_tcp_proxy: protocol state before stealing: %s", proto.get_info(alias_info=False))
        #any buffers read after we steal the connection will be placed in this temporary queue:
        temp_read_buffer = Queue()
        client_connection = proto.steal_connection(temp_read_buffer.put)
        #connect to web server:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        host, port = self._tcp_proxy.split(":", 1)
        try:
            web_server_connection = _socket_connect(sock, (host, int(port)), "web-proxy-for-%s" % proto, "tcp")
        except:
            proxylog.warn("failed to connect to proxy: %s:%s", host, port)
            proto.gibberish("invalid packet header", data)
            return
        proxylog("proxy connected to tcp server at %s:%s : %s", host, port, web_server_connection)
        sock.settimeout(self._socket_timeout)

        ioe = proto.wait_for_io_threads_exit(0.5+self._socket_timeout)
        if not ioe:
            proxylog.warn("proxy failed to stop all existing network threads!")
            self.disconnect_protocol(proto, "internal threading error")
            return
        #now that we own it, we can start it again:
        client_connection.set_active(True)
        #and we can use blocking sockets:
        self.set_socket_timeout(client_connection, None)
        sock.settimeout(None)

        proxylog("pushing initial buffer to its new destination: %s", repr_ellipsized(data))
        web_server_connection.write(data)
        while not temp_read_buffer.empty():
            buf = temp_read_buffer.get()
            if buf:
                proxylog("pushing read buffer to its new destination: %s", repr_ellipsized(buf))
                web_server_connection.write(buf)
        p = XpraProxy(client_connection.target, client_connection, web_server_connection)
        self._tcp_proxy_clients.append(p)
        proxylog.info("client connection from %s forwarded to proxy server on %s:%s", client_connection.target, host, port)
        p.run()
        proxylog("run_proxy() %s ended", p)
        if p in self._tcp_proxy_clients:
            self._tcp_proxy_clients.remove(p)

    def is_timedout(self, protocol):
        #subclasses may override this method (ServerBase does)
        v = not protocol._closed and protocol in self._potential_protocols and \
            protocol not in self._tcp_proxy_clients
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def verify_connection_accepted(self, protocol):
        if self.is_timedout(protocol):
            log.error("connection timedout: %s", protocol)
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def send_disconnect(self, proto, reason, *extra):
        netlog("send_disconnect(%s, %s, %s)", proto, reason, extra)
        if proto._closed:
            return
        proto.send_now(["disconnect", reason]+list(extra))
        self.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto):
        netlog("force_disconnect(%s)", proto)
        proto.close()

    def disconnect_client(self, protocol, reason, *extra):
        netlog("disconnect_client(%s, %s, %s)", protocol, reason, extra)
        if protocol and not protocol._closed:
            self.disconnect_protocol(protocol, reason, *extra)

    def disconnect_protocol(self, protocol, reason, *extra):
        netlog("disconnect_protocol(%s, %s, %s)", protocol, reason, extra)
        i = str(reason)
        if extra:
            i += " (%s)" % extra
        try:
            proto_info = " '%s'" % protocol._conn.get_info().get("endpoint")
        except:
            proto_info = " %s" % protocol
        netlog.info("Disconnecting client%s: %s", proto_info, i)
        protocol.flush_then_close(["disconnect", reason]+list(extra))


    def _process_connection_lost(self, proto, packet):
        netlog("process_connection_lost(%s, %s)", proto, packet)
        if proto in self._potential_protocols:
            netlog.info("Connection lost")
            self._potential_protocols.remove(proto)

    def _process_gibberish(self, proto, packet):
        (_, message, data) = packet
        netlog("Received uninterpretable nonsense from %s: %s", proto, message)
        netlog(" data: %s", repr_ellipsized(data))
        self.disconnect_client(proto, message)

    def _process_invalid(self, protocol, packet):
        (_, message, data) = packet
        netlog("Received invalid packet: %s", message)
        netlog(" data: %s", repr_ellipsized(data))
        self.disconnect_client(protocol, message)


    def send_version_info(self, proto):
        response = {"version" : xpra.__version__}
        proto.send_now(("hello", response))
        #client is meant to close the connection itself, but just in case:
        self.timeout_add(5*1000, self.send_disconnect, proto, DONE, "version sent")

    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        c = typedict(capabilities)
        proto.set_compression_level(c.intget("compression_level", self.compression_level))
        proto.enable_compressor_from_caps(c)
        if not proto.enable_encoder_from_caps(c):
            #this should never happen:
            #if we got here, we parsed a packet from the client!
            #(maybe the client used an encoding it claims not to support?)
            self.disconnect_client(proto, PROTOCOL_ERROR, "failed to negotiate a packet encoder")
            return

        log("process_hello: capabilities=%s", capabilities)
        if c.boolget("version_request"):
            self.send_version_info(proto)
            return

        auth_caps = self.verify_hello(proto, c)
        if auth_caps is not False:
            if c.boolget("info_request", False):
                self.send_hello_info(proto)
                return
            command_req = c.strlistget("command_request")
            if len(command_req)>0:
                #call from UI thread:
                self.idle_add(self.handle_command_request, proto, command_req)
                return
            #continue processing hello packet:
            try:
                self.hello_oked(proto, packet, c, auth_caps)
            except ClientException as e:
                log.error("error setting up connection for %s: %s", proto, e)
                self.disconnect_client(proto, SERVER_ERROR, str(e))
            except Exception as e:
                #log exception but don't disclose internal details to the client
                log.error("server error processing new connection from %s: %s", proto, e, exc_info=True)
                self.disconnect_client(proto, SERVER_ERROR, "error accepting new connection")

    def set_socket_timeout(self, conn, timeout=None):
        #FIXME: this is ugly, but less intrusive than the alternative?
        if isinstance(conn, SocketConnection):
            conn._socket.settimeout(timeout)


    def verify_hello(self, proto, c):
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, VERSION_ERROR, "incompatible version: %s" % verr)
            proto.close()
            return  False

        def auth_failed(msg):
            log.info("authentication failed: %s", msg)
            self.timeout_add(1000, self.disconnect_client, proto, msg)

        #authenticator:
        username = c.strget("username")
        if proto.authenticator is None and proto.auth_class:
            try:
                proto.authenticator = proto.auth_class(username)
            except Exception as e:
                log.warn("error instantiating %s: %s", proto.auth_class, e)
                auth_failed("authentication failed")
                return False
        self.digest_modes = c.get("digest", ("hmac", ))

        #client may have requested encryption:
        cipher = c.strget("cipher")
        cipher_iv = c.strget("cipher.iv")
        key_salt = c.strget("cipher.key_salt")
        iterations = c.intget("cipher.key_stretch_iterations")
        auth_caps = {}
        if cipher and cipher_iv:
            if cipher not in ENCRYPTION_CIPHERS:
                log.warn("unsupported cipher: %s", cipher)
                auth_failed("unsupported cipher")
                return False
            encryption_key = self.get_encryption_key(proto.authenticator)
            if encryption_key is None:
                auth_failed("encryption key is missing")
                return False
            proto.set_cipher_out(cipher, cipher_iv, encryption_key, key_salt, iterations)
            #use the same cipher as used by the client:
            auth_caps = new_cipher_caps(proto, cipher, encryption_key)
            log("server cipher=%s", auth_caps)
        else:
            auth_caps = None

        #verify authentication if required:
        if proto.authenticator and proto.authenticator.requires_challenge():
            challenge_response = c.strget("challenge_response")
            client_salt = c.strget("challenge_client_salt")
            log("processing authentication with %s, response=%s, client_salt=%s", proto.authenticator, challenge_response, binascii.hexlify(client_salt or ""))
            #send challenge if this is not a response:
            if not challenge_response:
                challenge = proto.authenticator.get_challenge()
                if challenge is None:
                    auth_failed("invalid authentication state: unexpected challenge response")
                    return False
                salt, digest = challenge
                log.info("Authentication required, %s sending challenge for '%s' using digest %s", proto.authenticator, username, digest)
                if digest not in self.digest_modes:
                    auth_failed("cannot proceed without %s digest support" % digest)
                    return False
                proto.send_now(("challenge", salt, auth_caps or "", digest))
                return False

            if not proto.authenticator.authenticate(challenge_response, client_salt):
                auth_failed("invalid challenge response")
                return False
            log("authentication challenge passed")
        else:
            #did the client expect a challenge?
            if c.boolget("challenge"):
                self.disconnect_client(proto, AUTHENTICATION_ERROR, "this server does not require authentication")
                return False
        return auth_caps

    def filedata_nocrlf(self, filename):
        v = load_binary_file(filename)
        if v is None:
            log.error("failed to load '%s'", filename)
            return None
        return v.strip("\n\r")

    def get_encryption_key(self, authenticator=None):
        #if we have a keyfile specified, use that:
        if self.encryption_keyfile:
            netlog("trying to load encryption key from keyfile: %s", self.encryption_keyfile)
            return self.filedata_nocrlf(self.encryption_keyfile)
        env_key = os.environ.get('XPRA_ENCRYPTION_KEY')
        if env_key:
            return env_key
        v = None
        if authenticator:
            netlog("trying to get encryption key from: %s", authenticator)
            v = authenticator.get_password()
        if v is None and self.password_file:
            netlog("trying to load encryption key from password file: %s", self.password_file)
            v = self.filedata_nocrlf(self.password_file)
        if v is None and os.environ.get('XPRA_PASSWORD'):
            v = os.environ.get('XPRA_PASSWORD')
        return v

    def hello_oked(self, proto, packet, c, auth_caps):
        pass


    def handle_command_request(self, proto, args):
        """ client sent a command request as part of the hello packet """
        try:
            assert len(args)>0
            command = args[0]
            error = 0
            if command not in self.control_commands:
                commandlog.warn("invalid command: '%s' (must be one of: %s)", command, ", ".join(self.control_commands))
                error = 6
                response = "invalid command"
            else:
                error, response = self.do_handle_command_request(command, args[1:])
        except Exception as e:
            commandlog.error("error processing command %s", command, exc_info=True)
            error = 127
            response = "error processing command: %s" % e
        hello = {"command_response"  : (error, response)}
        proto.send_now(("hello", hello))

    def do_handle_command_request(self, command, args):
        """ this may get called by:
            * handle_command_request from a hello packet
            * _process_command_request from a dedicated packet
            it is overriden in subclasses.
        """
        if command=="hello":
            return 0, "hello"
        elif command=="help":
            return 0, "control supports: %s" % (", ".join(self.control_commands))
        return 9, "invalid command '%s'" % command


    def accept_client(self, proto, c):
        #max packet size from client (the biggest we can get are clipboard packets)
        netlog("accept_client(%s, %s)", proto, c)
        proto.max_packet_size = 1024*1024  #1MB
        proto.send_aliases = c.dictget("aliases")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)

    def make_hello(self, source):
        now = time.time()
        capabilities = get_network_caps()
        if source.wants_versions:
            capabilities.update(get_server_info())
        capabilities.update({
                        "version"               : xpra.__version__,
                        "start_time"            : int(self.start_time),
                        "current_time"          : int(now),
                        "elapsed_time"          : int(now - self.start_time),
                        "server_type"           : "core",
                        })
        if source.wants_features:
            capabilities["info-request"] = True
        if source.wants_versions:
            capabilities["uuid"] = get_user_uuid()
            mid = get_machine_id()
            if mid:
                capabilities["machine_id"] = mid
        if self.session_name:
            capabilities["session_name"] = self.session_name
        return capabilities


    def send_hello_info(self, proto):
        #Note: this can be overriden in subclasses to pass arguments to get_ui_info()
        #(ie: see server_base)
        log.info("processing info request from %s", proto._conn)
        self.get_all_info(self.do_send_info, proto)

    def do_send_info(self, proto, info):
        proto.send_now(("hello", info))

    def get_all_info(self, callback, proto, *args):
        ui_info = self.get_ui_info(proto, *args)
        def in_thread(*args):
            #this runs in a non-UI thread
            try:
                info = self.get_info(proto, *args)
                ui_info.update(info)
            except Exception as e:
                log.error("error during info collection: %s", e, exc_info=True)
            callback(proto, ui_info)
        thread.start_new_thread(in_thread, ())

    def get_ui_info(self, proto, *args):
        #this function is for info which MUST be collected from the UI thread
        return {}

    def get_thread_info(self, proto):
        return get_thread_info(proto)

    def get_info(self, proto, *args):
        #this function is for non UI thread info
        info = {}
        def up(prefix, d):
            updict(info, prefix, d)
        filtered_env = os.environ.copy()
        if filtered_env.get('XPRA_PASSWORD'):
            filtered_env['XPRA_PASSWORD'] = "*****"
        if filtered_env.get('XPRA_ENCRYPTION_KEY'):
            filtered_env['XPRA_ENCRYPTION_KEY'] = "*****"

        up("network",   get_network_caps())
        up("server",    get_server_info())
        up("threads",   self.get_thread_info(proto))
        up("env",       filtered_env)
        up("server", {
                "mode"              : self.get_server_mode(),
                "type"              : "Python",
                "start_time"        : int(self.start_time),
                "authenticator"     : str((self.auth_class or str)("")),
                "argv"              : sys.argv,
                "path"              : sys.path,
                "exec_prefix"       : sys.exec_prefix,
                "executable"        : sys.executable,
                })
        if self.session_name:
            info["session.name"] = self.session_name
        if self.child_reaper:
            info.update(self.child_reaper.get_info())
        return info

    def process_packet(self, proto, packet):
        try:
            handler = None
            packet_type = packet[0]
            assert isinstance(packet_type, types.StringTypes), "packet_type %s is not a string: %s..." % (type(packet_type), str(packet_type)[:100])
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                netlog("process packet %s", packet_type)
                handler(proto, packet)
                return
            netlog.error("unknown or invalid packet type: %s from %s", packet_type, proto)
            proto.close()
        except KeyboardInterrupt:
            raise
        except:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
