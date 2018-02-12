# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import os
import sys
import time
import socket
import signal
import threading
import traceback

from xpra.log import Logger
log = Logger("server")
netlog = Logger("network")
httplog = Logger("http")
wslog = Logger("websocket")
proxylog = Logger("proxy")
commandlog = Logger("command")
authlog = Logger("auth")
timeoutlog = Logger("timeout")

import xpra
from xpra.server import ClientException
from xpra.scripts.main import _socket_connect, full_version_str
from xpra.scripts.server import deadly_signal
from xpra.scripts.config import InitException, parse_bool, python_platform
from xpra.net.bytestreams import SocketConnection, log_new_connection, inject_ssl_socket_info, pretty_socket, SOCKET_TIMEOUT
from xpra.platform import set_name
from xpra.os_util import load_binary_file, get_machine_id, get_user_uuid, platform_name, bytestostr, get_hex_uuid, SIGNAMES
from xpra.version_util import version_compat_check, get_version_info_full, get_platform_info, get_host_info
from xpra.net.protocol import Protocol, get_network_caps, sanity_checks
from xpra.net.crypto import crypto_backend_init, new_cipher_caps, get_salt, choose_digest, \
        ENCRYPTION_CIPHERS, ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS
from xpra.server.background_worker import stop_worker, get_worker
from xpra.make_thread import start_thread
from xpra.scripts.fdproxy import XpraProxy
from xpra.server.control_command import ControlError, HelloCommand, HelpCommand, DebugControl
from xpra.util import csv, merge_dicts, typedict, notypedict, flatten_dict, parse_simple_dict, repr_ellipsized, dump_all_frames, nonl, envint, envbool, \
        SERVER_SHUTDOWN, SERVER_UPGRADE, LOGIN_TIMEOUT, DONE, PROTOCOL_ERROR, SERVER_ERROR, VERSION_ERROR, CLIENT_REQUEST, SERVER_EXIT

main_thread = threading.current_thread()

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_MAX_CONCURRENT_CONNECTIONS", 100)
SIMULATE_SERVER_HELLO_ERROR = envbool("XPRA_SIMULATE_SERVER_HELLO_ERROR", False)
SERVER_SOCKET_TIMEOUT = float(os.environ.get("XPRA_SERVER_SOCKET_TIMEOUT", "0.1"))
LEGACY_SALT_DIGEST = envbool("XPRA_LEGACY_SALT_DIGEST", True)


def get_server_info():
    #this function is for non UI thread info
    info = {
            "platform"  : get_platform_info(),
            "build"     : get_version_info_full(),
            }
    info.update(get_host_info())
    return info

