# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import types
import os
import sys
import time
import socket
import signal
import threading
import thread

from xpra.log import Logger
log = Logger()

import xpra
from xpra.scripts.config import ENCRYPTION_CIPHERS
from xpra.scripts.server import deadly_signal
from xpra.net.bytestreams import SocketConnection
from xpra.os_util import set_application_name, load_binary_file, SIGNAMES
from xpra.version_util import version_compat_check, add_version_info, get_platform_info
from xpra.net.protocol import Protocol, use_lz4, use_rencode, new_cipher_caps, get_network_caps
from xpra.util import typedict


MAX_CONCURRENT_CONNECTIONS = 20


def get_server_info(prefix=""):
    #this function is for non UI thread info
    info = {
            prefix+"pid"                : os.getpid(),
            prefix+"byteorder"          : sys.byteorder,
            prefix+"hostname"           : socket.gethostname(),
            prefix+"python.full_version": sys.version,
            prefix+"python.version"     : sys.version_info[:3],
            }
    for x in ("uid", "gid"):
        if hasattr(os, "get%s" % x):
            try:
                info[prefix+x] = getattr(os, "get%s" % x)()
            except:
                pass
    info.update(get_platform_info(prefix))
    add_version_info(info, prefix)
    return info

def get_thread_info(prefix="", proto=None):
    #threads:
    info = {}
    info_threads = proto.get_threads()
    info[prefix+"threads"] = threading.active_count() - len(info_threads)
    info[prefix+"info_threads"] = len(info_threads)
    i = 0
    #threads used by the "info" client:
    for t in info_threads:
        info[prefix+"info_thread[%s]" % i] = t.name
        i += 1
    i = 0
    #all non-info threads:
    for t in threading.enumerate():
        if t not in info_threads:
            info[prefix+"thread[%s]" % i] = t.name
            i += 1
    #platform specific bits:
    try:
        from xpra.platform.info import get_sys_info
        for k,v in get_sys_info().items():
            info[prefix+k] = v
    except:
        log.error("error getting system info", exc_info=True)
    return info


