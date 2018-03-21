# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal
import os
import sys
import socket
import string
from collections import OrderedDict

from xpra.log import Logger
log = Logger("client")
netlog = Logger("network")
authlog = Logger("auth")
mouselog = Logger("mouse")
cryptolog = Logger("crypto")
bandwidthlog = Logger("bandwidth")

from xpra.scripts.config import InitExit, parse_with_unit
from xpra.child_reaper import getChildReaper, reaper_cleanup
from xpra.net import compression
from xpra.net.protocol import Protocol, sanity_checks
from xpra.net.net_util import get_network_caps
from xpra.net.crypto import crypto_backend_init, get_iterations, get_iv, get_salt, choose_padding, gendigest, \
    ENCRYPTION_CIPHERS, ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS, PADDING_OPTIONS
from xpra.version_util import get_version_info, XPRA_VERSION
from xpra.platform.info import get_name
from xpra.os_util import get_machine_id, get_user_uuid, load_binary_file, SIGNAMES, PYTHON3, strtobytes, bytestostr, hexstr, monotonic_time, BITS, WIN32
from xpra.util import flatten_dict, typedict, updict, repr_ellipsized, nonl, std, envbool, envint, disconnect_is_an_error, dump_all_frames, engs, csv, obsc, first_time
from xpra.client.mixins.serverinfo_mixin import ServerInfoMixin
from xpra.client.mixins.fileprint_mixin import FilePrintMixin

from xpra.exit_codes import (EXIT_OK, EXIT_CONNECTION_LOST, EXIT_TIMEOUT, EXIT_UNSUPPORTED,
        EXIT_PASSWORD_REQUIRED, EXIT_PASSWORD_FILE_ERROR, EXIT_INCOMPATIBLE_VERSION,
        EXIT_ENCRYPTION, EXIT_FAILURE, EXIT_PACKET_FAILURE,
        EXIT_NO_AUTHENTICATION, EXIT_INTERNAL_ERROR)