def get_thread_info(proto=None, protocols=[]):
    #threads:
    if proto:
        info_threads = proto.get_threads()
    else:
        info_threads = []
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

    it = info.setdefault("info", {})
    #threads used by the "info" client:
    for i, t in enumerate(info_threads):
        it[i] = t.getName()
        thread_ident[t.ident] = t.getName()
    for p in protocols:
        try:
            threads = p.get_threads()
            for t in threads:
                thread_ident[t.ident] = t.getName()
        except:
            pass
    #all non-info threads:
    anit = info.setdefault("thread", {})
    for i, t in enumerate((x for x in threading.enumerate() if x not in info_threads)):
        anit[i] = t.getName()
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
        frames = sys._current_frames()
        fi = info.setdefault("frame", {})
        for i,frame_pair in enumerate(frames.items()):
            stack = traceback.extract_stack(frame_pair[1])
            #sanitize stack to prevent None values (which cause encoding errors with the bencoder)
            sanestack = []
            for e in stack:
                sanestack.append(tuple([nn(x) for x in e]))
            fi[i] = {""         : thread_ident.get(frame_pair[0], "unknown"),
                     "stack"    : sanestack}
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
        self.ssl_auth_class = None
        self.vsock_auth_class = None
        self._when_ready = []
        self.child_reaper = None
        self.original_desktop_display = None

        self._closing = False
        self._upgrading = False
        #networking bits:
        self._socket_info = []
        self._potential_protocols = []
        self._tcp_proxy_clients = []
        self._tcp_proxy = ""
        self._ssl_wrap_socket = None
        self._accept_timeout = SOCKET_TIMEOUT + 1
        self.ssl_mode = None
        self._html = False
        self._www_dir = None
        self._aliases = {}
        self._reverse_aliases = {}
        self.socket_types = {}
        self._max_connections = MAX_CONCURRENT_CONNECTIONS
        self._socket_timeout = SERVER_SOCKET_TIMEOUT
        self._ws_timeout = 5
        self._socket_dir = None
        self.unix_socket_paths = []

        self.session_name = ""

        #Features:
        self.encryption = None
        self.encryption_keyfile = None
        self.tcp_encryption = None
        self.tcp_encryption_keyfile = None
        self.password_file = None
        self.compression_level = 1
        self.exit_with_client = False
        self.server_idle_timeout = 0
        self.server_idle_timer = None

        self.init_uuid()
        self.init_control_commands()
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
        set_name("Xpra", self.session_name or "Xpra")

        self.unix_socket_paths = []
        self._socket_dir = opts.socket_dir or opts.socket_dirs[0]
        self.encryption = opts.encryption
        self.encryption_keyfile = opts.encryption_keyfile
        self.tcp_encryption = opts.tcp_encryption
        self.tcp_encryption_keyfile = opts.tcp_encryption_keyfile
        if self.encryption or self.tcp_encryption:
            crypto_backend_init()
        self.password_file = opts.password_file
        self.compression_level = opts.compression_level
        self.exit_with_client = opts.exit_with_client
        self.server_idle_timeout = opts.server_idle_timeout
        self.readonly = opts.readonly
        self.ssl_mode = opts.ssl

        self.init_html_proxy(opts)
        self.init_auth(opts)


    def init_uuid(self):
        # Define a server UUID if needed:
        self.uuid = self.get_uuid()
        if not self.uuid:
            self.uuid = unicode(get_hex_uuid())
            self.save_uuid()
        log("server uuid is %s", self.uuid)

    def get_uuid(self):
        return  None

    def save_uuid(self):
        pass


    def init_html_proxy(self, opts):
        self._tcp_proxy = opts.tcp_proxy
        #opts.html can contain a boolean, "auto" or the path to the webroot
        www_dir = None
        if opts.html and os.path.isabs(opts.html):
            www_dir = opts.html
            self._html = True
        else:
            self._html = parse_bool("html", opts.html)
        if self._html is not False:     #True or None (for "auto")
            if not opts.bind_tcp:
                #we need a tcp socket!
                if self._html:
                    #html was enabled, so log an error:
                    log.error("Error: cannot use the html server without a bind-tcp socket")
                self._html = False
        if self._html is not False:
            try:
                from xpra.net.websocket import WebSocketConnection
                assert WebSocketConnection
                self._html = True
            except ImportError as e:
                if self._html is None:  #auto mode
                    log.info("html server unavailable, cannot find websockify module")
                else:
                    log.error("Error: cannot import websockify connection handler:")
                    log.error(" %s", e)
                    log.error(" the html server will not be available")
                self._html = False
        #make sure we have the web root:
        if self._html:
            from xpra.platform.paths import get_resources_dir
            self._www_dir = www_dir or os.path.abspath(os.path.join(get_resources_dir(), "www"))
            if not os.path.exists(self._www_dir):
                log.error("Error: cannot find the html web root")
                log.error(" '%s' does not exist", self._www_dir)
                self._html = False
        if self._html:
            log.info("serving html content from: %s", self._www_dir)
        if self._html and self._tcp_proxy:
            log.warn("Warning: the built in html server is enabled,")
            log.warn(" disabling the tcp-proxy option")
            self._tcp_proxy = False

    def init_auth(self, opts):
        self.auth_class = self.get_auth_module("unix-domain", opts.auth, opts)
        self.tcp_auth_class = self.get_auth_module("tcp", opts.tcp_auth or opts.auth, opts)
        self.ssl_auth_class = self.get_auth_module("ssl", opts.ssl_auth or opts.tcp_auth or opts.auth, opts)
        self.vsock_auth_class = self.get_auth_module("vsock", opts.vsock_auth, opts)
        authlog("init_auth(..) auth class=%s, tcp auth class=%s, ssl auth class=%s, vsock auth class=%s", self.auth_class, self.tcp_auth_class, self.ssl_auth_class, self.vsock_auth_class)

    def get_auth_module(self, socket_type, auth_str, opts):
        authlog("get_auth_module(%s, %s, {..})", socket_type, auth_str)
        if not auth_str:
            return None
        #separate options from the auth module name
        parts = auth_str.split(":", 1)
        auth = parts[0]
        auth_options = {}
        if len(parts)>1:
            auth_options = parse_simple_dict(parts[1])
        auth_options["exec_cwd"] = self.exec_cwd
        if auth=="sys":
            #resolve virtual "sys" auth:
            if sys.platform.startswith("win"):
                auth = "win32"
            else:
                auth = "pam"
            authlog("will try to use sys auth module '%s' for %s", auth, sys.platform)
        from xpra.server.auth import fail_auth, reject_auth, allow_auth, none_auth, file_auth, multifile_auth, password_auth, env_auth
        AUTH_MODULES = {
                        "fail"      : fail_auth,
                        "reject"    : reject_auth,
                        "allow"     : allow_auth,
                        "none"      : none_auth,
                        "env"       : env_auth,
                        "password"  : password_auth,
                        "multifile" : multifile_auth,
                        "file"      : file_auth,
                        }
        try:
            from xpra.server.auth import pam_auth
            AUTH_MODULES["pam"] = pam_auth
        except Exception as e:
            authlog("cannot load pam auth: %s", e)
        if sys.platform.startswith("win"):
            try:
                from xpra.server.auth import win32_auth
                AUTH_MODULES["win32"] = win32_auth
            except Exception as e:
                authlog.error("Error: cannot load the MS Windows authentication module:")
                authlog.error(" %s", e)
        auth_module = AUTH_MODULES.get(auth)
        if not auth_module:
            raise InitException("cannot find authentication module '%s' (supported: %s)" % (auth, csv(AUTH_MODULES.keys())))
        try:
            auth_module.init(opts)
            auth_class = getattr(auth_module, "Authenticator")
            auth_class.auth_name = auth.lower()
            return auth, auth_class, auth_options
        except Exception as e:
            raise InitException("Authenticator class not found in %s" % auth_module)


    def init_sockets(self, sockets):
        self._socket_info = sockets
        ### All right, we're ready to accept customers:
        for socktype, sock, info in sockets:
            netlog("init_sockets(%s) will add %s socket %s (%s)", sockets, socktype, sock, info)
            self.idle_add(self.add_listen_socket, socktype, sock)
            if socktype=="unix-domain" and info:
                try:
                    p = os.path.abspath(info)
                    self.unix_socket_paths.append(p)
                    netlog("added unix socket path: %s", p)
                except Exception as e:
                    log.error("failed to set socket path to %s: %s", info, e)

    def init_when_ready(self, callbacks):
        self._when_ready = callbacks


    def init_packet_handlers(self):
        netlog("initializing packet handlers")
        self._default_packet_handlers = {
            "hello":                                self._process_hello,
            "disconnect":                           self._process_disconnect,
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

    def init_control_commands(self):
        self.control_commands = {"hello"    : HelloCommand(),
                                 "debug"    : DebugControl()}
        help_command = HelpCommand(self.control_commands)
        self.control_commands["help"] = help_command


    def reaper_exit(self):
        self.clean_quit()

    def signal_quit(self, signum, frame):
        sys.stdout.write("\n")
        sys.stdout.flush()
        self._closing = True
        log.info("got signal %s, exiting", SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.idle_add(self.clean_quit)
        self.idle_add(sys.exit, 128+signum)

    def clean_quit(self, upgrading=False):
        log("clean_quit(%s)", upgrading)
        self._upgrading = upgrading
        self._closing = True
        #ensure the reaper doesn't call us again:
        if self.child_reaper:
            def noop():
                pass
            self.reaper_exit = noop
            log("clean_quit: reaper_exit=%s", self.reaper_exit)
        self.cleanup()
        def quit_timer(*args):
            log.debug("quit_timer()")
            stop_worker(True)
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
        dump_all_frames()

    def quit(self, upgrading=False):
        log("quit(%s)", upgrading)
        self._upgrading = upgrading
        self._closing = True
        log.info("xpra is terminating.")
        sys.stdout.flush()
        self.do_quit()
        log("quit(%s) do_quit done!", upgrading)
        dump_all_frames()

    def do_quit(self):
        raise NotImplementedError()

    def get_server_mode(self):
        return "core"

    def run(self):
        self.print_run_info()
        self.print_screen_info()
        #SIGINT breaks GTK3.. (but there are no py3k servers yet!)
        signal.signal(signal.SIGINT, self.signal_quit)
        signal.signal(signal.SIGTERM, self.signal_quit)
        def start_ready_callbacks():
            for x in self._when_ready:
                try:
                    x()
                except Exception as e:
                    log.error("error on %s: %s", x, e)
        self.idle_add(start_ready_callbacks)
        self.idle_add(self.reset_server_timeout)
        self.idle_add(self.server_is_ready)
        self.do_run()
        return self._upgrading

    def print_run_info(self):
        import struct
        bits = struct.calcsize("P") * 8
        log.info("xpra %s version %s %i-bit", self.get_server_mode(), full_version_str(), bits)
        try:
            pinfo = get_platform_info()
            osinfo = " on %s" % platform_name(sys.platform, pinfo.get("linux_distribution") or pinfo.get("sysrelease", ""))
        except:
            log("platform name error:", exc_info=True)
            osinfo = ""
        if os.name=="posix":
            uid = os.getuid()
            gid = os.getgid()
            try:
                import pwd, grp #@UnresolvedImport
                user = pwd.getpwuid(uid)[0]
                group = grp.getgrgid(gid)[0]
                log.info(" uid=%i (%s), gid=%i (%s)", uid, user, gid, group)
            except:
                log.info(" uid=%i, gid=%i", uid, gid)
        log.info(" running with pid %s%s", os.getpid(), osinfo)

    def print_screen_info(self):
        display = os.environ.get("DISPLAY")
        if display and display.startswith(":"):
            log.info(" connected to X11 display %s", display)


    def server_is_ready(self):
        log.info("xpra is ready.")
        sys.stdout.flush()

    def do_run(self):
        raise NotImplementedError()

    def cleanup(self, *args):
        netlog("cleanup() stopping %s tcp proxy clients: %s", len(self._tcp_proxy_clients), self._tcp_proxy_clients)
        for p in list(self._tcp_proxy_clients):
            p.quit()
        netlog("cleanup will disconnect: %s", self._potential_protocols)
        if self._upgrading:
            reason = SERVER_UPGRADE
        else:
            reason = SERVER_SHUTDOWN
        protocols = self.get_all_protocols()
        self.cleanup_protocols(protocols, reason)
        self.do_cleanup()
        self.cleanup_protocols(protocols, reason, True)
        self._potential_protocols = []

    def do_cleanup(self):
        #allow just a bit of time for the protocol packet flush
        time.sleep(0.1)


    def cleanup_all_protocols(self, reason):
        protocols = self.get_all_protocols()
        self.cleanup_protocols(protocols, reason)

    def get_all_protocols(self):
        return list(self._potential_protocols)

    def cleanup_protocols(self, protocols, reason, force=False):
        netlog("do_cleanup_all_protocols(%s, %s, %s)", protocols, reason, force)
        for protocol in protocols:
            if force:
                self.force_disconnect(protocol)
            else:
                self.disconnect_protocol(protocol, reason)


    def add_listen_socket(self, socktype, socket):
        raise NotImplementedError()

    def _new_connection(self, listener, *args):
        """
            Accept the new connection,
            verify that there aren't too many,
            start a thread to dispatch it to the correct handler.
        """
        if self._closing:
            netlog.warn("ignoring new connection during shutdown")
            return False
        socktype = self.socket_types.get(listener)
        assert socktype, "cannot find socket type for %s" % listener
        try:
            sock, address = listener.accept()
        except socket.error as e:
            netlog("rejecting new connection on %s", listener, exc_info=True)
            netlog.error("Error: cannot accept new connection:")
            netlog.error(" %s", e)
            return True
        try:
            peername = sock.getpeername()
        except:
            peername = str(address)
        sockname = sock.getsockname()
        target = peername or sockname
        sock.settimeout(self._socket_timeout)
        #limit number of concurrent network connections:
        if socktype not in ("unix-domain", "named-pipe") and len(self._potential_protocols)>=self._max_connections:
            netlog.error("Error: too many connections (%i)", len(self._potential_protocols))
            netlog.error(" ignoring new one: %s", target)
            sock.close()
            return True
        netlog("new_connection(%s) sock=%s, timeout=%s, sockname=%s, address=%s, peername=%s. timeout=%s", args, sock, self._socket_timeout, sockname, address, peername, self._socket_timeout)
        conn = SocketConnection(sock, sockname, address, target, socktype)

        #from here on, we run in a thread, so we can poll (peek does)
        start_thread(self.handle_new_connection, "new-%s-connection" % socktype, True, args=(conn, sock, socktype))
        return True

    def handle_new_connection(self, conn, sock, socktype):
        """
            Use peek to decide what sort of connection this is,
            and start the appropriate handler for it.
        """
        def conn_err(msg="invalid packet format, not an xpra client?"):
            #not an xpra client
            netlog.error("Error: %s connection failed:", socktype)
            netlog.error(" %s", msg)
            if conn.remote:
                netlog.error(" %s", pretty_socket(conn.remote))
            try:
                sock.settimeout(1)
                conn.write("disconnect: %s?\n" % msg)
                conn.close()
            except Exception as e:
                netlog("error sending '%s': %s", nonl(msg), e)
        #peek so we can detect invalid clients early,
        #or handle non-xpra traffic:
        PEEK_SIZE = 8192
        try:
            v = conn.peek(PEEK_SIZE)
        except:
            v = None
        if socktype=="tcp" and (self._html or self._tcp_proxy or self._ssl_wrap_socket):
            #see if the packet data is actually xpra or something else
            #that we need to handle via a tcp proxy, ssl wrapper or the websockify adapter:
            try:
                cont, conn, v = self.may_wrap_socket(conn, socktype, v)
                if not cont:
                    return
            except IOError as e:
                netlog("socket wrapping failed", exc_info=True)
                conn_err(str(e))
                return
        if v and v[0] not in ("P", ord("P")):
            msg = self.guess_header_protocol(v)
            conn_err("invalid packet header, %s" % msg)
            return True
        sock.settimeout(self._socket_timeout)
        inject_ssl_socket_info(conn)
        log_new_connection(conn)
        self.make_protocol(socktype, conn)


    def make_protocol(self, socktype, conn, frominfo=""):
        protocol = Protocol(self, conn, self.process_packet)
        self._potential_protocols.append(protocol)
        protocol.large_packets.append("info-response")
        protocol.challenge_sent = False
        protocol.authenticator = None
        protocol.encryption = None
        protocol.keyfile = None
        if socktype=="tcp":
            protocol.auth_class = self.tcp_auth_class
            protocol.encryption = self.tcp_encryption
            protocol.keyfile = self.tcp_encryption_keyfile
        elif socktype=="SSL":
            protocol.auth_class = self.ssl_auth_class
        elif socktype=="vsock":
            protocol.auth_class = self.vsock_auth_class
        else:
            protocol.auth_class = self.auth_class
            protocol.encryption = self.encryption
            protocol.keyfile = self.encryption_keyfile
        protocol.socket_type = socktype
        protocol.invalid_header = self.invalid_header
        protocol.receive_aliases.update(self._aliases)
        authlog("socktype=%s, auth class=%s, encryption=%s, keyfile=%s", socktype, protocol.auth_class, protocol.encryption, protocol.keyfile)
        if protocol.encryption and ENCRYPT_FIRST_PACKET:
            password = self.get_encryption_key(None, protocol.keyfile)
            protocol.set_cipher_in(protocol.encryption, DEFAULT_IV, password, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING)
        protocol.start()
        self.timeout_add(self._accept_timeout*1000, self.verify_connection_accepted, protocol)

    def may_wrap_socket(self, conn, socktype, peek_data=""):
        """
            Returns:
            * a flag indicating if we should continue processing this connection
            *  (False for websockify and tcp proxies as they take over the socket)
            * the connection object (which may now be wrapped, ie: for ssl)
            * new peek data (which may now be empty),
        """
        if not peek_data:
            netlog("may_wrap_socket: no data, not wrapping")
            return True, conn, peek_data
        if peek_data[0] in ("P", ord("P")):
            netlog("may_wrap_socket: xpra protocol header '%s', not wrapping", peek_data[0])
            #xpra packet header, no need to wrap this connection
            return True, conn, peek_data
        frominfo = pretty_socket(conn.remote)
        #the peek data we will return:
        v = peek_data
        if self._ssl_wrap_socket and v[0] in (chr(0x16), 0x16):
            socktype = "SSL"
            sock, sockname, address, target = conn._socket, conn.local, conn.remote, conn.target
            sock = self._ssl_wrap_socket(sock)
            if sock is None:
                #None means EOF! (we don't want to import ssl bits here)
                netlog("ignoring SSL EOF error")
                return False, None, None
            conn = SocketConnection(sock, sockname, address, target, socktype)
            #we cannot peek on SSL sockets, just clear the unencrypted data:
            netlog("may_wrap_socket SSL: %s", conn)
            v = None
        is_ssl = socktype=="SSL"
        if self._html and self.ssl_mode!="tcp":
            line1 = peek_data.splitlines()[0]
            if line1.find("HTTP/")>0 or (is_ssl and (self.ssl_mode=="www" or (self.ssl_mode=="auto" and peek_data.find("\x08http/1.1")>0))):
                http_proto = "http"+["","s"][int(is_ssl)]
                if line1.startswith("GET ") or line1.startswith("POST "):
                    parts = line1.split(" ")
                    httplog("New %s %s request received from %s for '%s'", http_proto, parts[0], frominfo, parts[1])
                    tname = "%s-request" % parts[0]
                    req_info = "%s %s" % (http_proto, parts[0])
                else:
                    httplog("New %s connection received from %s", http_proto, frominfo)
                    req_info = "ws"+["","s"][int(is_ssl)]
                    tname = "%s-proxy" % req_info
                start_thread(self.start_websockify, "%s-for-%s" % (tname, frominfo), daemon=True, args=(conn, req_info, conn.remote))
                return False, conn, None
        if self._tcp_proxy:
            netlog.info("New tcp proxy connection received from %s", frominfo)
            t = start_thread(self.start_tcp_proxy, "tcp-proxy-for-%s" % frominfo, daemon=True, args=(conn, conn.remote))
            netlog("may_wrap_socket handling via tcp proxy thread %s", t)
            return False, conn, None
        return True, conn, v

    def invalid_header(self, proto, data, msg):
        netlog("invalid_header(%s, %s bytes: '%s', %s) input_packetcount=%s, tcp_proxy=%s, html=%s, ssl=%s", proto, len(data or ""), msg, repr_ellipsized(data), proto.input_packetcount, self._tcp_proxy, self._html, bool(self._ssl_wrap_socket))
        err = "invalid packet format, %s" % self.guess_header_protocol(data)
        proto.gibberish(err, data)

    def guess_header_protocol(self, v):
        try:
            c = ord(v[0])
        except:
            c = int(v[0])
        if c==0x16:
            return "SSL packet?"
        elif len(v)>=3 and v.split(" ")[0] in ("GET", "POST"):
            return "HTTP %s request" % v.split(" ")[0]
        return "character %#x, not an xpra client?" % c


    def start_websockify(self, conn, req_info, frominfo):
        wslog("start_websockify(%s, %s, %s) www dir=%s", conn, req_info, frominfo, self._www_dir)
        from xpra.net.websocket import WebSocketConnection, WSRequestHandler
        try:
            sock = conn._socket
            sock.settimeout(self._ws_timeout)
            def new_websocket_client(wsh):
                wslog("new_websocket_client(%s) socket=%s", wsh, sock)
                wsc = WebSocketConnection(sock, conn.local, conn.remote, conn.target, conn.socktype, wsh)
                # we need this workaround for non-blocking sockets
                from xpra.net.bytestreams import untilConcludes
                saved_recv = sock.recv
                saved_send = sock.send
                #now we can have a "is_active" that belongs to the real connection object:
                def recv(*args):
                    return untilConcludes(wsc.is_active, saved_recv, *args)
                def send(*args):
                    return untilConcludes(wsc.is_active, saved_send, *args)
                sock.recv = recv
                sock.send = send
                self.make_protocol("tcp", wsc, frominfo)
            WSRequestHandler(sock, frominfo, new_websocket_client, self._www_dir)
            return
        except IOError as e:
            wslog("", exc_info=True)
            wslog.error("Error: %s request failure for client %s:", req_info, pretty_socket(frominfo))
            wslog.error(" %s", e)
        except Exception as e:
            wslog("", exc_info=True)
            wslog.error("Error: %s request failure for client %s:", req_info, pretty_socket(frominfo), exc_info=True)
        try:
            conn.close()
        except Exception as ce:
            wslog("error closing connection following error: %s", ce)

    def start_tcp_proxy(self, conn, frominfo):
        proxylog("start_tcp_proxy(%s, %s)", conn, frominfo)
        #connect to web server:
        host, port = self._tcp_proxy.split(":", 1)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            host, port = self._tcp_proxy.split(":", 1)
            tcp_server_connection = _socket_connect(sock, (host, int(port)), "web-proxy-for-%s" % frominfo, "tcp")
        except:
            proxylog.warn("failed to connect to proxy: %s:%s", host, port)
            conn.close()
            return
        proxylog("proxy connected to tcp server at %s:%s : %s", host, port, tcp_server_connection)
        sock = tcp_server_connection._socket
        sock.settimeout(self._socket_timeout)

        #we can use blocking sockets for the client:
        conn.settimeout(None)
        #but not for the server, which could deadlock on exit:
        sock.settimeout(1)

        #now start forwarding:
        p = XpraProxy(frominfo, conn, tcp_server_connection, self.tcp_proxy_quit)
        self._tcp_proxy_clients.append(p)
        proxylog.info("client connection from %s forwarded to proxy server on %s:%s", frominfo, host, port)
        p.start_threads()


    def tcp_proxy_quit(self, proxy):
        proxylog("tcp_proxy_quit(%s)", proxy)
        if proxy in self._tcp_proxy_clients:
            self._tcp_proxy_clients.remove(proxy)

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
            proto_info = " %s" % protocol._conn.get_info().get("endpoint")
        except:
            proto_info = " %s" % protocol
        self._log_disconnect(protocol, "Disconnecting client%s:", proto_info)
        self._log_disconnect(protocol, " %s", i)
        protocol.flush_then_close(["disconnect", reason]+list(extra))


    def _process_disconnect(self, proto, packet):
        info = packet[1]
        if len(packet)>2:
            info += " (%s)" % (", ".join(packet[2:]))
        #only log protocol info if there is more than one client:
        proto_info = self._disconnect_proto_info(proto)
        self._log_disconnect(proto, "client%s has requested disconnection: %s", proto_info, info)
        self.disconnect_protocol(proto, CLIENT_REQUEST)

    def _log_disconnect(self, proto, *args):
        netlog.info(*args)

    def _disconnect_proto_info(self, proto):
        #overriden in server_base in case there is more than one protocol
        return ""

    def _process_connection_lost(self, proto, packet):
        netlog("process_connection_lost(%s, %s)", proto, packet)
        if proto in self._potential_protocols:
            if not proto._closed:
                self._log_disconnect(proto, "Connection lost")
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
            command_req = c.strlistget("command_request")
            if len(command_req)>0:
                #call from UI thread:
                self.idle_add(self.handle_command_request, proto, *command_req)
                return
            #continue processing hello packet:
            try:
                if SIMULATE_SERVER_HELLO_ERROR:
                    raise Exception("Simulating a server error")
                self.hello_oked(proto, packet, c, auth_caps)
            except ClientException as e:
                log.error("Error setting up new connection for")
                log.error(" %s:", proto)
                log.error(" %s", e)
                self.disconnect_client(proto, SERVER_ERROR, str(e))
            except Exception as e:
                #log exception but don't disclose internal details to the client
                log.error("server error processing new connection from %s: %s", proto, e, exc_info=True)
                self.disconnect_client(proto, SERVER_ERROR, "error accepting new connection")


    def verify_hello(self, proto, c):
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, VERSION_ERROR, "incompatible version: %s" % verr)
            proto.close()
            return  False

        def auth_failed(msg):
            authlog.error("Error: authentication failed")
            authlog.error(" %s", msg)
            self.timeout_add(1000, self.disconnect_client, proto, msg)

        #authenticator:
        username = c.strget("username")
        if proto.authenticator is None and proto.auth_class:
            authlog("creating authenticator %s with username=%s", proto.auth_class, username)
            try:
                auth, aclass, options = proto.auth_class
                ainstance = aclass(username, **options)
                proto.authenticator = ainstance
                authlog("%s=%s", auth, ainstance)
            except Exception as e:
                authlog.error("Error instantiating %s:", proto.auth_class)
                authlog.error(" %s", e)
                auth_failed("authentication failed")
                return False

        digest_modes = c.strlistget("digest", ("hmac", ))
        salt_digest_modes = c.strlistget("salt-digest", ("xor",))
        #client may have requested encryption:
        cipher = c.strget("cipher")
        cipher_iv = c.strget("cipher.iv")
        key_salt = c.strget("cipher.key_salt")
        iterations = c.intget("cipher.key_stretch_iterations")
        padding = c.strget("cipher.padding", DEFAULT_PADDING)
        padding_options = c.strlistget("cipher.padding.options", [DEFAULT_PADDING])
        auth_caps = {}
        if cipher and cipher_iv:
            if cipher not in ENCRYPTION_CIPHERS:
                authlog.warn("unsupported cipher: %s", cipher)
                auth_failed("unsupported cipher")
                return False
            encryption_key = self.get_encryption_key(proto.authenticator, proto.keyfile)
            if encryption_key is None:
                auth_failed("encryption key is missing")
                return False
            if padding not in ALL_PADDING_OPTIONS:
                auth_failed("unsupported padding: %s" % padding)
                return False
            authlog("set output cipher using encryption key '%s'", repr_ellipsized(encryption_key))
            proto.set_cipher_out(cipher, cipher_iv, encryption_key, key_salt, iterations, padding)
            #use the same cipher as used by the client:
            auth_caps = new_cipher_caps(proto, cipher, encryption_key, padding_options)
            authlog("server cipher=%s", auth_caps)
        else:
            if proto.encryption:
                authlog("client does not provide encryption tokens")
                auth_failed("missing encryption tokens")
                return False
            auth_caps = None

        #verify authentication if required:
        if (proto.authenticator and proto.authenticator.requires_challenge()) or c.get("challenge") is not None:
            challenge_response = c.strget("challenge_response")
            client_salt = c.strget("challenge_client_salt")
            authlog("processing authentication with %s, response=%s, client_salt=%s, challenge_sent=%s, digest_modes=%s, salt_digest_modes=%s", proto.authenticator, challenge_response, binascii.hexlify(client_salt or ""), proto.challenge_sent, digest_modes, salt_digest_modes)
            #send challenge if this is not a response:
            if not challenge_response:
                if proto.challenge_sent:
                    auth_failed("invalid state, challenge already sent - no response!")
                    return False
                if proto.authenticator:
                    challenge = proto.authenticator.get_challenge()
                    if challenge is None:
                        if proto.authenticator.requires_challenge():
                            auth_failed("invalid state, unexpected challenge response")
                            return False
                        authlog.warn("Warning: authentication module '%s' does not require any credentials", proto.authenticator)
                        authlog.warn(" but the client %s supplied them", proto)
                        salt, digest = get_salt(), "hmac"
                    else:
                        authlog("challenge: %s", challenge)
                        salt, digest = challenge
                        authlog.info("Authentication required by %s authenticator module", proto.authenticator)
                        authlog.info(" sending challenge for username '%s' using %s digest", username, digest)
                    if digest not in digest_modes:
                        auth_failed("cannot proceed without %s digest support" % digest)
                        return False
                    salt_digest = proto.authenticator.choose_salt_digest(salt_digest_modes)
                    if salt_digest=="xor":
                        if not LEGACY_SALT_DIGEST:
                            auth_failed("insecure salt digest '%s' rejected" % salt_digest)
                            return False
                        log.warn("Warning: using legacy support for '%s' salt digest", salt_digest)
                else:
                    authlog.warn("Warning: client expects a challenge but this connection is unauthenticated")
                    #fake challenge so the client will send the real hello:
                    salt = get_salt()
                    digest = choose_digest(digest_modes)
                    salt_digest = choose_digest(salt_digest_modes)
                proto.challenge_sent = True
                proto.send_now(("challenge", salt, auth_caps or "", digest, salt_digest))
                return False

            if not proto.authenticator.authenticate(challenge_response, client_salt):
                auth_failed("invalid challenge response")
                return False
            authlog("authentication challenge passed")
        else:
            #did the client expect a challenge?
            if c.boolget("challenge"):
                authlog.warn("this server does not require authentication (client supplied a challenge)")
        return auth_caps

    def filedata_nocrlf(self, filename):
        v = load_binary_file(filename)
        if v is None:
            log.error("failed to load '%s'", filename)
            return None
        return v.strip("\n\r")

    def get_encryption_key(self, authenticator=None, keyfile=None):
        #if we have a keyfile specified, use that:
        authlog("get_encryption_key(%s, %s)", authenticator, keyfile)
        v = None
        if keyfile:
            authlog("loading encryption key from keyfile: %s", keyfile)
            v = self.filedata_nocrlf(keyfile)
        if not v:
            v = os.environ.get('XPRA_ENCRYPTION_KEY')
            if v:
                authlog("using encryption key from %s environment variable", 'XPRA_ENCRYPTION_KEY')
        if not v and authenticator:
            v = authenticator.get_password()
        return v

    def hello_oked(self, proto, packet, c, auth_caps):
        ctr = c.strget("connect_test_request")
        if ctr:
            response = {"connect_test_response" : ctr}
            proto.send_now(("hello", response))
            return
        if c.boolget("info_request", False):
            flatten = not c.boolget("info-namespace", False)
            self.send_hello_info(proto, flatten)
            return True
        if self._closing:
            self.disconnect_client(proto, SERVER_EXIT, "server is shutting down")
            return True
        return False


    def handle_command_request(self, proto, *args):
        """ client sent a command request as part of the hello packet """
        assert len(args)>0
        code, response = self.process_control_command(*args)
        hello = {"command_response"  : (code, response)}
        proto.send_now(("hello", hello))

    def process_control_command(self, *args):
        assert len(args)>0
        name = args[0]
        try:
            command = self.control_commands.get(name)
            commandlog("process_control_command control_commands[%s]=%s", name, command)
            if not command:
                commandlog.warn("invalid command: '%s' (must be one of: %s)", name, ", ".join(self.control_commands))
                return 6, "invalid command"
            commandlog("process_control_command calling %s%s", command.run, args[1:])
            v = command.run(*args[1:])
            return 0, v
        except ControlError as e:
            commandlog.error("error %s processing control command '%s'", e.code, name)
            msgs = [" %s" % e]
            if e.help:
                msgs.append(" '%s': %s" % (name, e.help))
            for msg in msgs:
                commandlog.error(msg)
            return e.code, "\n".join(msgs)
        except Exception as e:
            commandlog.error("error processing control command '%s'", name, exc_info=True)
            return 127, "error processing control command: %s" % e


    def accept_client(self, proto, c):
        #max packet size from client (the biggest we can get are clipboard packets)
        netlog("accept_client(%s, %s)", proto, c)
        #TODO: when we add the code to upload files,
        #this will need to be increased up to file-size-limit
        proto.max_packet_size = 1024*1024  #1MB
        proto.send_aliases = c.dictget("aliases")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        self.reset_server_timeout(False)

    def reset_server_timeout(self, reschedule=True):
        timeoutlog("reset_server_timeout(%s) server_idle_timeout=%s, server_idle_timer=%s", reschedule, self.server_idle_timeout, self.server_idle_timer)
        if self.server_idle_timeout<=0:
            return
        if self.server_idle_timer:
            self.source_remove(self.server_idle_timer)
            self.server_idle_timer = None
        if reschedule:
            self.server_idle_timer = self.timeout_add(self.server_idle_timeout*1000, self.server_idle_timedout)

    def server_idle_timedout(self, *args):
        timeoutlog.info("No valid client connections for %s seconds, exiting the server", self.server_idle_timeout)
        self.clean_quit(False)


    def make_hello(self, source=None):
        now = time.time()
        capabilities = flatten_dict(get_network_caps())
        if source is None or source.wants_versions:
            capabilities.update(flatten_dict(get_server_info()))
        capabilities.update({
                        "version"               : xpra.__version__,
                        "start_time"            : int(self.start_time),
                        "current_time"          : int(now),
                        "elapsed_time"          : int(now - self.start_time),
                        "server_type"           : "core",
                        "server.mode"           : self.get_server_mode(),
                        })
        if source is None or source.wants_features:
            capabilities["info-request"] = True
            capabilities["readonly-server"] = True
            if self.readonly:
                capabilities["readonly"] = True
        if source is None or source.wants_versions:
            capabilities["uuid"] = get_user_uuid()
            mid = get_machine_id()
            if mid:
                capabilities["machine_id"] = mid
        if self.session_name:
            capabilities["session_name"] = self.session_name
        return capabilities


    def send_hello_info(self, proto, flatten=True):
        #Note: this can be overriden in subclasses to pass arguments to get_ui_info()
        #(ie: see server_base)
        log.info("processing info request from %s", proto._conn)
        def cb(proto, info):
            self.do_send_info(proto, info, flatten)
        self.get_all_info(cb, proto)

    def do_send_info(self, proto, info, flatten):
        if flatten:
            info = flatten_dict(info)
        else:
            info = notypedict(info)
        proto.send_now(("hello", info))

    def get_all_info(self, callback, proto=None, *args):
        start = time.time()
        ui_info = self.get_ui_info(proto, *args)
        end = time.time()
        log("get_all_info: ui info collected in %ims", (end-start)*1000)
        def in_thread(*args):
            start = time.time()
            #this runs in a non-UI thread
            try:
                info = self.get_info(proto, *args)
                merge_dicts(ui_info, info)
            except Exception as e:
                log.error("error during info collection: %s", e, exc_info=True)
            end = time.time()
            log("get_all_info: non ui info collected in %ims", (end-start)*1000)
            callback(proto, ui_info)
        start_thread(in_thread, "Info", daemon=True)

    def get_ui_info(self, proto, *args):
        #this function is for info which MUST be collected from the UI thread
        return {}

    def get_thread_info(self, proto):
        return get_thread_info(proto)

    def get_info(self, proto, *args):
        start = time.time()
        #this function is for non UI thread info
        info = {}
        def up(prefix, d):
            info[prefix] = d
        filtered_env = os.environ.copy()
        if filtered_env.get('XPRA_PASSWORD'):
            filtered_env['XPRA_PASSWORD'] = "*****"
        if filtered_env.get('XPRA_ENCRYPTION_KEY'):
            filtered_env['XPRA_ENCRYPTION_KEY'] = "*****"

        si = get_server_info()
        si.update({
                   "mode"              : self.get_server_mode(),
                   "type"              : "Python",
                   "python"            : {"version" : python_platform.python_version()},
                   "start_time"        : int(self.start_time),
                   "idle-timeout"      : int(self.server_idle_timeout),
                   "argv"              : sys.argv,
                   "path"              : sys.path,
                   "exec_prefix"       : sys.exec_prefix,
                   "executable"        : sys.executable,
                   "uuid"              : self.uuid,
                })
        if self.original_desktop_display:
            si["original-desktop-display"] = self.original_desktop_display
        up("server", si)
        from xpra.net.net_util import get_info as get_net_info
        ni = get_net_info()
        ni.update({
                   "sockets"        : self.get_socket_info(),
                   "encryption"     : self.encryption or "",
                   "tcp-encryption" : self.tcp_encryption or "",
                   })
        up("network", ni)
        up("threads",   self.get_thread_info(proto))
        up("env",       filtered_env)
        if self.session_name:
            info["session"] = {"name" : self.session_name}
        if self.child_reaper:
            info.update(self.child_reaper.get_info())
        end = time.time()
        log("ServerCore.get_info took %ims", (end-start)*1000)
        return info

    def get_socket_info(self):
        si = {}
        for socktype, _, info in self._socket_info:
            if info:
                si.setdefault(socktype, {}).setdefault("listeners", []).append(info)
        for socktype, auth_class in {
                                     "tcp"          : self.tcp_auth_class,
                                     "ssl"          : self.ssl_auth_class,
                                     "unix-domain"  : self.auth_class,
                                     "vsock"        : self.vsock_auth_class,
                                     }.items():
            if auth_class:
                si.setdefault(socktype, {})["authenticator"] = auth_class[0], auth_class[2]
        return si


    def process_packet(self, proto, packet):
        packet_type = None
        handler = None
        try:
            packet_type = bytestostr(packet[0])
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                netlog("process packet %s", packet_type)
                handler(proto, packet)
                return
            if not self._closing:
                netlog("invalid packet: %s", packet)
                netlog.error("unknown or invalid packet type: '%s' from %s", packet_type, proto)
            proto.close()
        except KeyboardInterrupt:
            raise
        except:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
