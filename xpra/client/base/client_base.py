# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import uuid
import signal
import socket
import string
from time import monotonic
from typing import Dict, Any, Callable

from xpra.log import Logger
from xpra.scripts.config import InitExit
from xpra.common import SPLASH_EXIT_DELAY, FULL_INFO, LOG_HELLO
from xpra.child_reaper import getChildReaper, reaper_cleanup
from xpra.net import compression
from xpra.net.common import (
    may_log_packet,
    PACKET_TYPES, SSL_UPGRADE,
    PacketHandlerType, PacketType,
)
from xpra.make_thread import start_thread
from xpra.net.protocol.factory import get_client_protocol_class
from xpra.net.protocol.constants import CONNECTION_LOST, GIBBERISH, INVALID
from xpra.net.net_util import get_network_caps
from xpra.net.digest import get_salt, gendigest
from xpra.net.crypto import (
    crypto_backend_init, get_iterations, get_iv, choose_padding,
    get_ciphers, get_modes, get_key_hashes,
    ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT,
    DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS, PADDING_OPTIONS,
    DEFAULT_MODE, DEFAULT_KEYSIZE, DEFAULT_KEY_HASH, DEFAULT_KEY_STRETCH,
    )
from xpra.version_util import get_version_info, vparts, XPRA_VERSION
from xpra.platform.info import get_name, get_username
from xpra.os_util import (
    get_machine_id, get_user_uuid, register_SIGUSR_signals,
    filedata_nocrlf, force_quit,
    SIGNAMES, BITS,
    strtobytes, bytestostr, hexstr, use_gui_prompt,
    parse_encoded_bin_data,
    )
from xpra.util import (
    flatten_dict, typedict, updict, parse_simple_dict, noerr, std,
    repr_ellipsized, ellipsizer, nonl, print_nested_dict,
    envbool, envint, disconnect_is_an_error, dump_all_frames, csv, obsc,
    stderr_print,
    ConnectionMessage,
    )
from xpra.client.base.serverinfo_mixin import ServerInfoMixin
from xpra.client.base.fileprint_mixin import FilePrintMixin
from xpra.exit_codes import ExitCode, exit_str

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
LEGACY_SALT_DIGEST = envbool("XPRA_LEGACY_SALT_DIGEST", False)
MOUSE_DELAY = envint("XPRA_MOUSE_DELAY", 0)
SPLASH_LOG = envbool("XPRA_SPLASH_LOG", False)
LOG_DISCONNECT = envbool("XPRA_LOG_DISCONNECT", True)
SKIP_UI = envbool("XPRA_SKIP_UI", False)
LEGACY_PACKET_TYPES = envbool("XPRA_LEGACY_PACKET_TYPES", False)

ALL_CHALLENGE_HANDLERS = os.environ.get("XPRA_ALL_CHALLENGE_HANDLERS",
                                        "uri,file,env,kerberos,gss,u2f,prompt,prompt,prompt,prompt").split(",")


