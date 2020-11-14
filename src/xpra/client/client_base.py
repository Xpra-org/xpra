# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import uuid
import signal
import socket
import string

from xpra.log import Logger
from xpra.scripts.config import InitExit
from xpra.child_reaper import getChildReaper, reaper_cleanup
from xpra.net import compression
from xpra.net.common import may_log_packet, PACKET_TYPES
from xpra.net.protocol_classes import get_client_protocol_class
from xpra.net.protocol import Protocol, sanity_checks
from xpra.net.net_util import get_network_caps
from xpra.net.digest import get_salt, gendigest
from xpra.net.crypto import (
    crypto_backend_init, get_iterations, get_iv, choose_padding,
    ENCRYPTION_CIPHERS, ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT,
    DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS, PADDING_OPTIONS,
    )
from xpra.version_util import get_version_info, XPRA_VERSION
from xpra.platform.info import get_name
from xpra.os_util import (
    get_machine_id, get_user_uuid, register_SIGUSR_signals,
    load_binary_file, force_quit,
    SIGNAMES, BITS,
    strtobytes, bytestostr, hexstr, monotonic_time, use_tty,
    )
from xpra.util import (
    flatten_dict, typedict, updict, parse_simple_dict,
    repr_ellipsized, ellipsizer, nonl,
    envbool, envint, disconnect_is_an_error, dump_all_frames, engs, csv, obsc,
    )
from xpra.client.mixins.serverinfo_mixin import ServerInfoMixin
from xpra.client.mixins.fileprint_mixin import FilePrintMixin
from xpra.exit_codes import (EXIT_OK, EXIT_CONNECTION_LOST, EXIT_TIMEOUT, EXIT_UNSUPPORTED,
        EXIT_PASSWORD_REQUIRED, EXIT_PASSWORD_FILE_ERROR, EXIT_INCOMPATIBLE_VERSION,
        EXIT_ENCRYPTION, EXIT_FAILURE, EXIT_PACKET_FAILURE,
        EXIT_NO_AUTHENTICATION, EXIT_INTERNAL_ERROR)

log = Logger("client")
netlog = Logger("network")
authlog = Logger("auth")
mouselog = Logger("mouse")
cryptolog = Logger("crypto")
bandwidthlog = Logger("bandwidth")

EXTRA_TIMEOUT = 10
ALLOW_UNENCRYPTED_PASSWORDS = envbool("XPRA_ALLOW_UNENCRYPTED_PASSWORDS", False)
ALLOW_LOCALHOST_PASSWORDS = envbool("XPRA_ALLOW_LOCALHOST_PASSWORDS", True)
DETECT_LEAKS = envbool("XPRA_DETECT_LEAKS", False)
LEGACY_SALT_DIGEST = envbool("XPRA_LEGACY_SALT_DIGEST", True)
MOUSE_DELAY = envint("XPRA_MOUSE_DELAY", 0)


def noop():
    pass