EXTRA_TIMEOUT = 10
KERBEROS_SERVICES = os.environ.get("XPRA_KERBEROS_SERVICES", "*").split(",")
GSS_SERVICES = os.environ.get("XPRA_GSS_SERVICES", "*").split(",")
ALLOW_UNENCRYPTED_PASSWORDS = envbool("XPRA_ALLOW_UNENCRYPTED_PASSWORDS", False)
ALLOW_LOCALHOST_PASSWORDS = envbool("XPRA_ALLOW_LOCALHOST_PASSWORDS", True)
DETECT_LEAKS = envbool("XPRA_DETECT_LEAKS", False)
LEGACY_SALT_DIGEST = envbool("XPRA_LEGACY_SALT_DIGEST", True)
MOUSE_DELAY = envint("XPRA_MOUSE_DELAY", 0)
AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert AUTO_BANDWIDTH_PCT>1 and AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT


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

    def __init__(self):
        #this may be called more than once,
        #skip doing internal init again:
        if not hasattr(self, "exit_code"):
            self.defaults_init()
        FilePrintMixin.__init__(self)
        self._init_done = False
        self.default_challenge_methods = OrderedDict({
            "uri"       : self.process_challenge_uri,
            "file"      : self.process_challenge_file,
            "env"       : self.process_challenge_env,
            "kerberos"  : self.process_challenge_kerberos,
            "gss"       : self.process_challenge_gss,
            "prompt"    : self.process_challenge_prompt,
            })


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
        self.challenge_handlers = OrderedDict()
        self.username = None
        self.password = None
        self.password_file = ()
        self.password_index = 0
        self.password_sent = False
        self.bandwidth_limit = 0
        self.encryption = None
        self.encryption_keyfile = None
        self.server_padding_options = [DEFAULT_PADDING]
        self.server_client_shutdown = True
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
        self._reverse_aliases = {}
        #server state and caps:
        self.server_capabilities = None
        self.completed_startup = False
        self.uuid = get_user_uuid()
        self.init_packet_handlers()
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
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit)
        bandwidthlog("init bandwidth_limit=%s", self.bandwidth_limit)
        self.encryption = opts.encryption or opts.tcp_encryption
        if self.encryption:
            crypto_backend_init()
        self.encryption_keyfile = opts.encryption_keyfile or opts.tcp_encryption_keyfile
        #register the authentication challenge handlers:
        ch = tuple(x.strip().lower() for x in (opts.challenge_handlers or "").split(","))
        def has_h(name):
            return "all" in ch or name in ch
        for ch_name in ch:
            if ch_name=="all":
                self.challenge_handlers.update(self.default_challenge_methods)
                break
            method = self.default_challenge_methods.get(ch_name)
            if method:
                self.challenge_handlers[ch_name] = method
                continue
            log.warn("Warning: unknown challenge handler '%s'", ch_name)
        if DETECT_LEAKS:
            from xpra.util import detect_leaks
            detailed = []
            #example: warning, uses ugly direct import:
            #try:
            #    from xpra.x11.bindings.ximage import XShmImageWrapper       #@UnresolvedImport
            #    detailed.append(XShmImageWrapper)
            #except:
            #    pass
            print_leaks = detect_leaks(log, detailed)
            self.timeout_add(10*1000, print_leaks)


    def timeout_add(self, *args):
        raise Exception("override me!")

    def idle_add(self, *args):
        raise Exception("override me!")

    def source_remove(self, *args):
        raise Exception("override me!")


    def install_signal_handlers(self):
        def deadly_signal(signum, _frame):
            sys.stderr.write("\ngot deadly signal %s, exiting\n" % SIGNAMES.get(signum, signum))
            sys.stderr.flush()
            self.cleanup()
            os._exit(128 + signum)
        def app_signal(signum, _frame):
            sys.stderr.write("\ngot signal %s, exiting\n" % SIGNAMES.get(signum, signum))
            sys.stderr.flush()
            signal.signal(signal.SIGINT, deadly_signal)
            signal.signal(signal.SIGTERM, deadly_signal)
            self.signal_cleanup()
            self.timeout_add(0, self.signal_disconnect_and_quit, 128 + signum, "exit on signal %s" % SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)

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
        os._exit(exit_code)

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
        if p is None or p._closed:
            self.quit(exit_code)
            return
        def protocol_closed():
            log("disconnect_and_quit: protocol_closed()")
            self.idle_add(self.quit, exit_code)
        if p:
            p.send_disconnect([reason], done_callback=protocol_closed)
        self.timeout_add(1000, self.quit, exit_code)

    def exit(self):
        sys.exit()


    def client_type(self):
        #overriden in subclasses!
        return "Python"

    def get_scheduler(self):
        raise NotImplementedError()

    def setup_connection(self, conn):
        netlog("setup_connection(%s) timeout=%s, socktype=%s", conn, conn.timeout, conn.socktype)
        if conn.socktype=="udp":
            from xpra.net.udp_protocol import UDPClientProtocol
            self._protocol = UDPClientProtocol(self.get_scheduler(), conn, self.process_packet, self.next_packet)
            #use a random uuid:
            import random
            self._protocol.uuid = random.randint(0, 2**64-1)
            self.set_packet_handlers(self._packet_handlers, {
                "udp-control"   : self._process_udp_control,
                })
        else:
            self._protocol = Protocol(self.get_scheduler(), conn, self.process_packet, self.next_packet)
        for x in ("keymap-changed", "server-settings", "logging", "input-devices"):
            self._protocol.large_packets.append(x)
        self._protocol.set_compression_level(self.compression_level)
        self._protocol.receive_aliases.update(self._aliases)
        self._protocol.enable_default_encoder()
        self._protocol.enable_default_compressor()
        if self.encryption and ENCRYPT_FIRST_PACKET:
            key = self.get_encryption_key()
            self._protocol.set_cipher_out(self.encryption, DEFAULT_IV, key, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING)
        self.have_more = self._protocol.source_has_more
        if conn.timeout>0:
            self.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)
        process = getattr(conn, "process", None)        #ie: ssh is handled by anotherprocess
        if process:
            proc, name, command = process
            getChildReaper().add_process(proc, name, command, ignore=True, forget=False)
        netlog("setup_connection(%s) protocol=%s", conn, self._protocol)

    def _process_udp_control(self, packet):
        #send it back to the protocol object:
        self._protocol.process_control(*packet[1:])


    def remove_packet_handlers(self, *keys):
        for k in keys:
            for d in (self._packet_handlers, self._ui_packet_handlers):
                try:
                    del d[k]
                except:
                    pass

    def set_packet_handlers(self, to, defs):
        """ configures the given packet handlers,
            and make sure we remove any existing ones with the same key
            (which can be useful for subclasses, not here)
        """
        log("set_packet_handlers(%s, %s)", to, defs)
        self.remove_packet_handlers(*defs.keys())
        for k,v in defs.items():
            to[k] = v

    def init_packet_handlers(self):
        self._packet_handlers = {}
        self._ui_packet_handlers = {}
        self.set_packet_handlers(self._packet_handlers, {"hello" : self._process_hello})
        self.set_packet_handlers(self._ui_packet_handlers, {
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


    def init_aliases(self):
        packet_types = list(self._packet_handlers.keys())
        packet_types += list(self._ui_packet_handlers.keys())
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1

    def has_password(self):
        return self.password or self.password_file or os.environ.get('XPRA_PASSWORD')

    def send_hello(self, challenge_response=None, client_salt=None):
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
        if self.server_capabilities is None:
            #server has not said hello yet
            self.warn_and_quit(EXIT_TIMEOUT, "connection timed out")


    def make_hello_base(self):
        capabilities = flatten_dict(get_network_caps())
        #add "kerberos" and "gss" if enabled:
        default_on = "all" in self.challenge_handlers or "auto" in self.challenge_handlers
        for auth in ("kerberos", "gss"):
            if default_on or auth in self.challenge_handlers:
                capabilities["digest"].append(auth)
        capabilities.update(FilePrintMixin.get_caps(self))
        capabilities.update({
                "version"               : XPRA_VERSION,
                "encoding.generic"      : True,
                "namespace"             : True,
                "hostname"              : socket.gethostname(),
                "uuid"                  : self.uuid,
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
        #get socket speed if we have it:
        pinfo = self._protocol.get_info()
        netlog("protocol info=%s", pinfo)
        socket_speed = pinfo.get("socket", {}).get("speed")
        if socket_speed:
            capabilities["connection-data"] = {"speed" : socket_speed}
        bandwidth_limit = self.bandwidth_limit
        bandwidthlog("bandwidth-limit setting=%s, socket-speed=%s", self.bandwidth_limit, socket_speed)
        if bandwidth_limit is None:
            if socket_speed:
                #auto: use 80% of socket speed if we have it:
                bandwidth_limit = socket_speed*AUTO_BANDWIDTH_PCT//100 or 0
            else:
                bandwidth_limit = 0
        bandwidthlog("bandwidth-limit capability=%s", bandwidth_limit)
        if bandwidth_limit>0:
            capabilities["bandwidth-limit"] = bandwidth_limit

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
                return
            self._protocol.set_cipher_in(self.encryption, iv, key, key_salt, iterations, padding)
            netlog("encryption capabilities: %s", dict((k,v) for k,v in capabilities.items() if k.startswith("cipher")))
        capabilities.update(self.hello_extra)
        return capabilities

    def get_version_info(self):
        return get_version_info()

    def make_hello(self):
        capabilities = {
                        "randr_notify"        : False,        #only client.py cares about this
                        "windows"            : False,        #only client.py cares about this
                       }
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        return capabilities

    def compressed_wrapper(self, datatype, data, level=5):
        #FIXME: ugly assumptions here, should pass by name!
        zlib = "zlib" in self.server_compressors and compression.use_zlib
        lz4 = "lz4" in self.server_compressors and compression.use_lz4
        lzo = "lzo" in self.server_compressors and compression.use_lzo
        if level>0 and len(data)>=256 and (zlib or lz4 or lzo):
            cw = compression.compressed_wrapper(datatype, data, level=level, zlib=zlib, lz4=lz4, lzo=lzo, can_inline=False)
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
        mouselog("send_mouse_position(%s) elapsed=%i, delay=%i", packet, elapsed, self._mouse_position_delay)
        if elapsed<self._mouse_position_delay:
            self._mouse_position_timer = self.timeout_add(self._mouse_position_delay-elapsed, self.do_send_mouse_position)
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


    def have_more(self):
        #this function is overridden in setup_protocol()
        p = self._protocol
        if p and p.source:
            p.source_has_more()

    def next_packet(self):
        netlog("next_packet() packets in queues: priority=%i, ordinary=%i, mouse=%s", len(self._priority_packets), len(self._ordinary_packets), bool(self._mouse_position))
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
        FilePrintMixin.cleanup(self)
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
        if PYTHON3:
            import gi
            if gi.version_info>=(3, 11):
                #no longer need to call threads_init
                return
        from xpra.gtk_common.gobject_compat import import_glib
        glib = import_glib()
        glib.threads_init()

    def run(self):
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
        reason = bytestostr(packet[1])
        info = packet[2:]
        s = nonl(reason)
        if len(info):
            s += " (%s)" % csv(nonl(bytestostr(x)) for x in info)
        if self.server_capabilities is None or len(self.server_capabilities)==0:
            #server never sent hello to us - so disconnect is an error
            #(but we don't know which one - the info message may help)
            log.warn("server failure: disconnected before the session could be established")
            e = EXIT_FAILURE
        elif disconnect_is_an_error(reason):
            log.warn("server failure: %s", reason)
            e = EXIT_FAILURE
        else:
            if self.exit_code is None:
                #we're not in the process of exiting already,
                #tell the user why the server is disconnecting us
                log.info("server requested disconnect:")
                log.info(" %s", s)
            self.quit(EXIT_OK)
            return
        self.warn_and_quit(e, "server requested disconnect: %s" % s)

    def _process_connection_lost(self, _packet):
        p = self._protocol
        if p and p.input_raw_packetcount==0:
            props = p.get_info()
            c = props.get("compression", "unknown")
            e = props.get("encoder", "unknown")
            netlog.error("Error: failed to receive anything, not an xpra server?")
            netlog.error("  could also be the wrong protocol, username, password or port")
            if c!="unknown" or e!="unknown":
                netlog.error("  or maybe this server does not support '%s' compression or '%s' packet encoding?", c, e)
        if self.exit_code!=0:
            self.warn_and_quit(EXIT_CONNECTION_LOST, "Connection lost")


    ########################################
    # Authentication
    def _process_challenge(self, packet):
        authlog("processing challenge: %s", packet[1:])
        if not self.validate_challenge_packet(packet):
            return
        for name, method in self.challenge_handlers.items():
            try:
                if method(packet):
                    return
            except Exception as e:
                authlog("%s(%s)", method, packet, exc_info=True)
                authlog.error("Error in %s challenge handler:", name)
                authlog.error(" %s", e)
                continue
        self.quit(EXIT_PASSWORD_REQUIRED)

    def process_challenge_uri(self, packet):
        if self.password:
            self.send_challenge_reply(packet, self.password)
            #clearing it to allow other modules to process further challenges: 
            self.password = None
            return True
        return False

    def process_challenge_env(self, packet):
        k = "XPRA_PASSWORD"
        password = os.environ.get(k)
        authlog("process_challenge_env() %s=%s", k, obsc(password))
        if password:
            self.send_challenge_reply(packet, password)
            return True
        return False

    def process_challenge_file(self, packet):
        if self.password_index<len(self.password_file):
            password_file = self.password_file[self.password_index]
            self.password_index += 1
            filename = os.path.expanduser(password_file)
            password = load_binary_file(filename)
            authlog("password read from file %i '%s': %s", self.password_index, password_file, obsc(password))
            self.send_challenge_reply(packet, password)
            return True
        return False

    def process_challenge_prompt(self, packet):
        prompt = "password"
        digest = packet[3]
        if digest.startswith(b"gss:") or digest.startswith(b"kerberos:"):
            prompt = "%s token" % (digest.split(b":", 1)[0])
        if len(packet)>=6:
            prompt = std(packet[5])
        return self.do_process_challenge_prompt(packet, prompt)

    def do_process_challenge_prompt(self, packet, prompt="password"):
        authlog("do_process_challenge_prompt() isatty=%s", sys.stdin.isatty())
        if sys.stdin.isatty() and not os.environ.get("MSYSCON"):
            import getpass
            authlog("stdin isatty, using password prompt")
            password = getpass.getpass("%s :" % self.get_challenge_prompt(prompt))
            authlog("password read from tty via getpass: %s", obsc(password))
            self.send_challenge_reply(packet, password)
            return True
        return False

    def process_challenge_kerberos(self, packet):
        digest = packet[3]
        if not digest.startswith(b"kerberos:"):
            authlog("%s is not a kerberos challenge", digest)
            #not a kerberos challenge
            return False
        try:
            if WIN32:
                import winkerberos as kerberos
            else:
                import kerberos
        except ImportError as e:
            if first_time("no-kerberos"):
                authlog.warn("Warning: kerberos challenge handler is not supported:")
                authlog.warn(" %s", e)
            return False
        service = bytestostr(digest.split(b":", 1)[1])
        if service not in KERBEROS_SERVICES and "*" not in KERBEROS_SERVICES:
            authlog.warn("Warning: invalid kerberos request for service '%s'", service)
            authlog.warn(" services supported: %s", csv(KERBEROS_SERVICES))
            return False
        authlog("kerberos service=%s", service)
        r, ctx = kerberos.authGSSClientInit(service)
        if r!=1:
            log.error("Error: kerberos GSS client init failed")
            return False
        try:
            kerberos.authGSSClientStep(ctx, "")
        except Exception as e:
            authlog("kerberos.authGSSClientStep", exc_info=True)
            log.error("Error: kerberos client authentication failure:")
            try:
                for x in e.args:
                    try:
                        log.error(" %s", csv(x))
                    except:
                        log.error(" %s", x)
            except Exception as e:
                log.error(" %s", e)
                #log.error(" %s", dir(e))
            return False
        token = kerberos.authGSSClientResponse(ctx)
        authlog("kerberos token=%s", token)
        self.send_challenge_reply(packet, token)
        return True

    def process_challenge_gss(self, packet):
        digest = packet[3]
        if not digest.startswith(b"gss:"):
            #not a gss challenge
            authlog("%s is not a gss challenge", digest)
            return False
        try:
            import gssapi
        except ImportError as e:
            if first_time("no-kerberos"):
                log.warn("Warning: gss authentication not supported:")
                log.warn(" %s", e)
            return False
        service = bytestostr(digest.split(b":", 1)[1])
        if service not in GSS_SERVICES and "*" not in GSS_SERVICES:
            authlog.warn("Warning: invalid GSS request for service '%s'", service)
            authlog.warn(" services supported: %s", csv(GSS_SERVICES))
            return False
        authlog("gss service=%s", service)
        service_name = gssapi.Name(service)
        try:
            ctx = gssapi.SecurityContext(name=service_name, usage="initiate")
            token = ctx.step()
        except Exception as e:
            authlog("gssapi failure", exc_info=True)
            log.error("Error: gssapi client authentication failure:")
            log.error(" %s", e)
            return False
        authlog("gss token=%s", repr(token))
        self.send_challenge_reply(packet, token)
        return True


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
            elif not encrypted and not ALLOW_UNENCRYPTED_PASSWORDS:
                self.auth_error(EXIT_ENCRYPTION, "server requested '%s' digest, cowardly refusing to use it without encryption" % digest, "invalid digest")
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
            text += " for %s server %s" % (conn.socktype, pretty_socket(conn.remote))
        except:
            pass
        return text

    def send_challenge_reply(self, packet, password):
        if not password:
            if self.password_file:
                self.auth_error(EXIT_PASSWORD_FILE_ERROR, "failed to load password from file%s %s" % (engs(self.password_file), csv(self.password_file)), "no password available")
            else:
                self.auth_error(EXIT_PASSWORD_REQUIRED, "this server requires authentication and no password is available")
            return
        server_salt = bytestostr(packet[1])
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
            self.auth_error(EXIT_UNSUPPORTED, "server requested '%s' digest but it is not supported" % actual_digest, "invalid digest")
            return
        authlog("%s(%s, %s)=%s", actual_digest, repr(password), repr(salt), repr(challenge_response))
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
        self.server_padding_options = caps.strlistget("cipher.padding.options", [DEFAULT_PADDING])
        if not cipher or not cipher_iv:
            self.warn_and_quit(EXIT_ENCRYPTION, "the server does not use or support encryption/password, cannot continue with %s cipher" % self.encryption)
            return False
        if cipher not in ENCRYPTION_CIPHERS:
            self.warn_and_quit(EXIT_ENCRYPTION, "unsupported server cipher: %s, allowed ciphers: %s" % (cipher, csv(ENCRYPTION_CIPHERS)))
            return False
        if padding not in ALL_PADDING_OPTIONS:
            self.warn_and_quit(EXIT_ENCRYPTION, "unsupported server cipher padding: %s, allowed ciphers: %s" % (padding, csv(ALL_PADDING_OPTIONS)))
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
            cryptolog("get_encryption_key() got %i bytes from '%s' environment variable", len(key or ""), XPRA_ENCRYPTION_KEY)
        if not key:
            raise InitExit(1, "no encryption key")
        return key.strip(b"\n\r")

    def _process_hello(self, packet):
        self.remove_packet_handlers("challenge")
        if not self.password_sent and self.has_password():
            self.warn_and_quit(EXIT_NO_AUTHENTICATION, "the server did not request our password")
            return
        try:
            self.server_capabilities = typedict(packet[1])
            netlog("processing hello from server: %s", self.server_capabilities)
            if not self.server_connection_established():
                self.warn_and_quit(EXIT_FAILURE, "failed to establish connection")
        except Exception as e:
            netlog.info("error in hello packet", exc_info=True)
            self.warn_and_quit(EXIT_FAILURE, "error processing hello packet from server: %s" % e)

    def capsget(self, capabilities, key, default):
        v = capabilities.get(strtobytes(key), default)
        if PYTHON3 and type(v)==bytes:
            v = bytestostr(v)
        return v


    def server_connection_established(self):
        netlog("server_connection_established()")
        if not self.parse_encryption_capabilities():
            netlog("server_connection_established() failed encryption capabilities")
            return False
        if not self.parse_server_capabilities():
            netlog("server_connection_established() failed server capabilities")
            return False
        if not self.parse_network_capabilities():
            netlog("server_connection_established() failed network capabilities")
            return False
        #raise packet size if required:
        if self.file_transfer:
            self._protocol.max_packet_size = max(self._protocol.max_packet_size, self.file_size_limit*1024*1024)
        netlog("server_connection_established() adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        self.init_aliases()
        return True


    def parse_server_capabilities(self):
        for c in XpraClientBase.__bases__:
            if not c.parse_server_capabilities(self):
                return False
        self.server_client_shutdown = self.server_capabilities.boolget("client-shutdown", True)
        return True

    def parse_network_capabilities(self):
        c = self.server_capabilities
        p = self._protocol
        if not p or not p.enable_encoder_from_caps(c):
            return False
        p.enable_compressor_from_caps(c)
        p.accept()
        p.send_aliases = c.dictget("aliases", {})
        return True

    def parse_encryption_capabilities(self):
        c = self.server_capabilities
        p = self._protocol
        if not p:
            return False
        if self.encryption:
            #server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(c, key):
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
        log("process_gibberish(%s)", repr_ellipsized(packet))
        (_, message, data) = packet
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
            netlog.error(" packet no %i data: %s", p.input_packetcount, repr_ellipsized(data))
        self.quit(EXIT_PACKET_FAILURE)

    def _process_invalid(self, packet):
        (_, message, data) = packet
        netlog.info("Received invalid packet: %s", message)
        netlog(" data: %s", repr_ellipsized(data))
        self.quit(EXIT_PACKET_FAILURE)


    def process_packet(self, _proto, packet):
        try:
            handler = None
            packet_type = packet[0]
            if packet_type!=int:
                packet_type = bytestostr(packet_type)
            handler = self._packet_handlers.get(packet_type)
            if handler:
                handler(packet)
                return
            handler = self._ui_packet_handlers.get(packet_type)
            if not handler:
                netlog.error("unknown packet type: %s", packet_type)
                return
            self.idle_add(handler, packet)
        except KeyboardInterrupt:
            raise
        except:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