class XpraClientBase(ServerInfoMixin, FilePrintMixin):
    """
    Base class for Xpra clients.
    Provides the glue code for:
    * sending packets via Protocol
    * handling packets received via _process_packet
    For an actual implementation, look at:
    * GObjectXpraClient
    * xpra.client.gtk3.client
    """

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
            log(f" {k}={v!r}")
        #client state:
        self.exit_code = None
        self.exit_on_signal = False
        self.display_desc = {}
        self.progress_process = None
        self.progress_timer = 0
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
        self._pointer_sequence = {}
        self._mouse_position = None
        self._mouse_position_pending = None
        self._mouse_position_send_time = 0
        self._mouse_position_delay = MOUSE_DELAY
        self._mouse_position_timer = 0
        self._aliases = {}
        #server state and caps:
        self.server_packet_types = ()
        self.connection_established = False
        self.completed_startup = False
        self.uuid = get_user_uuid()
        self.session_id = uuid.uuid4().hex
        self.init_packet_handlers()
        def noop():
            """
            until we hook up the real protocol instance,
            do nothing when have_more() is called
            """
        self.have_more = noop

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
        self.encryption_keyfile = opts.encryption_keyfile or opts.tcp_encryption_keyfile
        self.init_challenge_handlers(opts.challenge_handlers)
        self.install_signal_handlers()
        #we need this to expose the 'packet-types' capability,
        self.init_aliases()


    def show_progress(self, pct, text=""):
        log(f"progress({pct}, {text!r})")
        if SPLASH_LOG:
            log.info(f"{pct:3} {text}")
        pp = self.progress_process
        if not pp:
            return
        if pp.poll():
            self.progress_process = None
            return
        noerr(pp.stdin.write, f"{pct}:{text}\n".encode("latin1"))
        noerr(pp.stdin.flush)
        if pct==100:
            #it should exit on its own, but just in case:
            #kill it if it's still running after 2 seconds
            self.cancel_progress_timer()
            def stop_progress():
                self.progress_timer = 0
                self.stop_progress_process()
            self.progress_timer = self.timeout_add(SPLASH_EXIT_DELAY*1000+500, stop_progress)

    def cancel_progress_timer(self):
        pt = self.progress_timer
        if pt:
            self.progress_timer = 0
            self.source_remove(pt)


    def init_challenge_handlers(self, challenge_handlers):
        #register the authentication challenge handlers:
        authlog(f"init_challenge_handlers({challenge_handlers})")
        ch = tuple(x.strip() for x in (challenge_handlers or "".split(",")))
        for ch_name in ch:
            if ch_name=="none":
                continue
            if ch_name=="all":
                items = ALL_CHALLENGE_HANDLERS
                ierror = authlog
            else:
                items = (ch_name, )
                ierror = authlog.warn
            for auth in items:
                instance = self.get_challenge_handler(auth, ierror)
                if instance:
                    self.challenge_handlers.append(instance)
        if DETECT_LEAKS:
            from xpra.util import detect_leaks  # pylint: disable=import-outside-toplevel
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
        auth_mod_name = f"xpra.client.auth.{mod_name}_handler"
        authlog(f"auth module name for {auth!r}: {auth_mod_name!r}")
        try:
            auth_module = __import__(auth_mod_name, {}, {}, ["Handler"])
            auth_class = auth_module.Handler
            instance = auth_class(self, **kwargs)
            return instance
        except ImportError as e:
            import_error_logger(f"Error: authentication handler {mod_name!r} is not available")
            import_error_logger(f" {e}")
        except Exception as e:
            authlog("get_challenge_handler(%s)", auth, exc_info=True)
            authlog.error("Error: cannot instantiate authentication handler")
            authlog.error(f" {mod_name!r}: {e}")
        return None


    def may_notify(self, nid:int, summary:str, body:str, *args, **kwargs):
        notifylog = Logger("notify")
        notifylog("may_notify(%s, %s, %s, %s, %s)", nid, summary, body, args, kwargs)
        notifylog.info("%s", summary)
        if body:
            for x in body.splitlines():
                notifylog.info(" %s", x)


    def handle_deadly_signal(self, signum:int, _frame=None):
        stderr_print("\ngot deadly signal %s, exiting" % SIGNAMES.get(signum, signum))
        self.cleanup()
        force_quit(128 + signum)

    def handle_app_signal(self, signum:int, _frame=None):
        try:
            log.info("exiting")
        except Exception:
            pass
        signal.signal(signal.SIGINT, self.handle_deadly_signal)
        signal.signal(signal.SIGTERM, self.handle_deadly_signal)
        self.signal_cleanup()
        reason = "exit on signal %s" % SIGNAMES.get(signum, signum)
        self.timeout_add(0, self.signal_disconnect_and_quit, 128 + signum, reason)

    def install_signal_handlers(self) -> None:
        def os_signal(signum, _frame=None):
            if self.exit_code is None:
                try:
                    stderr_print()
                    log.info("client got signal %s", SIGNAMES.get(signum, signum))
                except Exception:
                    pass
            self.handle_app_signal(signum)
        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        register_SIGUSR_signals(self.idle_add)

    def signal_disconnect_and_quit(self, exit_code:int, reason:str) -> None:
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

    def signal_cleanup(self) -> None:
        #placeholder for stuff that can be cleaned up from the signal handler
        #(non UI thread stuff)
        pass

    def disconnect_and_quit(self, exit_code:int, reason:str) -> None:
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

    def exit(self) -> None:
        log("XpraClientBase.exit() calling %s", sys.exit)
        sys.exit()


    def client_type(self) -> str:
        #overridden in subclasses!
        return "Python"

    def get_scheduler(self):
        raise NotImplementedError()

    def setup_connection(self, conn):
        protocol_class = get_client_protocol_class(conn.socktype)
        netlog("setup_connection(%s) timeout=%s, socktype=%s, protocol-class=%s",
               conn, conn.timeout, conn.socktype, protocol_class)
        protocol = protocol_class(self.get_scheduler(), conn, self.process_packet, self.next_packet)
        #ssh channel may contain garbage initially,
        #tell the protocol to wait for a valid header:
        protocol.wait_for_header = conn.socktype=="ssh"
        self._protocol = protocol
        if protocol.TYPE!="rfb":
            for x in ("keymap-changed", "server-settings", "logging", "input-devices"):
                protocol.large_packets.append(x)
            protocol.set_compression_level(10)
            protocol.set_receive_aliases(self._aliases)
            protocol.enable_default_encoder()
            protocol.enable_default_compressor()
            encryption = self.get_encryption()
            if encryption and ENCRYPT_FIRST_PACKET:
                key = self.get_encryption_key()
                protocol.set_cipher_out(encryption,
                                        DEFAULT_IV, key, DEFAULT_SALT,
                                        DEFAULT_KEY_HASH, DEFAULT_KEYSIZE, DEFAULT_ITERATIONS, INITIAL_PADDING)
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

    def init_aliases(self) -> None:
        i = 1
        for key in PACKET_TYPES:
            self._aliases[i] = key
            i += 1

    def has_password(self) -> bool:
        return self.password or self.password_file or os.environ.get('XPRA_PASSWORD')

    def send_hello(self, challenge_response=None, client_salt=None) -> None:
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
            hello.setdefault("wants", []).append("packet-types")
        except InitExit as e:
            log.error("error preparing connection:")
            log.estr(e)
            self.quit(ExitCode.INTERNAL_ERROR)
            return
        except Exception as e:
            log.error("error preparing connection: %s", e, exc_info=True)
            self.quit(ExitCode.INTERNAL_ERROR)
            return
        if challenge_response:
            hello["challenge_response"] = challenge_response
            #make it harder for a passive attacker to guess the password length
            #by observing packet sizes (only relevant for wss and ssl)
            hello["challenge_padding"] = get_salt(max(32, 512-len(challenge_response)))
            if client_salt:
                hello["challenge_client_salt"] = client_salt
        log("send_hello(%s) packet=%s", hexstr(challenge_response or ""), hello)
        if LOG_HELLO:
            netlog.info("sending hello:")
            print_nested_dict(hello, print_fn=netlog.info)
        self.send("hello", hello)

    def verify_connected(self) -> None:
        if not self.connection_established:
            #server has not said hello yet
            self.warn_and_quit(ExitCode.TIMEOUT, "connection timed out")


    def make_hello_base(self) -> Dict[str,Any]:
        capabilities = flatten_dict(get_network_caps(FULL_INFO))
        #add "kerberos", "gss" and "u2f" digests if enabled:
        for handler in self.challenge_handlers:
            digest = handler.get_digest()
            if digest:
                digests = capabilities.setdefault("digest", [])
                if digest not in digests:
                    digests.append(digest)
        capabilities.update(FilePrintMixin.get_caps(self))
        if self.username:
            #set for authentication:
            capabilities["username"] = self.username
        capabilities.update({
                "uuid"                  : self.uuid,
                "compression_level"     : self.compression_level,
                "version"               : vparts(XPRA_VERSION, FULL_INFO+1),
                "packet-types"          : tuple(self._aliases.values()),
                })
        if self.display:
            capabilities["display"] = self.display
        if FULL_INFO>0:
            capabilities.update({
                "client_type"           : self.client_type(),
                "session-id"            : self.session_id,
                })
        if FULL_INFO>1:
            capabilities.update({
                "python.version"        : sys.version_info[:3],
                "python.bits"           : BITS,
                "hostname"              : socket.gethostname(),
                "user"                  : get_username(),
                "name"                  : get_name(),
                "argv"                  : sys.argv,
                })
        capabilities.update(self.get_file_transfer_features())
        def up(prefix, d):
            updict(capabilities, prefix, d)
        vi = self.get_version_info()
        capabilities["build"] = vi
        #legacy format:
        up("build", vi)
        mid = get_machine_id()
        if mid:
            capabilities["machine_id"] = mid
        cipher_caps = self.get_cipher_caps()
        if cipher_caps:
            up("cipher", cipher_caps)
            cipher_caps["cipher"] = cipher_caps.pop("")
            capabilities["encryption"] = cipher_caps
        capabilities.update(self.hello_extra)
        return capabilities

    def get_cipher_caps(self) -> Dict[str,Any]:
        encryption = self.get_encryption()
        cryptolog(f"encryption={encryption}")
        if not encryption:
            return {}
        crypto_backend_init()
        enc, mode = (encryption+"-").split("-")[:2]
        if not mode:
            mode = DEFAULT_MODE
        ciphers = get_ciphers()
        if enc not in ciphers:
            raise ValueError(f"invalid encryption {enc!r}, options: {csv(ciphers) or 'none'}")
        modes = get_modes()
        if mode not in modes:
            raise ValueError(f"invalid encryption mode {mode!r}, options: {csv(modes) or 'none'}")
        iv = get_iv()
        key_salt = get_salt()
        iterations = get_iterations()
        padding = choose_padding(self.server_padding_options)
        cipher_caps : Dict[str,Any] = {
            ""                      : enc,
            "cipher"                : enc,
            "mode"                  : mode,
            "iv"                    : iv,
            "key_salt"              : key_salt,
            "key_size"              : DEFAULT_KEYSIZE,
            "key_hash"              : DEFAULT_KEY_HASH,
            "key_stretch"           : DEFAULT_KEY_STRETCH,
            "key_stretch_iterations": iterations,
            "padding"               : padding,
            "padding.options"       : PADDING_OPTIONS,
            }
        cryptolog(f"cipher_caps={cipher_caps}")
        key = self.get_encryption_key()
        self._protocol.set_cipher_in(encryption, iv, key,
                                     key_salt, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE, iterations, padding)
        return cipher_caps


    def get_version_info(self) -> Dict[str, Any]:
        return get_version_info(FULL_INFO)

    def make_hello(self) -> Dict[str,Any]:
        return {"aliases" : self.get_network_aliases()}

    def get_network_aliases(self):
        return dict((v,k) for k,v in self._aliases.items())


    def compressed_wrapper(self, datatype, data, level=5, **kwargs) -> compression.Compressed:
        if level>0 and len(data)>=256:
            kw = {}
            #brotli is not enabled by default as a generic compressor
            #but callers may choose to enable it via kwargs:
            for algo, defval in {
                "zlib" : True,
                "lz4" : True,
                "brotli" : False,
                }.items():
                kw[algo] = algo in self.server_compressors and compression.use(algo) and kwargs.get(algo, defval)
            cw = compression.compressed_wrapper(datatype, data, level=level, can_inline=False, **kw)
            if len(cw)<len(data):
                #the compressed version is smaller, use it:
                return cw
        #we can't compress, so at least avoid warnings in the protocol layer:
        return compression.Compressed(f"raw {datatype}", data, can_inline=True)


    def send(self, *parts) -> None:
        self._ordinary_packets.append(parts)
        self.have_more()

    def send_now(self, *parts) -> None:
        self._priority_packets.append(parts)
        self.have_more()

    def send_positional(self, packet) -> None:
        #packets that include the mouse position in them
        #we can cancel the pending position packets
        self._ordinary_packets.append(packet)
        self._mouse_position = None
        self._mouse_position_pending = None
        self.cancel_send_mouse_position_timer()
        self.have_more()

    def next_pointer_sequence(self, device_id:int) -> int:
        if device_id<0:
            #unspecified device, don't bother with sequence numbers
            return 0
        seq = self._pointer_sequence.get(device_id, 0)+1
        self._pointer_sequence[device_id] = seq
        return seq

    def send_mouse_position(self, device_id, wid, pos, modifiers=None, buttons=None, props=None) -> None:
        if "pointer" in self.server_packet_types:
            #v5 packet type, most attributes are optional:
            attrs = props or {}
            if modifiers is not None:
                attrs["modifiers"] = modifiers
            if buttons is not None:
                attrs["buttons"] = buttons
            seq = self.next_pointer_sequence(device_id)
            packet = ("pointer", device_id, seq, wid, pos, attrs)
        else:
            #pre v5 packet format:
            packet = ("pointer-position", wid, pos, modifiers or (), buttons or ())
            if props:
                packet += props.values()
        if self._mouse_position_timer:
            self._mouse_position_pending = packet
            return
        self._mouse_position_pending = packet
        now = monotonic()
        elapsed = int(1000*(now-self._mouse_position_send_time))
        delay = self._mouse_position_delay-elapsed
        mouselog("send_mouse_position(%s) elapsed=%i, delay left=%i", packet, elapsed, delay)
        if delay>0:
            self._mouse_position_timer = self.timeout_add(delay, self.do_send_mouse_position)
        else:
            self.do_send_mouse_position()

    def do_send_mouse_position(self) -> None:
        self._mouse_position_timer = 0
        self._mouse_position_send_time = monotonic()
        self._mouse_position = self._mouse_position_pending
        mouselog("do_send_mouse_position() position=%s", self._mouse_position)
        self.have_more()

    def cancel_send_mouse_position_timer(self) -> None:
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
                (bool(self._priority_packets) or bool(self._ordinary_packets)
                 or self._mouse_position is not None)
        return packet, None, None, None, synchronous, has_more


    def stop_progress_process(self) -> None:
        pp = self.progress_process
        if not pp:
            return
        self.show_progress(100, "closing")
        self.progress_process = None
        if pp.poll() is not None:
            return
        try:
            pp.terminate()
        except Exception:
            pass

    def cleanup(self) -> None:
        self.cancel_progress_timer()
        self.stop_progress_process()
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


    @staticmethod
    def glib_init() -> None:
        #this will take care of calling threads_init if needed:
        from gi.repository import GLib  # @UnresolvedImport
        register_SIGUSR_signals(GLib.idle_add)

    def run(self) -> int:
        self.start_protocol()
        return 0

    def start_protocol(self) -> None:
        #protocol may be None in "listen" mode
        if self._protocol:
            self._protocol.start()

    def quit(self, exit_code:int=0) -> None:
        raise NotImplementedError()

    def warn_and_quit(self, exit_code:int, message:str):
        log.warn(message)
        self.quit(exit_code)


    def send_shutdown_server(self) -> None:
        assert self.server_client_shutdown
        self.send("shutdown-server")

    def _process_disconnect(self, packet : PacketType) -> None:
        #ie: ("disconnect", "version error", "incompatible version")
        netlog("%s", packet)
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

    def server_disconnect_warning(self, reason:str, *extra_info) -> None:
        log.warn("Warning: server connection failure:")
        log.warn(f" {reason}")
        for x in extra_info:
            log.warn(f" {x}")
        if ConnectionMessage.AUTHENTICATION_FAILED in extra_info:
            self.quit(ExitCode.AUTHENTICATION_FAILED)
        elif ConnectionMessage.CONNECTION_ERROR in extra_info or not self.completed_startup:
            self.quit(ExitCode.CONNECTION_FAILED)
        else:
            self.quit(ExitCode.FAILURE)

    def server_disconnect(self, reason:str, *extra_info) -> None:
        self.quit(self.server_disconnect_exit_code(reason, *extra_info))

    def server_disconnect_exit_code(self, reason:str, *extra_info) -> int:
        if self.exit_code is None and (LOG_DISCONNECT or disconnect_is_an_error(reason)):
            l = log.info
        else:
            l = log
        l("server requested disconnect:")
        l(" %s", reason)
        for x in extra_info:
            l(" %s", x)
        if reason==ConnectionMessage.SERVER_UPGRADE:
            return ExitCode.UPGRADE
        if ConnectionMessage.AUTHENTICATION_FAILED in extra_info:
            return ExitCode.AUTHENTICATION_FAILED
        return ExitCode.OK


    def _process_connection_lost(self, _packet : PacketType) -> None:
        p = self._protocol
        if p and p.input_raw_packetcount==0:
            props = p.get_info()
            c = props.get("compression", "unknown")
            e = props.get("encoder", "rencode")
            netlog.error("Error: failed to receive anything, not an xpra server?")
            netlog.error("  could also be the wrong protocol, username, password or port")
            netlog.error("  or the session was not found")
            if c!="unknown" or not e.startswith("rencode"):
                netlog.error("  or maybe this server does not support '%s' compression or '%s' packet encoding?", c, e)
            exit_code = ExitCode.CONNECTION_FAILED
        elif not self.completed_startup:
            exit_code = ExitCode.CONNECTION_FAILED
        else:
            exit_code = ExitCode.CONNECTION_LOST
        if self.exit_code is None:
            msg = exit_str(exit_code).lower().replace("_", " ").replace("connection", "Connection")
            self.warn_and_quit(exit_code, msg)


    def _process_ssl_upgrade(self, packet : PacketType) -> None:
        assert SSL_UPGRADE
        ssl_attrs = typedict(packet[1])
        start_thread(self.ssl_upgrade, "ssl-upgrade", True, args=(ssl_attrs, ))

    def ssl_upgrade(self, ssl_attrs : typedict) -> None:
        # send ssl-upgrade request!
        ssllog = Logger("client", "ssl")
        ssllog(f"ssl-upgrade({ssl_attrs})")
        conn = self._protocol._conn
        socktype = conn.socktype
        new_socktype = {"tcp" : "ssl", "ws" : "wss"}.get(socktype)
        if not new_socktype:
            raise ValueError(f"cannot upgrade {socktype} to ssl")
        log.info(f"upgrading {conn} to {new_socktype}")
        self.send("ssl-upgrade", {})
        from xpra.net.socket_util import ssl_wrap_socket, get_ssl_attributes, ssl_handshake
        overrides = {
            "verify_mode" : "none",
            "check_hostname" : "no",
        }
        overrides.update(conn.options.get("ssl-options", {}))
        ssl_options = get_ssl_attributes(None, False, overrides)
        kwargs = dict((k.replace("-", "_"), v) for k, v in ssl_options.items())
        # wait for the 'ssl-upgrade' packet to be sent...
        # this should be done by watching the IO and formatting threads instead
        import time
        time.sleep(1)
        def read_callback(packet):
            if packet:
                ssllog.error("Error: received another packet during ssl socket upgrade:")
                ssllog.error(" %s", packet)
                self.quit(ExitCode.INTERNAL_ERROR)
        conn = self._protocol.steal_connection(read_callback)
        if not self._protocol.wait_for_io_threads_exit(1):
            log.error("Error: failed to terminate network threads for ssl upgrade")
            self.quit(ExitCode.INTERNAL_ERROR)
            return
        ssl_sock = ssl_wrap_socket(conn._socket, **kwargs)
        ssl_sock = ssl_handshake(ssl_sock)
        authlog("ssl handshake complete")
        from xpra.net.bytestreams import SSLSocketConnection
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint, new_socktype)
        self._protocol = self.setup_connection(ssl_conn)
        self._protocol.start()


    ########################################
    # Authentication
    def _process_challenge(self, packet : PacketType) -> None:
        authlog(f"processing challenge: {packet[1:]}")
        if not self.validate_challenge_packet(packet):
            return
        start_thread(self.do_process_challenge, "call-challenge-handlers", True, (packet, ))

    def do_process_challenge(self, packet : PacketType) -> None:
        digest = bytestostr(packet[3])
        authlog(f"challenge handlers: {self.challenge_handlers}, digest: {digest}")
        while self.challenge_handlers:
            handler = self.pop_challenge_handler(digest)
            try:
                challenge = packet[1]
                digest = bytestostr(packet[3])
                prompt = "password"
                if len(packet)>=6:
                    prompt = std(bytestostr(packet[5]), extras="-,./: '")
                authlog(f"calling challenge handler {handler}")
                value = handler.handle(challenge=challenge, digest=digest, prompt=prompt)
                authlog(f"{handler.handle}({packet})={obsc(value)}")
                if value:
                    self.send_challenge_reply(packet, value)
                    #stop since we have sent the reply
                    return
            except InitExit as e:
                #the handler is telling us to give up
                #(ie: pinentry was cancelled by the user)
                authlog(f"{handler.handle}({packet}) raised {e!r}")
                log.info(f"exiting: {e!r}")
                self.idle_add(self.disconnect_and_quit, e.status, str(e))
                return
            except Exception as e:
                authlog(f"{handler.handle}({packet})", exc_info=True)
                authlog.error(f"Error in {handler} challenge handler:")
                authlog.estr(e)
                continue
        authlog.warn("Warning: failed to connect, authentication required")
        self.idle_add(self.disconnect_and_quit, ExitCode.PASSWORD_REQUIRED, "authentication required")

    def pop_challenge_handler(self, digest=None):
        #find the challenge handler most suitable for this digest type,
        #otherwise take the first one
        digest_type = None if digest is None else digest.split(":")[0]  #ie: "kerberos:value" -> "kerberos"
        index = 0
        for i, handler in enumerate(self.challenge_handlers):
            if handler.get_digest()==digest_type:
                index = i
                break
        return self.challenge_handlers.pop(index)


    #utility method used by some authentication handlers,
    #and overridden in UI client to provide a GUI dialog
    def do_process_challenge_prompt(self, prompt="password"):
        authlog(f"do_process_challenge_prompt({prompt}) use_gui_prompt={use_gui_prompt()}")
        if SKIP_UI:
            return None
        # pylint: disable=import-outside-toplevel
        if not use_gui_prompt():
            import getpass
            authlog("stdin isatty, using password prompt")
            password = getpass.getpass("%s :" % self.get_challenge_prompt(prompt))
            authlog("password read from tty via getpass: %s", obsc(password))
            return password
        from xpra.platform.paths import get_nodock_command
        cmd = get_nodock_command()+["_pass", prompt]
        try:
            from subprocess import Popen, PIPE
            proc = Popen(cmd, stdout=PIPE)
            getChildReaper().add_process(proc, "password-prompt", cmd, True, True)
            out, err = proc.communicate(None, 60)
            authlog("err(%s)=%s", cmd, err)
            password = out.decode()
            return password
        except Exception:
            log("Error: failed to show GUI for password prompt", exc_info=True)
            return None

    def auth_error(self, code, message, server_message=str(ConnectionMessage.AUTHENTICATION_FAILED)):
        authlog.error("Error: authentication failed:")
        authlog.error(f" {message}")
        self.disconnect_and_quit(code, server_message)

    def validate_challenge_packet(self, packet):
        p = self._protocol
        if not p:
            return False
        digest = bytestostr(packet[3]).split(":", 1)[0]
        #don't send XORed password unencrypted:
        if digest in ("xor", "des"):
            encrypted = p.is_sending_encrypted()
            local = self.display_desc.get("local", False)
            authlog(f"{digest} challenge, encrypted={encrypted}, local={local}")
            if local and ALLOW_LOCALHOST_PASSWORDS:
                return True
            if not encrypted and not ALLOW_UNENCRYPTED_PASSWORDS:
                self.auth_error(ExitCode.ENCRYPTION,
                                f"server requested {digest!r} digest, cowardly refusing to use it without encryption",
                                "invalid digest")
                return False
        salt_digest = "xor"
        if len(packet)>=5:
            salt_digest = bytestostr(packet[4])
        if salt_digest in ("xor", "des"):
            if not LEGACY_SALT_DIGEST:
                self.auth_error(ExitCode.INCOMPATIBLE_VERSION, f"server uses legacy salt digest {salt_digest!r}")
                return False
            log.warn(f"Warning: server using legacy support for {salt_digest!r} salt digest")
        return True

    def get_challenge_prompt(self, prompt="password"):
        text = f"Please enter the {prompt}"
        try:
            from xpra.net.bytestreams import pretty_socket  # pylint: disable=import-outside-toplevel
            conn = self._protocol._conn
            text += f",\n connecting to {conn.socktype} server {pretty_socket(conn.remote)}"
        except Exception:
            pass
        return text

    def send_challenge_reply(self, packet, value):
        if not value:
            self.auth_error(ExitCode.PASSWORD_REQUIRED,
                            "this server requires authentication and no password is available")
            return
        encryption = self.get_encryption()
        if encryption:
            assert len(packet)>=3, "challenge does not contain encryption details to use for the response"
            server_cipher = typedict(packet[2])
            key = self.get_encryption_key()
            if not self.set_server_encryption(server_cipher, key):
                return
        #some authentication handlers give us the response and salt,
        #ready to use without needing to use the digest
        #(ie: u2f handler)
        if isinstance(value, (tuple, list)) and len(value)==2:
            self.do_send_challenge_reply(*value)
            return
        password = value
        #all server versions support a client salt,
        #they also tell us which digest to use:
        server_salt = strtobytes(packet[1])
        digest = bytestostr(packet[3])
        actual_digest = digest.split(":", 1)[0]
        if actual_digest=="des":
            salt = client_salt = server_salt
        else:
            l = len(server_salt)
            salt_digest = "xor"
            if len(packet)>=5:
                salt_digest = bytestostr(packet[4])
            if salt_digest=="xor":
                #with xor, we have to match the size
                if l<16:
                    raise ValueError(f"server salt is too short: only {l} bytes, minimum is 16")
                if l>256:
                    raise ValueError(f"server salt is too long: {l} bytes, maximum is 256")
            else:
                #other digest, 32 random bytes is enough:
                l = 32
            client_salt = get_salt(l)
            salt = gendigest(salt_digest, client_salt, server_salt)
            authlog(f"combined {salt_digest} salt({hexstr(server_salt)}, {hexstr(client_salt)})={hexstr(salt)}")

        challenge_response = gendigest(actual_digest, password, salt)
        if not challenge_response:
            log(f"invalid digest module {actual_digest!r}")
            self.auth_error(ExitCode.UNSUPPORTED,
                            f"server requested {actual_digest} digest but it is not supported", "invalid digest")
            return
        authlog(f"{actual_digest}({obsc(password)!r}, {salt!r})={obsc(challenge_response)!r}")
        self.do_send_challenge_reply(challenge_response, client_salt)

    def do_send_challenge_reply(self, challenge_response:bytes, client_salt:bytes):
        self.password_sent = True
        if self._protocol.TYPE=="rfb":
            self._protocol.send_challenge_reply(challenge_response)
            return
        #call send_hello from the UI thread:
        self.idle_add(self.send_hello, challenge_response, client_salt)

    ########################################
    # Encryption
    def set_server_encryption(self, caps, key):
        enc_caps = caps.dictget("encryption")
        if enc_caps:
            #v5, proper namespace
            caps = typedict(enc_caps)
            prefix = ""
        else:
            #legacy string prefix:
            prefix = "cipher."
        cipher = caps.strget("cipher")
        cipher_mode = caps.strget(f"{prefix}mode", DEFAULT_MODE)
        cipher_iv = caps.strget(f"{prefix}iv")
        key_salt = caps.strget(f"{prefix}key_salt")
        key_hash = caps.strget(f"{prefix}key_hash", DEFAULT_KEY_HASH)
        key_size = caps.intget(f"{prefix}key_size", DEFAULT_KEYSIZE)
        key_stretch = caps.strget(f"{prefix}key_stretch", DEFAULT_KEY_STRETCH)
        iterations = caps.intget(f"{prefix}key_stretch_iterations")
        padding = caps.strget(f"{prefix}padding", DEFAULT_PADDING)
        ciphers = get_ciphers()
        key_hashes = get_key_hashes()
        #server may tell us what it supports,
        #either from hello response or from challenge packet:
        self.server_padding_options = caps.strtupleget(f"{prefix}padding.options", (DEFAULT_PADDING,))
        def fail(msg):
            self.warn_and_quit(ExitCode.ENCRYPTION, msg)
            return False
        if key_stretch!="PBKDF2":
            return fail(f"unsupported key stretching {key_stretch}")
        if not cipher or not cipher_iv:
            return fail("the server does not use or support encryption/password, cannot continue")
        if cipher not in ciphers:
            return fail(f"unsupported server cipher: {cipher}, allowed ciphers: {csv(ciphers)}")
        if padding not in ALL_PADDING_OPTIONS:
            return fail(f"unsupported server cipher padding: {padding}, allowed paddings: {csv(ALL_PADDING_OPTIONS)}")
        if key_hash not in key_hashes:
            return fail(f"unsupported key hashing: {key_hash}, allowed algorithms: {csv(key_hashes)}")
        p = self._protocol
        if not p:
            return False
        p.set_cipher_out(cipher+"-"+cipher_mode, cipher_iv, key,
                         key_salt, key_hash, key_size, iterations, padding)
        return True


    def get_encryption(self) -> str:
        p = self._protocol
        if not p:
            return ""
        conn = p._conn
        #prefer the socket option, fallback to "--encryption=" option:
        encryption = conn.options.get("encryption", self.encryption)
        cryptolog(f"get_encryption() connection options encryption={encryption!r}")
        #specifying keyfile or keydata is enough:
        if not encryption and any(conn.options.get(x) for x in ("encryption-keyfile", "keyfile", "keydata")):
            encryption = f"AES-{DEFAULT_MODE}"
            cryptolog(f"found keyfile or keydata attribute, enabling {encryption!r} encryption")
        if not encryption and os.environ.get("XPRA_ENCRYPTION_KEY"):
            encryption = f"AES-{DEFAULT_MODE}"
            cryptolog("found encryption key environment variable, enabling {encryption!r} encryption")
        return encryption

    def get_encryption_key(self) -> bytes:
        conn = self._protocol._conn
        keydata = parse_encoded_bin_data(conn.options.get("keydata", None))
        cryptolog(f"get_encryption_key() connection options keydata={ellipsizer(keydata)}")
        if keydata:
            return keydata
        keyfile = conn.options.get("encryption-keyfile") or conn.options.get("keyfile") or self.encryption_keyfile
        if keyfile:
            if not os.path.isabs(keyfile):
                keyfile = os.path.abspath(keyfile)
            if os.path.exists(keyfile):
                keydata = filedata_nocrlf(keyfile)
                if keydata:
                    cryptolog("get_encryption_key() loaded %i bytes from '%s'",
                          len(keydata or b""), keyfile)
                    return keydata
                cryptolog(f"get_encryption_key() keyfile {keyfile!r} is empty")
            else:
                cryptolog(f"get_encryption_key() file {keyfile!r} does not exist")
        XPRA_ENCRYPTION_KEY = "XPRA_ENCRYPTION_KEY"
        keydata = strtobytes(os.environ.get(XPRA_ENCRYPTION_KEY, ''))
        cryptolog(f"get_encryption_key() got %i bytes from {XPRA_ENCRYPTION_KEY!r} environment variable",
                  len(keydata or ""))
        if keydata:
            return keydata.strip(b"\n\r")
        raise InitExit(ExitCode.ENCRYPTION, "no encryption key")

    def _process_hello(self, packet : PacketType) -> None:
        if LOG_HELLO:
            netlog.info("received hello:")
            print_nested_dict(packet[1], print_fn=netlog.info)
        self.remove_packet_handlers("challenge")
        self.remove_packet_handlers("ssl-upgrade")
        if not self.password_sent and self.has_password():
            p = self._protocol
            if not p or p.TYPE=="xpra":
                self.warn_and_quit(ExitCode.NO_AUTHENTICATION, "the server did not request our password")
                return
        try:
            caps = typedict(packet[1])
            netlog("processing hello from server: %s", ellipsizer(caps))
            if not self.server_connection_established(caps):
                self.warn_and_quit(ExitCode.FAILURE, "failed to establish connection")
            else:
                self.connection_established = True
        except Exception as e:
            netlog.info("error in hello packet", exc_info=True)
            self.warn_and_quit(ExitCode.FAILURE, f"error processing hello packet from server: {e}")


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
        netlog("server_connection_established(..) adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        return True


    def parse_server_capabilities(self, c : typedict) -> bool:
        for bc in XpraClientBase.__bases__:
            if not bc.parse_server_capabilities(self, c):
                log.info(f"server capabilities rejected by {bc}")
                return False
        self.server_client_shutdown = c.boolget("client-shutdown", True)
        self.server_compressors = c.strtupleget("compressors", ("zlib",))
        return True

    def parse_network_capabilities(self, caps : typedict) -> bool:
        p = self._protocol
        if p.TYPE=="rfb":
            return True
        if not p or not p.enable_encoder_from_caps(caps):
            return False
        p.set_compression_level(self.compression_level)
        p.enable_compressor_from_caps(caps)
        p.parse_remote_caps(caps)
        if not LEGACY_PACKET_TYPES:
            self.server_packet_types = caps.strtupleget("packet-types")
        netlog(f"self.server_packet_types={self.server_packet_types}")
        return True

    def parse_encryption_capabilities(self, caps : typedict) -> bool:
        p = self._protocol
        if not p:
            return False
        encryption = self.get_encryption()
        if encryption:
            #server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(caps, key):
                return False
        return True

    def _process_set_deflate(self, packet : PacketType) -> None:
        #legacy, should not be used for anything
        pass

    def _process_startup_complete(self, packet : PacketType) -> None:
        #can be received if we connect with "xpra stop" or other command line client
        #as the server is starting up
        self.completed_startup = packet


    def _process_gibberish(self, packet : PacketType) -> None:
        log("process_gibberish(%s)", ellipsizer(packet))
        message, data = packet[1:3]
        from xpra.net.socket_util import guess_packet_type  #pylint: disable=import-outside-toplevel
        packet_type = guess_packet_type(data)
        p = self._protocol
        exit_code = ExitCode.PACKET_FAILURE
        pcount = p.input_packetcount if p else 0
        data = bytestostr(data).strip("\n\r")
        show_as_text = pcount<=1 and len(data)<128 and all((c in string.printable) or c in "\n\r" for c in data)
        if pcount<=1:
            exit_code = ExitCode.CONNECTION_FAILED
            netlog.error("Error: failed to connect")
        else:
            netlog.error("Error: received an invalid packet")
        if packet_type=="xpra":
            netlog.error(" xpra server bug or mangled packet")
        if packet_type and packet_type!="xpra":
            netlog.error(f" this is a {packet_type!r} packet,")
            netlog.error(" not from an xpra server?")
        else:
            parts = message.split(" read buffer=", 1)
            netlog.error(f" received uninterpretable nonsense: {parts[0]}")
            if len(parts)==2:
                text = bytestostr(parts[1])
                netlog.error(" %s", text)
                show_as_text = not data.startswith(text)
        if show_as_text:
            if data.find("\n")>=0:
                netlog.error(" data:")
                for x in data.split("\n"):
                    netlog.error("  %r", x.split("\0")[0])
            else:
                netlog.error(f" data: {data!r}")
        else:
            netlog.error(f" packet no {pcount} data: {repr_ellipsized(data)}")
        self.quit(exit_code)

    def _process_invalid(self, packet : PacketType) -> None:
        message, data = packet[1:3]
        netlog.info(f"Received invalid packet: {message}")
        netlog(" data: %s", ellipsizer(data))
        p = self._protocol
        exit_code = ExitCode.PACKET_FAILURE
        if not p or p.input_packetcount<=1:
            exit_code = ExitCode.CONNECTION_FAILED
        self.quit(exit_code)


    ######################################################################
    # packets:
    def remove_packet_handlers(self, *keys) -> None:
        for k in keys:
            for d in (self._packet_handlers, self._ui_packet_handlers):
                d.pop(k, None)

    def init_packet_handlers(self) -> None:
        self._packet_handlers : Dict[str,PacketHandlerType] = {}
        self._ui_packet_handlers : Dict[str,PacketHandlerType] = {}
        self.add_packet_handler("hello", self._process_hello, False)
        if SSL_UPGRADE:
            self.add_packet_handler("ssl-upgrade", self._process_ssl_upgrade)
        self.add_packet_handlers({
            "challenge":                self._process_challenge,
            "disconnect":               self._process_disconnect,
            "set_deflate":              self._process_set_deflate,
            "startup-complete":         self._process_startup_complete,
            CONNECTION_LOST:            self._process_connection_lost,
            GIBBERISH:                  self._process_gibberish,
            INVALID:                    self._process_invalid,
            })

    def init_authenticated_packet_handlers(self) -> None:
        FilePrintMixin.init_authenticated_packet_handlers(self)

    def add_packet_handlers(self, defs, main_thread:bool=True) -> None:
        for packet_type, handler in defs.items():
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type:str, handler:Callable, main_thread:bool=True) -> None:
        netlog("add_packet_handler%s", (packet_type, handler, main_thread))
        self.remove_packet_handlers(packet_type)
        if main_thread:
            handlers = self._ui_packet_handlers
        else:
            handlers = self._packet_handlers
        handlers[packet_type] = handler

    def process_packet(self, _proto, packet):
        packet_type = ""
        handler = None
        try:
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