""" Base class for Xpra clients.
    Provides the glue code for:
    * sending packets via Protocol
    * handling packets received via _process_packet
    For an actual implementation, look at:
    * GObjectXpraClient
    * xpra.client.gtk2.client
    * xpra.client.gtk3.client
"""
class XpraClientBase(ServerInfoMixin, FilePrintMixin):

    INSTALL_SIGNAL_HANDLERS = True

    def __init__(self):
        #this may be called more than once,
        #skip doing internal init again:
        if not hasattr(self, "exit_code"):
            self.defaults_init()
        ServerInfoMixin.__init__(self)
        FilePrintMixin.__init__(self)
        self._init_done = False

    def defaults_init(self):
        #skip warning when running the client
        from xpra import child_reaper
        child_reaper.POLL_WARNING = False
        getChildReaper()
        log("XpraClientBase.defaults_init() os.environ:")
        for k,v in os.environ.items():
            log(" %s=%s", k, nonl(v))
        #client state:
        self.exit_code = None
        self.exit_on_signal = False
        self.display_desc = {}
        #connection attributes:
        self.hello_extra = {}
        self.compression_level = 0
        self.display = None
        self.challenge_handlers = []
        self.username = None
        self.password = None
        self.password_file = ()
        self.password_index = 0
        self.password_sent = False
        self.encryption = None
        self.encryption_keyfile = None
        self.server_padding_options = [DEFAULT_PADDING]
        self.server_client_shutdown = True
        self.server_compressors = []
        #protocol stuff:
        self._protocol = None
        self._priority_packets = []
        self._ordinary_packets = []
        self._mouse_position = None
        self._mouse_position_pending = None
        self._mouse_position_send_time = 0
        self._mouse_position_delay = MOUSE_DELAY
        self._mouse_position_timer = 0
        self._aliases = {}
        #server state and caps:
        self.connection_established = False
        self.completed_startup = False
        self.uuid = get_user_uuid()
        self.session_id = uuid.uuid4().hex
        self.init_packet_handlers()
        self.have_more = noop
        sanity_checks()

    def init(self, opts):
        if self._init_done:
            #the gtk client classes can inherit this method
            #from multiple parents, skip initializing twice
            return
        self._init_done = True
        for c in XpraClientBase.__bases__:
            c.init(self, opts)
        self.compression_level = opts.compression_level
        self.display = opts.display
        self.username = opts.username
        self.password = opts.password
        self.password_file = opts.password_file
        self.encryption = opts.encryption or opts.tcp_encryption
        if self.encryption:
            crypto_backend_init()
        self.encryption_keyfile = opts.encryption_keyfile or opts.tcp_encryption_keyfile
        self.init_challenge_handlers(opts.challenge_handlers)
        self.init_aliases()
        if self.INSTALL_SIGNAL_HANDLERS:
            self.install_signal_handlers()


    def init_challenge_handlers(self, challenge_handlers):
        #register the authentication challenge handlers:
        authlog("init_challenge_handlers(%s)", challenge_handlers)
        ch = tuple(x.strip() for x in (challenge_handlers or "".split(",")))
        for ch_name in ch:
            if ch_name=="none":
                continue
            if ch_name=="all":
                items = (
                    "uri", "file", "env",
                    "kerberos", "gss",
                    "u2f",
                    "prompt", "prompt", "prompt", "prompt",
                    )
                ierror = authlog
            else:
                items = (ch_name, )
                ierror = authlog.warn
            for auth in items:
                instance = self.get_challenge_handler(auth, ierror)
                if instance:
                    self.challenge_handlers.append(instance)
        if DETECT_LEAKS:
            from xpra.util import detect_leaks
            print_leaks = detect_leaks()
            self.timeout_add(10*1000, print_leaks)

    def get_challenge_handler(self, auth, import_error_logger):
        #the module may have attributes,
        #ie: file:filename=password.txt
        parts = auth.split(":", 1)
        mod_name = parts[0]
        kwargs = {}
        if len(parts)==2:
            kwargs = parse_simple_dict(parts[1])
        auth_mod_name = "xpra.client.auth.%s_handler" % mod_name
        authlog("auth module name for '%s': '%s'", auth, auth_mod_name)
        try:
            auth_module = __import__(auth_mod_name, {}, {}, ["Handler"])
            auth_class = auth_module.Handler
            instance = auth_class(self, **kwargs)
            return instance
        except ImportError as e:
            import_error_logger("Error: authentication handler %s not available", mod_name)
            import_error_logger(" %s", e)
        except Exception as e:
            authlog("get_challenge_handler(%s)", auth, exc_info=True)
            authlog.error("Error: cannot instantiate authentication handler")
            authlog.error(" '%s': %s", mod_name, e)
        return None


    def may_notify(self, nid, summary, body, *args, **kwargs):
        notifylog = Logger("notify")
        notifylog("may_notify(%s, %s, %s, %s, %s)", nid, summary, body, args, kwargs)
        notifylog.info("%s", summary)
        if body:
            for x in body.splitlines():
                notifylog.info(" %s", x)


    def handle_deadly_signal(self, signum, _frame=None):
        sys.stderr.write("\ngot deadly signal %s, exiting\n" % SIGNAMES.get(signum, signum))
        sys.stderr.flush()
        self.cleanup()
        force_quit(128 + signum)

    def handle_app_signal(self, signum, _frame=None):
        try:
            log.info("exiting")
        except Exception:
            pass
        signal.signal(signal.SIGINT, self.handle_deadly_signal)
        signal.signal(signal.SIGTERM, self.handle_deadly_signal)
        self.signal_cleanup()
        reason = "exit on signal %s" % SIGNAMES.get(signum, signum)
        self.timeout_add(0, self.signal_disconnect_and_quit, 128 + signum, reason)

    def install_signal_handlers(self):
        def os_signal(signum, _frame=None):
            try:
                sys.stderr.write("\n")
                sys.stderr.flush()
                log.info("client got signal %s", SIGNAMES.get(signum, signum))
            except Exception:
                pass
            self.handle_app_signal(signum)
        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        register_SIGUSR_signals(self.idle_add)

    def signal_disconnect_and_quit(self, exit_code, reason):
        log("signal_disconnect_and_quit(%s, %s) exit_on_signal=%s", exit_code, reason, self.exit_on_signal)
        if not self.exit_on_signal:
            #if we get another signal, we'll try to exit without idle_add...
            self.exit_on_signal = True
            self.idle_add(self.disconnect_and_quit, exit_code, reason)
            self.idle_add(self.quit, exit_code)
            self.idle_add(self.exit)
            return
        #warning: this will run cleanup code from the signal handler
        self.disconnect_and_quit(exit_code, reason)
        self.quit(exit_code)
        self.exit()
        force_quit(exit_code)

    def signal_cleanup(self):
        #placeholder for stuff that can be cleaned up from the signal handler
        #(non UI thread stuff)
        pass

    def disconnect_and_quit(self, exit_code, reason):
        #make sure that we set the exit code early,
        #so the protocol shutdown won't set a different one:
        if self.exit_code is None:
            self.exit_code = exit_code
        #try to tell the server we're going, then quit
        log("disconnect_and_quit(%s, %s)", exit_code, reason)
        p = self._protocol
        if p is None or p.is_closed():
            self.quit(exit_code)
            return
        def protocol_closed():
            log("disconnect_and_quit: protocol_closed()")
            self.idle_add(self.quit, exit_code)
        if p:
            p.send_disconnect([reason], done_callback=protocol_closed)
        self.timeout_add(1000, self.quit, exit_code)

    def exit(self):
        log("XpraClientBase.exit() calling %s", sys.exit)
        sys.exit()


    def client_type(self) -> str:
        #overriden in subclasses!
        return "Python"

    def get_scheduler(self):
        raise NotImplementedError()

    def setup_connection(self, conn):
        netlog("setup_connection(%s) timeout=%s, socktype=%s", conn, conn.timeout, conn.socktype)
        if conn.socktype=="udp":
            self.add_packet_handler("udp-control", self._process_udp_control, False)
        protocol_class = get_client_protocol_class(conn.socktype)
        protocol = protocol_class(self.get_scheduler(), conn, self.process_packet, self.next_packet)
        self._protocol = protocol
        for x in (b"keymap-changed", b"server-settings", b"logging", b"input-devices"):
            protocol.large_packets.append(x)
        protocol.set_compression_level(self.compression_level)
        protocol.receive_aliases.update(self._aliases)
        protocol.enable_default_encoder()
        protocol.enable_default_compressor()
        if self.encryption and ENCRYPT_FIRST_PACKET:
            key = self.get_encryption_key()
            protocol.set_cipher_out(self.encryption,
                                          DEFAULT_IV, key, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING)
        self.have_more = protocol.source_has_more
        if conn.timeout>0:
            self.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)
        process = getattr(conn, "process", None)        #ie: ssh is handled by another process
        if process:
            proc, name, command = process
            if proc:
                getChildReaper().add_process(proc, name, command, ignore=True, forget=False)
        netlog("setup_connection(%s) protocol=%s", conn, protocol)
        return protocol

    def _process_udp_control(self, packet):
        #send it back to the protocol object:
        self._protocol.process_control(*packet[1:])


    def init_aliases(self):
        i = 1
        for key in PACKET_TYPES:
            self._aliases[i] = key
            i += 1

    def has_password(self) -> bool:
        return self.password or self.password_file or os.environ.get('XPRA_PASSWORD')

    def send_hello(self, challenge_response=None, client_salt=None):
        if not self._protocol:
            log("send_hello(..) skipped, no protocol (listen mode?)")
            return
        try:
            hello = self.make_hello_base()
            if self.has_password() and not challenge_response:
                #avoid sending the full hello: tell the server we want
                #a packet challenge first
                hello["challenge"] = True
            else:
                hello.update(self.make_hello())
        except InitExit as e:
            log.error("error preparing connection:")
            log.error(" %s", e)
            self.quit(EXIT_INTERNAL_ERROR)
            return
        except Exception as e:
            log.error("error preparing connection: %s", e, exc_info=True)
            self.quit(EXIT_INTERNAL_ERROR)
            return
        if challenge_response:
            hello["challenge_response"] = challenge_response
            #make it harder for a passive attacker to guess the password length
            #by observing packet sizes (only relevant for wss and ssl)
            hello["challenge_padding"] = get_salt(max(32, 512-len(challenge_response)))
            if client_salt:
                hello["challenge_client_salt"] = client_salt
        log("send_hello(%s) packet=%s", hexstr(challenge_response or ""), hello)
        self.send("hello", hello)

    def verify_connected(self):
        if not self.connection_established:
            #server has not said hello yet
            self.warn_and_quit(EXIT_TIMEOUT, "connection timed out")


    def make_hello_base(self):
        capabilities = flatten_dict(get_network_caps())
        #add "kerberos", "gss" and "u2f" digests if enabled:
        for handler in self.challenge_handlers:
            digest = handler.get_digest()
            if digest:
                capabilities["digest"].append(digest)
        capabilities.update(FilePrintMixin.get_caps(self))
        capabilities.update({
                "version"               : XPRA_VERSION,
                "websocket.multi-packet": True,
                "hostname"              : socket.gethostname(),
                "uuid"                  : self.uuid,
                "session-id"            : self.session_id,
                "username"              : self.username,
                "name"                  : get_name(),
                "client_type"           : self.client_type(),
                "python.version"        : sys.version_info[:3],
                "python.bits"           : BITS,
                "compression_level"     : self.compression_level,
                "argv"                  : sys.argv,
                })
        capabilities.update(self.get_file_transfer_features())
        if self.display:
            capabilities["display"] = self.display
        def up(prefix, d):
            updict(capabilities, prefix, d)
        up("build",     self.get_version_info())
        mid = get_machine_id()
        if mid:
            capabilities["machine_id"] = mid
        if self.encryption:
            assert self.encryption in ENCRYPTION_CIPHERS
            iv = get_iv()
            key_salt = get_salt()
            iterations = get_iterations()
            padding = choose_padding(self.server_padding_options)
            up("cipher", {
                    ""                      : self.encryption,
                    "iv"                    : iv,
                    "key_salt"              : key_salt,
                    "key_stretch_iterations": iterations,
                    "padding"               : padding,
                    "padding.options"       : PADDING_OPTIONS,
                    })
            key = self.get_encryption_key()
            if key is None:
                self.warn_and_quit(EXIT_ENCRYPTION, "encryption key is missing")
                return None
            self._protocol.set_cipher_in(self.encryption, iv, key, key_salt, iterations, padding)
            netlog("encryption capabilities: %s", dict((k,v) for k,v in capabilities.items() if k.startswith("cipher")))
        capabilities.update(self.hello_extra)
        return capabilities

    def get_version_info(self) -> dict:
        return get_version_info()

    def make_hello(self):
        capabilities = {
                        "randr_notify"        : False,        #only client.py cares about this
                        "windows"            : False,        #only client.py cares about this
                       }
        if self._aliases:
            reverse_aliases = {}
            for i, packet_type in self._aliases.items():
                reverse_aliases[packet_type] = i
            capabilities["aliases"] = reverse_aliases
        return capabilities

    def compressed_wrapper(self, datatype, data, level=5):
        #ugly assumptions here, should pass by name
        zlib = "zlib" in self.server_compressors and compression.use_zlib
        lz4 = "lz4" in self.server_compressors and compression.use_lz4
        lzo = "lzo" in self.server_compressors and compression.use_lzo
        brotli = False
        #never use brotli as a generic compressor
        #brotli = "brotli" in self.server_compressors and compression.use_brotli
        if level>0 and len(data)>=256 and (zlib or lz4 or lzo):
            cw = compression.compressed_wrapper(datatype, data, level=level,
                                                zlib=zlib, lz4=lz4, lzo=lzo, brotli=brotli,
                                                can_inline=False)
            if len(cw)<len(data):
                #the compressed version is smaller, use it:
                return cw
        #we can't compress, so at least avoid warnings in the protocol layer:
        return compression.Compressed("raw %s" % datatype, data, can_inline=True)


    def send(self, *parts):
        self._ordinary_packets.append(parts)
        self.have_more()

    def send_now(self, *parts):
        self._priority_packets.append(parts)
        self.have_more()

    def send_positional(self, packet):
        #packets that include the mouse position in them
        #we can cancel the pending position packets
        self._ordinary_packets.append(packet)
        self._mouse_position = None
        self._mouse_position_pending = None
        self.cancel_send_mouse_position_timer()
        self.have_more()

    def send_mouse_position(self, packet):
        if self._mouse_position_timer:
            self._mouse_position_pending = packet
            return
        self._mouse_position_pending = packet
        now = monotonic_time()
        elapsed = int(1000*(now-self._mouse_position_send_time))
        delay = self._mouse_position_delay-elapsed
        mouselog("send_mouse_position(%s) elapsed=%i, delay left=%i", packet, elapsed, delay)
        if delay>0:
            self._mouse_position_timer = self.timeout_add(delay, self.do_send_mouse_position)
        else:
            self.do_send_mouse_position()

    def do_send_mouse_position(self):
        self._mouse_position_timer = 0
        self._mouse_position_send_time = monotonic_time()
        self._mouse_position = self._mouse_position_pending
        mouselog("do_send_mouse_position() position=%s", self._mouse_position)
        self.have_more()

    def cancel_send_mouse_position_timer(self):
        mpt = self._mouse_position_timer
        if mpt:
            self._mouse_position_timer = 0
            self.source_remove(mpt)


    def next_packet(self):
        netlog("next_packet() packets in queues: priority=%i, ordinary=%i, mouse=%s",
               len(self._priority_packets), len(self._ordinary_packets), bool(self._mouse_position))
        synchronous = True
        if self._priority_packets:
            packet = self._priority_packets.pop(0)
        elif self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif self._mouse_position is not None:
            packet = self._mouse_position
            synchronous = False
            self._mouse_position = None
        else:
            packet = None
        has_more = packet is not None and \
                (bool(self._priority_packets) or bool(self._ordinary_packets) \
                 or self._mouse_position is not None)
        return packet, None, None, None, synchronous, has_more


    def cleanup(self):
        reaper_cleanup()
        try:
            FilePrintMixin.cleanup(self)
        except Exception:
            log.error("%s", FilePrintMixin.cleanup, exc_info=True)
        p = self._protocol
        log("XpraClientBase.cleanup() protocol=%s", p)
        if p:
            log("calling %s", p.close)
            p.close()
            self._protocol = None
        log("cleanup done")
        self.cancel_send_mouse_position_timer()
        dump_all_frames()


    def glib_init(self):
        #this will take care of calling threads_init if needed:
        from gi.repository import GLib
        register_SIGUSR_signals(GLib.idle_add)

    def run(self):
        #protocol may be None in "listen" mode
        if self._protocol:
            self._protocol.start()

    def quit(self, exit_code=0):
        raise Exception("override me!")

    def warn_and_quit(self, exit_code, message):
        log.warn(message)
        self.quit(exit_code)


    def send_shutdown_server(self):
        assert self.server_client_shutdown
        self.send("shutdown-server")

    def _process_disconnect(self, packet):
        #ie: ("disconnect", "version error", "incompatible version")
        info = tuple(nonl(bytestostr(x)) for x in packet[1:])
        reason = info[0]
        if not self.connection_established:
            #server never sent hello to us - so disconnect is an error
            #(but we don't know which one - the info message may help)
            self.server_disconnect_warning("disconnected before the session could be established", *info)
        elif disconnect_is_an_error(reason):
            self.server_disconnect_warning(*info)
        elif self.exit_code is None:
            #we're not in the process of exiting already,
            #tell the user why the server is disconnecting us
            self.server_disconnect(*info)

    def server_disconnect_warning(self, reason, *extra_info):
        log.warn("Warning: server connection failure:")
        log.warn(" %s", reason)
        for x in extra_info:
            log.warn(" %s", x)
        self.quit(EXIT_FAILURE)

    def server_disconnect(self, reason, *extra_info):
        log.info("server requested disconnect:")
        log.info(" %s", reason)
        for x in extra_info:
            log.info(" %s", x)
        self.quit(EXIT_OK)


    def _process_connection_lost(self, _packet):
        p = self._protocol
        if p and p.input_raw_packetcount==0:
            props = p.get_info()
            c = props.get("compression", "unknown")
            e = props.get("encoder", "rencode")
            netlog.error("Error: failed to receive anything, not an xpra server?")
            netlog.error("  could also be the wrong protocol, username, password or port")
            netlog.error("  or the session was not found")
            if c!="unknown" or e!="rencode":
                netlog.error("  or maybe this server does not support '%s' compression or '%s' packet encoding?", c, e)
        if self.exit_code is None:
            self.warn_and_quit(EXIT_CONNECTION_LOST, "Connection lost")


    ########################################
    # Authentication
    def _process_challenge(self, packet):
        authlog("processing challenge: %s", packet[1:])
        if not self.validate_challenge_packet(packet):
            return
        authlog("challenge handlers: %s", self.challenge_handlers)
        digest = bytestostr(packet[3])
        while self.challenge_handlers:
            handler = self.pop_challenge_handler(digest)
            try:
                authlog("calling challenge handler %s", handler)
                r = handler.handle(packet)
                authlog("%s(%s)=%s", handler.handle, packet, r)
                if r:
                    #the challenge handler claims to have handled authentication
                    return
            except Exception as e:
                authlog("%s(%s)", handler.handle, packet, exc_info=True)
                authlog.error("Error in %r challenge handler:", handler)
                authlog.error(" %s", str(e) or type(e))
                continue
        authlog.warn("Warning: failed to connect, authentication required")
        self.quit(EXIT_PASSWORD_REQUIRED)

    def pop_challenge_handler(self, digest):
        #find the challenge handler most suitable for this digest type,
        #otherwise take the first one
        digest_type = digest.split(":")[0]  #ie: "kerberos:value" -> "kerberos"
        index = 0
        for i, handler in enumerate(self.challenge_handlers):
            if handler.get_digest()==digest_type:
                index = i
                break
        return self.challenge_handlers.pop(index)


    #utility method used by some authentication handlers,
    #and overriden in UI client to provide a GUI dialog
    def do_process_challenge_prompt(self, packet, prompt="password"):
        authlog("do_process_challenge_prompt() use_tty=%s", use_tty())
        if use_tty():
            import getpass
            authlog("stdin isatty, using password prompt")
            password = getpass.getpass("%s :" % self.get_challenge_prompt(prompt))
            authlog("password read from tty via getpass: %s", obsc(password))
            self.send_challenge_reply(packet, password)
            return True
        return False

    def auth_error(self, code, message, server_message="authentication failed"):
        authlog.error("Error: authentication failed:")
        authlog.error(" %s", message)
        self.disconnect_and_quit(code, server_message)

    def validate_challenge_packet(self, packet):
        digest = bytestostr(packet[3])
        #don't send XORed password unencrypted:
        if digest=="xor":
            encrypted = self._protocol.cipher_out or self._protocol.get_info().get("type") in ("ssl", "wss")
            local = self.display_desc.get("local", False)
            authlog("xor challenge, encrypted=%s, local=%s", encrypted, local)
            if local and ALLOW_LOCALHOST_PASSWORDS:
                return True
            if not encrypted and not ALLOW_UNENCRYPTED_PASSWORDS:
                self.auth_error(EXIT_ENCRYPTION,
                                "server requested '%s' digest, cowardly refusing to use it without encryption" % digest,
                                "invalid digest")
                return False
        salt_digest = "xor"
        if len(packet)>=5:
            salt_digest = bytestostr(packet[4])
        if salt_digest in ("xor", "des"):
            if not LEGACY_SALT_DIGEST:
                self.auth_error(EXIT_INCOMPATIBLE_VERSION, "server uses legacy salt digest '%s'" % salt_digest)
                return False
            log.warn("Warning: server using legacy support for '%s' salt digest", salt_digest)
        return True

    def get_challenge_prompt(self, prompt="password"):
        text = "Please enter the %s" % (prompt,)
        try:
            from xpra.net.bytestreams import pretty_socket
            conn = self._protocol._conn
            text += " for user '%s',\n connecting to %s server %s" % (
                self.username, conn.socktype, pretty_socket(conn.remote),
                )
        except Exception:
            pass
        return text

    def send_challenge_reply(self, packet, password):
        if not password:
            if self.password_file:
                self.auth_error(EXIT_PASSWORD_FILE_ERROR,
                                "failed to load password from file%s %s" % (engs(self.password_file), csv(self.password_file)),
                                "no password available")
            else:
                self.auth_error(EXIT_PASSWORD_REQUIRED,
                                "this server requires authentication and no password is available")
            return
        if self.encryption:
            assert len(packet)>=3, "challenge does not contain encryption details to use for the response"
            server_cipher = typedict(packet[2])
            key = self.get_encryption_key()
            if key is None:
                self.auth_error(EXIT_ENCRYPTION, "the server does not use any encryption", "client requires encryption")
                return
            if not self.set_server_encryption(server_cipher, key):
                return
        #all server versions support a client salt,
        #they also tell us which digest to use:
        server_salt = bytestostr(packet[1])
        digest = bytestostr(packet[3])
        actual_digest = digest.split(":", 1)[0]
        l = len(server_salt)
        salt_digest = "xor"
        if len(packet)>=5:
            salt_digest = bytestostr(packet[4])
        if salt_digest=="xor":
            #with xor, we have to match the size
            assert l>=16, "server salt is too short: only %i bytes, minimum is 16" % l
            assert l<=256, "server salt is too long: %i bytes, maximum is 256" % l
        else:
            #other digest, 32 random bytes is enough:
            l = 32
        client_salt = get_salt(l)
        salt = gendigest(salt_digest, client_salt, server_salt)
        authlog("combined %s salt(%s, %s)=%s", salt_digest, hexstr(server_salt), hexstr(client_salt), hexstr(salt))

        challenge_response = gendigest(actual_digest, password, salt)
        if not challenge_response:
            log("invalid digest module '%s': %s", actual_digest)
            self.auth_error(EXIT_UNSUPPORTED,
                            "server requested '%s' digest but it is not supported" % actual_digest, "invalid digest")
            return
        authlog("%s(%s, %s)=%s", actual_digest, repr(password), repr(salt), repr(challenge_response))
        self.do_send_challenge_reply(challenge_response, client_salt)

    def do_send_challenge_reply(self, challenge_response, client_salt):
        self.password_sent = True
        self.send_hello(challenge_response, client_salt)

    ########################################
    # Encryption
    def set_server_encryption(self, caps, key):
        cipher = caps.strget("cipher")
        cipher_iv = caps.strget("cipher.iv")
        key_salt = caps.strget("cipher.key_salt")
        iterations = caps.intget("cipher.key_stretch_iterations")
        padding = caps.strget("cipher.padding", DEFAULT_PADDING)
        #server may tell us what it supports,
        #either from hello response or from challenge packet:
        self.server_padding_options = caps.strtupleget("cipher.padding.options", (DEFAULT_PADDING,))
        if not cipher or not cipher_iv:
            self.warn_and_quit(EXIT_ENCRYPTION,
                               "the server does not use or support encryption/password, cannot continue with %s cipher" % self.encryption)
            return False
        if cipher not in ENCRYPTION_CIPHERS:
            self.warn_and_quit(EXIT_ENCRYPTION,
                               "unsupported server cipher: %s, allowed ciphers: %s" % (cipher, csv(ENCRYPTION_CIPHERS)))
            return False
        if padding not in ALL_PADDING_OPTIONS:
            self.warn_and_quit(EXIT_ENCRYPTION,
                               "unsupported server cipher padding: %s, allowed ciphers: %s" % (padding, csv(ALL_PADDING_OPTIONS)))
            return False
        p = self._protocol
        if not p:
            return False
        p.set_cipher_out(cipher, cipher_iv, key, key_salt, iterations, padding)
        return True


    def get_encryption_key(self):
        key = None
        if self.encryption_keyfile and os.path.exists(self.encryption_keyfile):
            key = load_binary_file(self.encryption_keyfile)
            cryptolog("get_encryption_key() loaded %i bytes from '%s'", len(key or ""), self.encryption_keyfile)
        else:
            cryptolog("get_encryption_key() file '%s' does not exist", self.encryption_keyfile)
        if not key:
            XPRA_ENCRYPTION_KEY = "XPRA_ENCRYPTION_KEY"
            key = strtobytes(os.environ.get(XPRA_ENCRYPTION_KEY, ''))
            cryptolog("get_encryption_key() got %i bytes from '%s' environment variable",
                      len(key or ""), XPRA_ENCRYPTION_KEY)
        if not key:
            raise InitExit(1, "no encryption key")
        return key.strip(b"\n\r")

    def _process_hello(self, packet):
        self.remove_packet_handlers("challenge")
        if not self.password_sent and self.has_password():
            self.warn_and_quit(EXIT_NO_AUTHENTICATION, "the server did not request our password")
            return
        try:
            caps = typedict(packet[1])
            netlog("processing hello from server: %s", ellipsizer(caps))
            if not self.server_connection_established(caps):
                self.warn_and_quit(EXIT_FAILURE, "failed to establish connection")
            else:
                self.connection_established = True
        except Exception as e:
            netlog.info("error in hello packet", exc_info=True)
            self.warn_and_quit(EXIT_FAILURE, "error processing hello packet from server: %s" % e)


    def server_connection_established(self, caps : typedict) -> bool:
        netlog("server_connection_established(..)")
        if not self.parse_encryption_capabilities(caps):
            netlog("server_connection_established(..) failed encryption capabilities")
            return False
        if not self.parse_server_capabilities(caps):
            netlog("server_connection_established(..) failed server capabilities")
            return False
        if not self.parse_network_capabilities(caps):
            netlog("server_connection_established(..) failed network capabilities")
            return False
        #raise packet size if required:
        if self.file_transfer:
            self._protocol.max_packet_size = max(self._protocol.max_packet_size, self.file_size_limit*1024*1024)
        netlog("server_connection_established(..) adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        return True


    def parse_server_capabilities(self, caps : typedict) -> bool:
        for c in XpraClientBase.__bases__:
            if not c.parse_server_capabilities(self, caps):
                return False
        self.server_client_shutdown = caps.boolget("client-shutdown", True)
        self.server_compressors = caps.strtupleget("compressors", ("zlib",))
        return True

    def parse_network_capabilities(self, caps : typedict) -> bool:
        p = self._protocol
        if not p or not p.enable_encoder_from_caps(caps):
            return False
        p.enable_compressor_from_caps(caps)
        p.accept()
        p.parse_remote_caps(caps)
        return True

    def parse_encryption_capabilities(self, caps : typedict) -> bool:
        p = self._protocol
        if not p:
            return False
        if self.encryption:
            #server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(caps, key):
                return False
        return True

    def _process_set_deflate(self, packet):
        #legacy, should not be used for anything
        pass

    def _process_startup_complete(self, packet):
        #can be received if we connect with "xpra stop" or other command line client
        #as the server is starting up
        self.completed_startup = packet


    def _process_gibberish(self, packet):
        log("process_gibberish(%s)", ellipsizer(packet))
        message, data = packet[1:3]
        p = self._protocol
        show_as_text = p and p.input_packetcount==0 and all(c in string.printable for c in bytestostr(data))
        if show_as_text:
            #looks like the first packet back is just text, print it:
            data = bytestostr(data)
            if data.find("\n")>=0:
                for x in data.splitlines():
                    netlog.warn(x)
            else:
                netlog.error("Error: failed to connect, received")
                netlog.error(" %s", repr_ellipsized(data))
        else:
            netlog.error("Error: received uninterpretable nonsense: %s", message)
            if p:
                netlog.error(" packet no %i data: %s", p.input_packetcount, repr_ellipsized(data))
            else:
                netlog.error(" data: %s", repr_ellipsized(data))
        self.quit(EXIT_PACKET_FAILURE)

    def _process_invalid(self, packet):
        message, data = packet[1:3]
        netlog.info("Received invalid packet: %s", message)
        netlog(" data: %s", ellipsizer(data))
        self.quit(EXIT_PACKET_FAILURE)


    ######################################################################
    # packets:
    def remove_packet_handlers(self, *keys):
        for k in keys:
            for d in (self._packet_handlers, self._ui_packet_handlers):
                try:
                    del d[k]
                except KeyError:
                    pass

    def init_packet_handlers(self):
        self._packet_handlers = {}
        self._ui_packet_handlers = {}
        self.add_packet_handler("hello", self._process_hello, False)
        self.add_packet_handlers({
            "challenge":                self._process_challenge,
            "disconnect":               self._process_disconnect,
            "set_deflate":              self._process_set_deflate,
            "startup-complete":         self._process_startup_complete,
            Protocol.CONNECTION_LOST:   self._process_connection_lost,
            Protocol.GIBBERISH:         self._process_gibberish,
            Protocol.INVALID:           self._process_invalid,
            })

    def init_authenticated_packet_handlers(self):
        FilePrintMixin.init_authenticated_packet_handlers(self)

    def add_packet_handlers(self, defs, main_thread=True):
        for packet_type, handler in defs.items():
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type, handler, main_thread=True):
        netlog("add_packet_handler%s", (packet_type, handler, main_thread))
        self.remove_packet_handlers(packet_type)
        if main_thread:
            handlers = self._ui_packet_handlers
        else:
            handlers = self._packet_handlers
        handlers[packet_type] = handler

    def process_packet(self, _proto, packet):
        try:
            handler = None
            packet_type = packet[0]
            if packet_type!=int:
                packet_type = bytestostr(packet_type)
            def call_handler():
                may_log_packet(False, packet_type, packet)
                handler(packet)
            handler = self._packet_handlers.get(packet_type)
            if handler:
                call_handler()
                return
            handler = self._ui_packet_handlers.get(packet_type)
            if not handler:
                netlog.error("unknown packet type: %s", packet_type)
                return
            self.idle_add(call_handler)
        except Exception:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s",
                         packet_type, handler, exc_info=True)