class ServerCore(object):
    """
        This is the simplest base class for servers.
        It only handles establishing the connection.
    """

    def __init__(self):
        log("ServerCore.__init__()")
        self.start_time = time.time()
        self.auth_class = None
        self._when_ready = []

        self._upgrading = False
        #networking bits:
        self._potential_protocols = []
        self._aliases = {}
        self._reverse_aliases = {}
        self.socket_types = {}
        self._max_connections = MAX_CONCURRENT_CONNECTIONS

        self.session_name = "Xpra"

        #Features:
        self.digest_modes = ("hmac", )
        self.encryption_keyfile = None
        self.password_file = None
        self.compression_level = 1

        self.init_packet_handlers()
        self.init_aliases()

    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()

    def init(self, opts):
        log("ServerCore.init(%s)", opts)
        self.session_name = opts.session_name
        set_application_name(self.session_name)

        self.encryption_keyfile = opts.encryption_keyfile
        self.password_file = opts.password_file
        self.compression_level = opts.compression_level

        self.init_auth(opts)

    def init_auth(self, opts):
        auth = opts.auth
        if not auth and opts.password_file:
            log.warn("no authentication module specified with 'password_file', using 'file' based authentication")
            auth = "file"
        if auth=="":
            return
        elif auth=="sys":
            if sys.platform.startswith("win"):
                auth = "win32"
            else:
                auth = "pam"
            log("will try to use sys auth module '%s' for %s", auth, sys.platform)
        if auth=="fail":
            from xpra.server.auth import fail_auth
            auth_module = fail_auth
        elif auth=="allow":
            from xpra.server.auth import allow_auth
            auth_module = allow_auth
        elif auth=="file":
            from xpra.server.auth import file_auth
            auth_module = file_auth
        elif auth=="pam":
            from xpra.server.auth import pam_auth
            auth_module = pam_auth
        elif auth=="win32":
            from xpra.server.auth import win32_auth
            auth_module = win32_auth
        else:
            raise Exception("invalid auth module: %s" % auth)
        try:
            auth_module.init(opts)
        except Exception, e:
            raise Exception("failed to initialize %s module: %s" % (auth_module, e))
        try:
            self.auth_class = getattr(auth_module, "Authenticator")
        except Exception, e:
            raise Exception("Authenticator class not found in %s" % auth_module)

    def init_sockets(self, sockets):
        ### All right, we're ready to accept customers:
        for socktype, sock in sockets:
            self.idle_add(self.add_listen_socket, socktype, sock)

    def init_when_ready(self, callbacks):
        self._when_ready = callbacks


    def init_packet_handlers(self):
        log("initializing packet handlers")
        self._default_packet_handlers = {
            "hello":                                self._process_hello,
            "info-request":                         self._process_info_request,
            Protocol.CONNECTION_LOST:               self._process_connection_lost,
            Protocol.GIBBERISH:                     self._process_gibberish,
            }

    def init_aliases(self):
        self.do_init_aliases(self._default_packet_handlers.keys())

    def do_init_aliases(self, packet_types):
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1

    def signal_quit(self, signum, frame):
        log.info("")
        log.info("got signal %s, exiting", SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.clean_quit()

    def clean_quit(self):
        self.cleanup()
        def quit_timer(*args):
            log.debug("quit_timer()")
            self.quit(False)
        self.timeout_add(500, quit_timer)
        def force_quit(*args):
            log.debug("force_quit()")
            os._exit(1)
        self.timeout_add(5000, force_quit)

    def quit(self, upgrading):
        log("quit(%s)", upgrading)
        self._upgrading = upgrading
        log.info("xpra is terminating.")
        sys.stdout.flush()
        self.do_quit()

    def do_quit(self):
        raise NotImplementedError()

    def get_server_mode(self):
        return "server"

    def run(self):
        log.info("xpra %s version %s", self.get_server_mode(), xpra.__version__)
        log.info("running with pid %s", os.getpid())
        signal.signal(signal.SIGTERM, self.signal_quit)
        signal.signal(signal.SIGINT, self.signal_quit)
        def start_ready_callbacks():
            for x in self._when_ready:
                try:
                    x()
                except Exception, e:
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
        log("cleanup will disconnect: %s", self._potential_protocols)
        for proto in self._potential_protocols:
            if self._upgrading:
                reason = "upgrading"
            else:
                reason = "shutting down"
            self.disconnect_client(proto, reason)
        self._potential_protocols = []

    def add_listen_socket(self, socktype, socket):
        raise NotImplementedError()

    def _new_connection(self, listener, *args):
        socktype = self.socket_types.get(listener, "")
        sock, address = listener.accept()
        if len(self._potential_protocols)>=self._max_connections:
            log.error("too many connections (%s), ignoring new one", len(self._potential_protocols))
            sock.close()
            return  True
        try:
            peername = sock.getpeername()
        except:
            peername = str(address)
        sockname = sock.getsockname()
        target = peername or sockname
        log("new_connection(%s) sock=%s, sockname=%s, address=%s, peername=%s", args, sock, sockname, address, peername)
        sc = SocketConnection(sock, sockname, address, target, socktype)
        log.info("New connection received: %s", sc)
        protocol = Protocol(self, sc, self.process_packet)
        protocol.large_packets.append("info-response")
        protocol.authenticator = None
        self._potential_protocols.append(protocol)
        protocol.start()
        self.timeout_add(10*1000, self.verify_connection_accepted, protocol)
        return True

    def verify_connection_accepted(self, protocol):
        raise NotImplementedError()

    def send_disconnect(self, proto, reason):
        log("send_disconnect(%s, %s)", proto, reason)
        if proto._closed:
            return
        proto.send_now(["disconnect", reason])
        self.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto):
        proto.close()

    def disconnect_client(self, protocol, reason):
        if protocol:
            self.disconnect_protocol(protocol, reason)
        log.info("Connection lost")

    def disconnect_protocol(self, protocol, reason):
        log.info("Disconnecting existing client %s, reason is: %s", protocol, reason)
        protocol.flush_then_close(["disconnect", reason])


    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)

    def _process_gibberish(self, proto, packet):
        data = packet[1]
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.disconnect_client(proto, "invalid packet format, not an xpra client?")


    def send_version_info(self, proto):
        response = {"version" : xpra.__version__}
        proto.send_now(("hello", response))
        self.timeout_add(5*1000, self.send_disconnect, proto, "version sent")

    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        c = typedict(capabilities)

        proto.chunked_compression = c.boolget("chunked_compression")
        if proto.chunked_compression:
            proto.set_compression_level(c.intget("compression_level", self.compression_level))
        if use_rencode and c.boolget("rencode"):
            proto.enable_rencode()
        else:
            proto.enable_bencode()

        if c.boolget("lz4") and use_lz4 and proto.chunked_compression and self.compression_level==1:
            proto.enable_lz4()

        log("process_hello: capabilities=%s", capabilities)
        if c.boolget("version_request"):
            self.send_version_info(proto)
            return False

        auth_caps = self.verify_hello(proto, c)
        if auth_caps is not False:
            if c.boolget("info_request", False):
                log.info("processing info request from %s", proto._conn)
                self.send_hello_info(proto)
                return
            #continue processing hello packet:
            try:
                self.hello_oked(proto, packet, c, auth_caps)
            except:
                log.error("server error processing new connection from %s", proto, exc_info=True)
                self.disconnect_client(proto, "server error accepting new connection")


    def verify_hello(self, proto, c):
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, "incompatible version: %s" % verr)
            proto.close()
            return  False

        def auth_failed(msg):
            log.info("authentication failed: %s", msg)
            self.timeout_add(1000, self.disconnect_client, proto, msg)

        #authenticator:
        username = c.strget("username")
        if proto.authenticator is None and self.auth_class:
            try:
                proto.authenticator = self.auth_class(username)
            except Exception, e:
                log.warn("error instantiating %s: %s", self.auth_class, e)
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
        if proto.authenticator:
            challenge_response = c.strget("challenge_response")
            client_salt = c.strget("challenge_client_salt")
            log("processing authentication with %s, response=%s, client_salt=%s", proto.authenticator, challenge_response, client_salt)
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
                self.disconnect_client(proto, "this server does not require authentication")
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
            log("trying to load encryption key from keyfile: %s", self.encryption_keyfile)
            return self.filedata_nocrlf(self.encryption_keyfile)
        v = None
        if authenticator:
            log("trying to get encryption key from: %s", authenticator)
            v = authenticator.get_password()
        if v is None and self.password_file:
            log("trying to load encryption key from password file: %s", self.password_file)
            v = self.filedata_nocrlf(self.password_file)
        return v

    def hello_oked(self, proto, packet, c, auth_caps):
        pass


    def accept_client(self, proto, c):
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.aliases = c.dictget("aliases")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)

    def make_hello(self):
        now = time.time()
        capabilities = get_network_caps()
        capabilities.update(get_server_info())
        capabilities.update({
                        "start_time"            : int(self.start_time),
                        "current_time"          : int(now),
                        "elapsed_time"          : int(now - self.start_time),
                        "server_type"           : "core",
                        "info-request"          : True,
                        })
        if self.session_name:
            capabilities["session_name"] = self.session_name
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        add_version_info(capabilities)
        return capabilities


    def send_hello_info(self, proto):
        #Note: this can be overriden in subclasses to pass arguments to get_ui_info()
        #(ie: see server_base)
        self.get_all_info(self.do_send_info, proto)

    def do_send_info(self, proto, info):
        proto.send_now(("hello", info))

    def _process_info_request(self, proto, packet):
        ss = self._server_sources.get(proto)
        assert ss, "cannot find server source for %s" % proto
        def info_callback(_proto, info):
            assert proto==_proto
            ss.send_info_response(info)
        self.get_all_info(info_callback, proto, *packet[1:])

    def get_all_info(self, callback, proto, *args):
        ui_info = self.get_ui_info(proto, *args)
        def in_thread(*args):
            #this runs in a non-UI thread
            try:
                info = self.get_info(proto, *args)
                ui_info.update(info)
            except Exception, e:
                log.error("error during info collection: %s", e, exc_info=True)
            callback(proto, ui_info)
        thread.start_new_thread(in_thread, ())

    def get_ui_info(self, proto, *args):
        #this function is for info which MUST be collected from the UI thread
        return {}

    def get_info(self, proto, *args):
        #this function is for non UI thread info
        info = get_server_info("server.")
        info.update({
                "server.mode"               : self.get_server_mode(),
                "server.type"               : "Python",
                "server.start_time"         : int(self.start_time),
                "session.name"              : self.session_name or "",
                "features.authenticator"    : str((self.auth_class or str)("")),
                })
        info.update(self.get_thread_info(proto))
        return info

    def get_thread_info(self, proto):
        #threads:
        info = {}
        info_threads = proto.get_threads()
        info["threads"] = threading.active_count() - len(info_threads)
        info["info_threads"] = len(info_threads)
        i = 0
        #threads used by the "info" client:
        for t in info_threads:
            info["info_thread[%s]" % i] = t.name
            i += 1
        i = 0
        #all non-info threads:
        for t in threading.enumerate():
            if t not in info_threads:
                info["thread[%s]" % i] = t.name
                i += 1
        #platform specific bits:
        try:
            from xpra.platform.info import get_sys_info
            for k,v in get_sys_info().items():
                info[k] = v
        except:
            log.error("error getting system info", exc_info=True)
        return info

    def process_packet(self, proto, packet):
        try:
            handler = None
            packet_type = packet[0]
            if type(packet_type)==int:
                packet_type = self._aliases.get(packet_type)
            assert isinstance(packet_type, types.StringTypes), "packet_type %s is not a string: %s..." % (type(packet_type), str(packet_type)[:100])
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                log("process packet %s", packet_type)
                handler(proto, packet)
                return
            log.error("unknown or invalid packet type: %s from %s", packet_type, proto)
            if proto not in self._server_sources:
                proto.close()
        except KeyboardInterrupt:
            raise
        except:
            log.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
