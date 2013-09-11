# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import types
import os.path
import sys
import hmac
import time
import socket
import signal

from xpra.log import Logger
log = Logger()

import xpra
from xpra.scripts.config import ENCRYPTION_CIPHERS, python_platform
from xpra.scripts.server import deadly_signal
from xpra.net.bytestreams import SocketConnection
from xpra.os_util import set_application_name, get_hex_uuid, SIGNAMES
from xpra.version_util import version_compat_check, add_version_info
from xpra.net.protocol import Protocol, has_rencode, has_lz4, rencode_version, use_rencode
from xpra.util import typedict


MAX_CONCURRENT_CONNECTIONS = 20


class ServerCore(object):
    """
        This is the simplest base class for servers.
        It only handles establishing the connection.
    """

    def __init__(self):
        log("ServerCore.__init__()")
        self.start_time = time.time()

        self._upgrading = False
        #networking bits:
        self._potential_protocols = []
        self._aliases = {}
        self._reverse_aliases = {}
        self.socket_types = {}

        self.session_name = "Xpra"

        #Features:
        self.compression_level = 1
        self.password_file = ""

        self.init_packet_handlers()
        self.init_aliases()

    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()

    def init(self, opts):
        log("ServerCore.init(%s, %s)", opts)
        self.session_name = opts.session_name
        set_application_name(self.session_name)

        self.compression_level = opts.compression_level
        self.password_file = opts.password_file

    def init_sockets(self, sockets):
        ### All right, we're ready to accept customers:
        for socktype, sock in sockets:
            self.idle_add(self.add_listen_socket, socktype, sock)


    def init_packet_handlers(self):
        log("initializing packet handlers")
        self._default_packet_handlers = {
            "hello":                                self._process_hello,
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

    def run(self):
        log.info("xpra server version %s" % xpra.__version__)
        log.info("running with pid %s" % os.getpid())
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
        if len(self._potential_protocols)>=MAX_CONCURRENT_CONNECTIONS:
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
        protocol = Protocol(sc, self.process_packet)
        protocol.large_packets.append("info-response")
        protocol.salt = None
        protocol.set_compression_level(self.compression_level)
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

    def _process_gibberish(self, proto, packet):
        data = packet[1]
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.disconnect_client(proto, "invalid packet format")


    def _send_password_challenge(self, proto, server_cipher):
        proto.salt = get_hex_uuid()
        log.info("Password required, sending challenge")
        proto.send_now(("challenge", proto.salt, server_cipher))

    def _verify_password(self, proto, client_hash, password):
        salt = proto.salt
        proto.salt = None
        if not salt:
            self.send_disconnect(proto, "illegal challenge response received - salt cleared or unset")
            return False
        password_hash = hmac.HMAC(password, salt)
        if client_hash != password_hash.hexdigest():
            def login_failed(*args):
                log.error("Password supplied does not match! dropping the connection.")
                self.send_disconnect(proto, "invalid password")
            self.timeout_add(1000, login_failed)
            return False
        log.info("Password matches!")
        sys.stdout.flush()
        return True

    def get_password(self):
        if not self.password_file:
            return None
        filename = os.path.expanduser(self.password_file)
        if not filename:
            return None
        try:
            passwordFile = open(filename, "rU")
            password  = passwordFile.read()
            passwordFile.close()
            while len(password)>0 and password[-1] in ("\n", "\r"):
                password = password[:-1]
            return password
        except IOError, e:
            log.error("cannot open password file %s: %s", filename, e)
            return None


    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        c = typedict(capabilities)

        proto.chunked_compression = c.boolget("chunked_compression")
        if use_rencode and c.boolget("rencode"):
            proto.enable_rencode()
        if c.boolget("lz4") and proto.chunked_compression and self.compression_level>0 and self.compression_level<3:
            proto.enable_lz4()

        log("process_hello: capabilities=%s", capabilities)
        if c.boolget("version_request"):
            response = {"version" : xpra.__version__}
            proto.send_now(("hello", response))
            self.timeout_add(5*1000, self.send_disconnect, proto, "version sent")
            return False
    
        auth_caps = self.verify_hello(proto, c)
        if auth_caps is not False:
            #continue processing hello packet:
            self.hello_oked(proto, packet, c, auth_caps)


    def verify_hello(self, proto, c):
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, "incompatible version: %s" % verr)
            proto.close()
            return  False
        #client may have requested encryption:
        cipher = c.strget("cipher")
        cipher_iv = c.strget("cipher.iv")
        key_salt = c.strget("cipher.key_salt")
        iterations = c.intget("cipher.key_stretch_iterations")
        password = None
        if bool(self.password_file) or (cipher is not None and cipher_iv is not None):
            #we will need the password:
            log("process_hello password is required!")
            password = self.get_password()
            if not password:
                self.send_disconnect(proto, "password not found")
                return False
        auth_caps = {}
        if cipher and cipher_iv:
            if cipher not in ENCRYPTION_CIPHERS:
                log.warn("unsupported cipher: %s", cipher)
                self.send_disconnect(proto, "unsupported cipher")
                return False
            proto.set_cipher_out(cipher, cipher_iv, password, key_salt, iterations)
            #use the same cipher as used by the client:
            iv = get_hex_uuid()[:16]
            key_salt = get_hex_uuid()
            iterations = 1000
            proto.set_cipher_in(cipher, iv, password, key_salt, iterations)
            auth_caps = {
                         "cipher"           : cipher,
                         "cipher.iv"        : iv,
                         "cipher.key_salt"  : key_salt,
                         "cipher.key_stretch_iterations" : iterations
                         }
            log("server cipher=%s", auth_caps)

        if self.password_file:
            log("password auth required")
            #send challenge if this is not a response:
            client_hash = c.strget("challenge_response")
            if not client_hash or not proto.salt:
                self._send_password_challenge(proto, auth_caps or "")
                return False
            if not self._verify_password(proto, client_hash, password):
                return False
        return auth_caps

    def hello_oked(self, proto, packet, c, auth_caps):
        pass


    def accept_client(self, proto, c):
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.aliases = c.dictget("aliases")


    def make_hello(self):
        capabilities = {}
        capabilities["hostname"] = socket.gethostname()
        capabilities["version"] = xpra.__version__
        capabilities["platform"] = sys.platform
        capabilities["platform.release"] = python_platform.release()
        capabilities["platform.platform"] = python_platform.platform()
        if sys.platform.startswith("linux"):
            capabilities["platform.linux_distribution"] = python_platform.linux_distribution()
        capabilities["python_version"] = python_platform.python_version()
        if self.session_name:
            capabilities["session_name"] = self.session_name
        capabilities["start_time"] = int(self.start_time)
        now = time.time()
        capabilities["current_time"] = int(now)
        capabilities["elapsed_time"] = int(now - self.start_time)
        capabilities["raw_packets"] = True
        capabilities["chunked_compression"] = True
        capabilities["lz4"] = has_lz4
        capabilities["rencode"] = has_rencode
        if has_rencode:
            capabilities["rencode.version"] = rencode_version
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        capabilities["server_type"] = "core"
        add_version_info(capabilities)
        return capabilities

    def send_hello(self, server_cipher):
        capabilities = self.make_hello()
        if server_cipher:
            capabilities.update(server_cipher)
        pass


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
