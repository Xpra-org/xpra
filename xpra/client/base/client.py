# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import uuid
import signal
import socket
import string
from time import monotonic
from typing import Any, NoReturn
from types import FrameType
from importlib import import_module
from collections.abc import Callable

from xpra.scripts.config import InitExit
from xpra.common import (
    FULL_INFO, LOG_HELLO,
    ConnectionMessage, disconnect_is_an_error, noerr, NotificationID, noop,
)
from xpra.util.child_reaper import getChildReaper, reaper_cleanup
from xpra.util.thread import start_thread
from xpra.net import compression
from xpra.net.common import PacketType, PacketElement, SSL_UPGRADE
from xpra.net.glib_handler import GLibPacketHandler
from xpra.net.protocol.factory import get_client_protocol_class
from xpra.net.protocol.constants import CONNECTION_LOST, GIBBERISH, INVALID
from xpra.net.net_util import get_network_caps
from xpra.net.digest import get_salt, gendigest
from xpra.net.crypto import (
    crypto_backend_init, get_iterations, get_iv, choose_padding,
    get_ciphers, get_modes, get_key_hashes,
    ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT, DEFAULT_STREAM,
    DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS, PADDING_OPTIONS,
    DEFAULT_MODE, DEFAULT_KEYSIZE, DEFAULT_KEY_HASH, DEFAULT_KEY_STRETCH, DEFAULT_ALWAYS_PAD,
)
from xpra.util.version import get_version_info, vparts, XPRA_VERSION
from xpra.net.net_util import get_info as get_net_info
from xpra.log import Logger, get_info as get_log_info
from xpra.platform.info import get_name, get_username, get_sys_info
from xpra.os_util import get_machine_id, get_user_uuid, gi_import, BITS
from xpra.util.system import SIGNAMES, register_SIGUSR_signals, get_env_info, get_sysconfig_info
from xpra.util.io import filedata_nocrlf, stderr_print, use_gui_prompt
from xpra.util.pysystem import dump_all_frames, detect_leaks, get_frame_info
from xpra.util.objects import typedict
from xpra.util.str_fn import (
    std, obsc, csv, Ellipsizer, repr_ellipsized, print_nested_dict, strtobytes,
    bytestostr, hexstr,
)
from xpra.util.parsing import parse_simple_dict, parse_encoded_bin_data
from xpra.util.env import envint, envbool
from xpra.client.base.serverinfo import ServerInfoMixin
from xpra.client.base.fileprint import FilePrintMixin
from xpra.exit_codes import ExitCode, ExitValue, exit_str

GLib = gi_import("GLib")

log = Logger("client")
netlog = Logger("network")
authlog = Logger("auth")
mouselog = Logger("mouse")
cryptolog = Logger("crypto")

EXTRA_TIMEOUT = 10
ALLOW_UNENCRYPTED_PASSWORDS = envbool("XPRA_ALLOW_UNENCRYPTED_PASSWORDS", False)
ALLOW_LOCALHOST_PASSWORDS = envbool("XPRA_ALLOW_LOCALHOST_PASSWORDS", True)
DETECT_LEAKS = envbool("XPRA_DETECT_LEAKS", False)
MOUSE_DELAY = envint("XPRA_MOUSE_DELAY", 0)
SPLASH_LOG = envbool("XPRA_SPLASH_LOG", False)
LOG_DISCONNECT = envbool("XPRA_LOG_DISCONNECT", True)
SKIP_UI = envbool("XPRA_SKIP_UI", False)
SYSCONFIG = envbool("XPRA_SYSCONFIG", FULL_INFO > 1)

ALL_CHALLENGE_HANDLERS = os.environ.get("XPRA_ALL_CHALLENGE_HANDLERS",
                                        "uri,file,env,kerberos,gss,u2f,prompt,prompt,prompt,prompt").split(",")


class XpraClientBase(GLibPacketHandler, ServerInfoMixin, FilePrintMixin):
    """
    Base class for Xpra clients.
    Provides the glue code for:
    * sending packets via Protocol
    * handling packets received via _process_packet
    For an actual implementation, look at:
    * GObjectXpraClient
    * xpra.client.bindings.client
    """

    def __init__(self):
        # this may be called more than once,
        # skip doing internal init again:
        if not hasattr(self, "exit_code"):
            GLibPacketHandler.__init__(self)
            self.defaults_init()
            ServerInfoMixin.__init__(self)
            FilePrintMixin.__init__(self)
        self._init_done = False
        self.exit_code = None
        self.start_time = int(monotonic())

    def defaults_init(self) -> None:
        # skip warning when running the client
        from xpra.util import child_reaper
        child_reaper.POLL_WARNING = False
        getChildReaper()
        log("XpraClientBase.defaults_init() os.environ:")
        for k, v in os.environ.items():
            log(f" {k}={v!r}")
        # client state:
        self.exit_code: int | ExitCode | None = None
        self.exit_on_signal = False
        self.display_desc = {}
        self.progress_process = None
        # connection attributes:
        self.hello_extra = {}
        self.compression_level = 0
        self.display = None
        self.challenge_handlers_option = ()
        self.challenge_handlers = []
        self.username = None
        self.password = None
        self.password_file: list[str] = []
        self.password_index = 0
        self.password_sent = False
        self.encryption = None
        self.encryption_keyfile = None
        self.server_padding_options = [DEFAULT_PADDING]
        self.server_client_shutdown = True
        self.server_compressors = []
        # protocol stuff:
        self._protocol = None
        self._priority_packets = []
        self._ordinary_packets = []
        self._pointer_sequence = {}
        self._mouse_position = None
        self._mouse_position_pending = None
        self._mouse_position_send_time = 0
        self._mouse_position_delay = MOUSE_DELAY
        self._mouse_position_timer = 0
        # control channel for requests coming from either a client socket, or the server connection:
        self.control_commands = {}
        # server state and caps:
        self.server_packet_types = ()
        self.connection_established = False
        self.completed_startup = False
        self.uuid: str = get_user_uuid()
        self.session_id: str = uuid.uuid4().hex
        self.init_packet_handlers()
        self.have_more = noop

    def init(self, opts) -> None:
        if self._init_done:
            # the gtk client classes can inherit this method
            # from multiple parents, skip initializing twice
            return
        self._init_done = True
        for c in (ServerInfoMixin, FilePrintMixin):
            c.init(self, opts)
        self.compression_level = opts.compression_level
        self.display = opts.display
        self.username = opts.username
        self.password = opts.password
        self.password_file = opts.password_file
        self.encryption = opts.encryption or opts.tcp_encryption
        self.encryption_keyfile = opts.encryption_keyfile or opts.tcp_encryption_keyfile
        self.challenge_handlers_option = opts.challenge_handlers
        self.install_signal_handlers()

    def show_progress(self, pct: int, text="") -> None:
        pp = self.progress_process
        log(f"progress({pct}, {text!r}) progress process={pp}")
        if SPLASH_LOG:
            log.info(f"{pct:3} {text}")
        if pp:
            pp.progress(pct, text)

    def init_challenge_handlers(self) -> None:
        # register the authentication challenge handlers:
        authlog("init_challenge_handlers() %r", self.challenge_handlers_option)
        ch = tuple(x.strip() for x in (self.challenge_handlers_option or ()))
        for ch_name in ch:
            if ch_name == "none":
                continue
            if ch_name == "all":
                items = ALL_CHALLENGE_HANDLERS
                ierror = authlog.debug
            else:
                items = (ch_name,)
                ierror = authlog.warn
            for auth in items:
                instance = self.get_challenge_handler(auth, ierror)
                if instance:
                    self.challenge_handlers.append(instance)
        authlog("challenge-handlers=%r", self.challenge_handlers)

    def get_challenge_handler(self, auth: str, import_error_logger: Callable):
        # the module may have attributes,
        # ie: file:filename=password.txt
        parts = auth.split(":", 1)
        mod_name = parts[0]
        kwargs: dict[str, Any] = {}
        if len(parts) == 2:
            kwargs = parse_simple_dict(parts[1])
        kwargs["protocol"] = self._protocol
        kwargs["display-desc"] = self.display_desc
        if "password" not in kwargs and self.password:
            kwargs["password"] = self.password
        if self.password_file:
            kwargs["password-files"] = self.password_file
        kwargs["challenge_prompt_function"] = self.do_process_challenge_prompt

        auth_mod_name = f"xpra.challenge.{mod_name}"
        authlog(f"auth module name for {auth!r}: {auth_mod_name!r}")
        try:
            auth_module = import_module(auth_mod_name)
            auth_class = auth_module.Handler
            authlog(f"{auth_class}({kwargs})")
            instance = auth_class(**kwargs)
            return instance
        except ImportError as e:
            import_error_logger(f"Error: authentication handler {mod_name!r} is not available")
            import_error_logger(f" {e}")
        except Exception as e:
            authlog("get_challenge_handler(%s)", auth, exc_info=True)
            authlog.error("Error: cannot instantiate authentication handler")
            authlog.error(f" {mod_name!r}: {e}")
        return None

    def may_notify(self, nid: int | NotificationID, summary: str, body: str, *args, **kwargs) -> None:
        notifylog = Logger("notify")
        notifylog("may_notify(%s, %s, %s, %s, %s)", nid, summary, body, args, kwargs)
        notifylog.info("%s", summary)
        if body:
            for x in body.splitlines():
                notifylog.info(" %s", x)
        self.show_progress(100, f"notification: {summary}")

    @staticmethod
    def force_quit(exit_code: ExitValue = ExitCode.FAILURE) -> NoReturn:
        from xpra import os_util
        log(f"force_quit() calling {os_util.force_quit}")
        os_util.force_quit(int(exit_code))

    def handle_deadly_signal(self, signum, _frame: FrameType = None) -> None:
        stderr_print("\ngot deadly signal %s, exiting" % SIGNAMES.get(signum, signum))
        self.cleanup()
        self.force_quit(128 + int(signum))

    def handle_app_signal(self, signum: int, _frame: FrameType = None) -> None:
        # from now on, force quit if we get another signal:
        signal.signal(signal.SIGINT, self.handle_deadly_signal)
        signal.signal(signal.SIGTERM, self.handle_deadly_signal)
        noerr(log.info, "exiting")
        self.signal_cleanup()
        reason = "exit on signal %s" % SIGNAMES.get(signum, signum)
        GLib.timeout_add(0, self.signal_disconnect_and_quit, 128 + signum, reason)

    def install_signal_handlers(self) -> None:

        def os_signal(signum: int | signal.Signals, _frame: FrameType | None = None) -> None:
            if self.exit_code is None:
                try:
                    stderr_print()
                    log.info("client got signal %s", SIGNAMES.get(signum, signum))
                except IOError:
                    pass
            self.handle_app_signal(int(signum))

        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        register_SIGUSR_signals(GLib.idle_add)

    # noinspection PyUnreachableCode
    def signal_disconnect_and_quit(self, exit_code: ExitValue, reason: str) -> None:
        log("signal_disconnect_and_quit(%s, %s) exit_on_signal=%s", exit_code, reason, self.exit_on_signal)
        if not self.exit_on_signal:
            # if we get another signal, we'll try to exit without idle_add...
            self.exit_on_signal = True
            GLib.idle_add(self.disconnect_and_quit, exit_code, reason)
            GLib.idle_add(self.quit, exit_code)
            GLib.idle_add(self.exit)
            return
        # warning: this will run cleanup code from the signal handler
        self.disconnect_and_quit(exit_code, reason)
        self.quit(exit_code)
        self.exit()
        self.force_quit(int(exit_code))

    def signal_cleanup(self) -> None:
        # placeholder for stuff that can be cleaned up from the signal handler
        # (non UI thread stuff)
        pass

    def disconnect_and_quit(self, exit_code: ExitValue, reason: str | ConnectionMessage) -> None:
        # make sure that we set the exit code early,
        # so the protocol shutdown won't set a different one:
        if self.exit_code is None:
            self.exit_code = exit_code
        # try to tell the server we're going, then quit
        log("disconnect_and_quit(%s, %s)", exit_code, reason)
        p = self._protocol
        if p is None or p.is_closed():
            self.quit(exit_code)
            return

        def protocol_closed() -> None:
            log("disconnect_and_quit: protocol_closed()")
            GLib.idle_add(self.quit, exit_code)

        if p:
            p.send_disconnect([str(reason)], done_callback=protocol_closed)
        GLib.timeout_add(1000, self.quit, exit_code)

    def exit(self) -> None:
        log("XpraClientBase.exit() calling %s", sys.exit)
        sys.exit()

    def client_type(self) -> str:
        # overridden in subclasses!
        return "Python"

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {}
        if FULL_INFO > 0:
            info |= {
                "pid": os.getpid(),
                "sys": get_sys_info(),
                "network": get_net_info(),
                "logging": get_log_info(),
                "threads": get_frame_info(),
                "env": get_env_info(),
                "endpoint": self.get_connection_endpoint(),
            }
        if SYSCONFIG:
            info["sysconfig"] = get_sysconfig_info()
        return info

    def make_protocol(self, conn):
        if not conn:
            raise ValueError("no connection")
        protocol_class = get_client_protocol_class(conn.socktype)
        netlog("setup_connection(%s) timeout=%s, socktype=%s, protocol-class=%s",
               conn, conn.timeout, conn.socktype, protocol_class)
        protocol = protocol_class(conn, self.process_packet, self.next_packet)
        self._protocol = protocol
        if protocol.TYPE != "rfb":
            for x in ("keymap-changed", "server-settings", "logging", "input-devices"):
                protocol.large_packets.append(x)
            protocol.set_compression_level(1)
            protocol.enable_default_encoder()
            protocol.enable_default_compressor()
            encryption = self.get_encryption()
            if encryption and ENCRYPT_FIRST_PACKET:
                key = self.get_encryption_key()
                protocol.set_cipher_out(encryption, strtobytes(DEFAULT_IV),
                                        key, DEFAULT_SALT, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
                                        DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_ALWAYS_PAD, DEFAULT_STREAM)
        self.have_more = protocol.source_has_more
        if conn.timeout > 0:
            GLib.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)
        process = getattr(conn, "process", None)  # ie: ssh is handled by another process
        if process:
            proc, name, command = process
            if proc:
                getChildReaper().add_process(proc, name, command, ignore=True, forget=False)
        netlog("setup_connection(%s) protocol=%s", conn, protocol)
        self.setup_connection(conn)
        return protocol

    def setup_connection(self, conn) -> None:
        self.init_challenge_handlers()

    def has_password(self) -> bool:
        return self.password or self.password_file or os.environ.get('XPRA_PASSWORD')

    def send_hello(self, challenge_response=b"", client_salt=b"") -> None:
        if not self._protocol:
            log("send_hello(..) skipped, no protocol (listen mode?)")
            return
        try:
            hello = self.make_hello_base()
            if self.has_password() and not challenge_response:
                # avoid sending the full hello: tell the server we want
                # a packet challenge first
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
            # make it harder for a passive attacker to guess the password length
            # by observing packet sizes (only relevant for wss and ssl)
            hello["challenge_padding"] = get_salt(max(32, 512 - len(challenge_response)))
            if client_salt:
                hello["challenge_client_salt"] = client_salt
        log("send_hello(%s) packet=%s", hexstr(challenge_response or ""), hello)
        if LOG_HELLO:
            netlog.info("sending hello:")
            print_nested_dict(hello, print_fn=netlog.info)
        self.send("hello", hello)

    def verify_connected(self) -> None:
        if not self.connection_established:
            # server has not said hello yet
            self.warn_and_quit(ExitCode.TIMEOUT, "connection timed out")

    def make_hello_base(self) -> dict[str, Any]:
        capabilities = get_network_caps(FULL_INFO)
        # add "kerberos", "gss" and "u2f" digests if enabled:
        for handler in self.challenge_handlers:
            digest = handler.get_digest()
            if digest:
                digests = capabilities.setdefault("digest", ())
                if digest not in digests:
                    capabilities["digest"] = tuple(list(digests)+[digest])
        capabilities.update(FilePrintMixin.get_caps(self))
        # set for authentication:
        capabilities["username"] = self.username or get_username()
        capabilities |= {
            "uuid": self.uuid,
            "compression_level": self.compression_level,
            "version": vparts(XPRA_VERSION, FULL_INFO + 1),
        }
        if self.display:
            capabilities["display"] = self.display
        if FULL_INFO > 0:
            capabilities |= {
                "client_type": self.client_type(),
                "session-id": self.session_id,
            }
        if FULL_INFO > 1:
            capabilities |= {
                "python.version": sys.version_info[:3],
                "python.bits": BITS,
                "hostname": socket.gethostname(),
                "user": get_username(),
                "name": get_name(),
                "argv": sys.argv,
            }
        capabilities.update(self.get_file_transfer_features())
        vi = self.get_version_info()
        capabilities["build"] = vi
        mid = get_machine_id()
        if mid:
            capabilities["machine_id"] = mid
        cipher_caps = self.get_cipher_caps()
        if cipher_caps:
            capabilities["encryption"] = cipher_caps
        capabilities.update(self.hello_extra)
        return capabilities

    def get_cipher_caps(self) -> dict[str, Any]:
        encryption = self.get_encryption()
        cryptolog(f"encryption={encryption}")
        if not encryption:
            return {}
        crypto_backend_init()
        enc, mode = (encryption + "-").split("-")[:2]
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
        always_pad = DEFAULT_ALWAYS_PAD
        stream = DEFAULT_STREAM
        cipher_caps: dict[str, Any] = {
            "cipher": enc,
            "mode": mode,
            "iv": iv,
            "key_salt": key_salt,
            "key_size": DEFAULT_KEYSIZE,
            "key_hash": DEFAULT_KEY_HASH,
            "key_stretch": DEFAULT_KEY_STRETCH,
            "key_stretch_iterations": iterations,
            "padding": padding,
            "padding.options": PADDING_OPTIONS,
            "always-pad": always_pad,
            "stream": stream,
        }
        cryptolog(f"cipher_caps={cipher_caps}")
        key = self.get_encryption_key()
        self._protocol.set_cipher_in(encryption, strtobytes(iv),
                                     key, key_salt, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
                                     iterations, padding, always_pad, stream)
        return cipher_caps

    @staticmethod
    def get_version_info() -> dict[str, Any]:
        return get_version_info(FULL_INFO)

    def make_hello(self) -> dict[str, Any]:
        return {}

    def compressed_wrapper(self, datatype, data, level=5, **kwargs) -> compression.Compressed:
        if level > 0 and len(data) >= 256:
            kw = {}
            # brotli is not enabled by default as a generic compressor
            # but callers may choose to enable it via kwargs:
            for algo, defval in {
                "lz4": True,
                "brotli": False,
            }.items():
                kw[algo] = algo in self.server_compressors and compression.use(algo) and kwargs.get(algo, defval)
            cw = compression.compressed_wrapper(datatype, data, level=level, can_inline=False, **kw)
            if len(cw) < len(data):
                # the compressed version is smaller, use it:
                return cw
        # we can't compress, so at least avoid warnings in the protocol layer:
        return compression.Compressed(f"raw {datatype}", data)

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        packet = (packet_type, *parts)
        self._ordinary_packets.append(packet)
        self.have_more()

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        packet = (packet_type, *parts)
        self._priority_packets.append(packet)
        self.have_more()

    def send_positional(self, packet_type: str, *parts: PacketElement) -> None:
        # packets that include the mouse position data
        # we can cancel the pending position packets
        packet = (packet_type, *parts)
        self._ordinary_packets.append(packet)
        self._mouse_position = None
        self._mouse_position_pending = None
        self.cancel_send_mouse_position_timer()
        self.have_more()

    def next_pointer_sequence(self, device_id: int) -> int:
        if device_id < 0:
            # unspecified device, don't bother with sequence numbers
            return 0
        seq = self._pointer_sequence.get(device_id, 0) + 1
        self._pointer_sequence[device_id] = seq
        return seq

    def send_mouse_position(self, device_id: int, wid: int, pos, modifiers=None, buttons=None, props=None) -> None:
        if "pointer" in self.server_packet_types:
            # v5 packet type, most attributes are optional:
            attrs = props or {}
            if modifiers is not None:
                attrs["modifiers"] = modifiers
            if buttons is not None:
                attrs["buttons"] = buttons
            seq = self.next_pointer_sequence(device_id)
            packet = ("pointer", device_id, seq, wid, pos, attrs)
        else:
            # pre v5 packet format:
            packet = ("pointer-position", wid, pos, modifiers or (), buttons or ())
            if props:
                packet += props.values()
        if self._mouse_position_timer:
            self._mouse_position_pending = packet
            return
        self._mouse_position_pending = packet
        now = monotonic()
        elapsed = int(1000 * (now - self._mouse_position_send_time))
        delay = self._mouse_position_delay - elapsed
        mouselog("send_mouse_position(%s) elapsed=%i, delay left=%i", packet, elapsed, delay)
        if delay > 0:
            self._mouse_position_timer = GLib.timeout_add(delay, self.do_send_mouse_position)
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
            GLib.source_remove(mpt)

    def next_packet(self) -> tuple[PacketType, bool, bool]:
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
            packet = ("none", )
        has_more = packet is not None and (
            bool(self._priority_packets) or bool(self._ordinary_packets) or self._mouse_position is not None
        )
        return packet, synchronous, has_more

    def stop_progress_process(self, reason="closing") -> None:
        pp = self.progress_process
        if not pp:
            return
        self.show_progress(100, reason)
        self.progress_process = None
        if pp.poll() is not None:
            return
        from subprocess import TimeoutExpired
        try:
            if pp.wait(0.1) is not None:
                return
        except TimeoutExpired:
            pass
        try:
            pp.terminate()
        except OSError:
            pass

    def cleanup(self) -> None:
        self.stop_progress_process()
        reaper_cleanup()
        with log.trap_error("Error cleaning file-print handler"):
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

    @staticmethod
    def glib_init() -> None:
        register_SIGUSR_signals(GLib.idle_add)

    def run(self) -> ExitValue:
        if DETECT_LEAKS:
            print_leaks = detect_leaks()
            GLib.timeout_add(10 * 1000, print_leaks)
        self.start_protocol()
        return 0

    def start_protocol(self) -> None:
        # protocol may be None in "listen" mode
        if self._protocol:
            self._protocol.start()

    def get_connection_endpoint(self) -> str:
        p = self._protocol
        if not p:
            return ""
        conn = getattr(p, "_conn", None)
        if not conn:
            return ""
        from xpra.net.bytestreams import pretty_socket
        cinfo = conn.get_info()
        return pretty_socket(cinfo.get("endpoint", conn.target)).split("?")[0]

    def quit(self, exit_code: ExitValue = 0) -> None:
        raise NotImplementedError()

    def warn_and_quit(self, exit_code: ExitValue, message: str) -> None:
        log.warn(message)
        self.quit(exit_code)

    def send_shutdown_server(self) -> None:
        assert self.server_client_shutdown
        self.send("shutdown-server")

    def _process_disconnect(self, packet: PacketType) -> None:
        # ie: ("disconnect", "version error", "incompatible version")
        netlog("%s", packet)
        info = tuple(str(x) for x in packet[1:])
        reason = info[0]
        if not self.connection_established:
            # server never sent hello to us - so disconnect is an error
            # (but we don't know which one - the info message may help)
            self.server_disconnect_warning("disconnected before the session could be established", *info)
        elif disconnect_is_an_error(reason):
            self.server_disconnect_warning(*info)
        elif self.exit_code is None:
            # we're not in the process of exiting already,
            # tell the user why the server is disconnecting us
            self.server_disconnect(*info)

    def server_disconnect_warning(self, reason: str, *extra_info) -> None:
        log.warn("Warning: server connection failure:")
        log.warn(f" {reason!r}")
        for x in extra_info:
            if str(x).lower() != str(reason).lower():
                log.warn(f" {x!r}")
        if ConnectionMessage.AUTHENTICATION_FAILED.value in extra_info:
            self.quit(ExitCode.AUTHENTICATION_FAILED)
        elif ConnectionMessage.CONNECTION_ERROR.value in extra_info or not self.completed_startup:
            self.quit(ExitCode.CONNECTION_FAILED)
        else:
            self.quit(ExitCode.FAILURE)

    def server_disconnect(self, reason: str, *extra_info) -> None:
        self.quit(self.server_disconnect_exit_code(reason, *extra_info))

    def server_disconnect_exit_code(self, reason: str, *extra_info) -> ExitCode:
        if self.exit_code is None and (LOG_DISCONNECT or disconnect_is_an_error(reason)):
            log_fn = log.info
        else:
            log_fn = log.debug
        log_fn("server requested disconnect:")
        log_fn(" %s", reason)
        for x in extra_info:
            log_fn(" %s", x)
        if reason == ConnectionMessage.SERVER_UPGRADE.value:
            return ExitCode.UPGRADE
        if ConnectionMessage.AUTHENTICATION_FAILED.value in extra_info:
            return ExitCode.AUTHENTICATION_FAILED
        return ExitCode.OK

    def _process_connection_lost(self, _packet: PacketType) -> None:
        p = self._protocol
        if p and p.input_raw_packetcount == 0:
            props = p.get_info()
            c = props.get("compression", "unknown")
            e = props.get("encoder", "rencodeplus")
            netlog.error("Error: failed to receive anything, not an xpra server?")
            netlog.error("  could also be the wrong protocol, username, password or port")
            netlog.error("  or the session was not found")
            if c != "unknown" or not e.startswith("rencode"):
                netlog.error("  or maybe this server does not support '%s' compression or '%s' packet encoding?", c, e)
            exit_code = ExitCode.CONNECTION_FAILED
        elif not self.completed_startup:
            exit_code = ExitCode.CONNECTION_FAILED
        else:
            exit_code = ExitCode.CONNECTION_LOST
        if self.exit_code is None:
            msg = exit_str(exit_code).lower().replace("_", " ").replace("connection", "Connection")
            self.warn_and_quit(exit_code, msg)

    def _process_ssl_upgrade(self, packet: PacketType) -> None:
        assert SSL_UPGRADE
        ssl_attrs = typedict(packet[1])
        start_thread(self.ssl_upgrade, "ssl-upgrade", True, args=(ssl_attrs,))

    def ssl_upgrade(self, ssl_attrs: typedict) -> None:
        # send ssl-upgrade request!
        ssllog = Logger("client", "ssl")
        ssllog(f"ssl-upgrade({ssl_attrs})")
        conn = self._protocol._conn
        socktype = conn.socktype
        new_socktype = {"tcp": "ssl", "ws": "wss"}.get(socktype)
        if not new_socktype:
            raise ValueError(f"cannot upgrade {socktype} to ssl")
        log.info(f"upgrading {conn} to {new_socktype}")
        self.send("ssl-upgrade", {})
        from xpra.net.ssl_util import ssl_handshake, ssl_wrap_socket, get_ssl_attributes
        overrides = {
            "verify_mode": "none",
            "check_hostname": "no",
        }
        overrides.update(conn.options.get("ssl-options", {}))
        ssl_options = get_ssl_attributes(None, False, overrides)
        kwargs = {k.replace("-", "_"): v for k, v in ssl_options.items()}
        # wait for the 'ssl-upgrade' packet to be sent...
        # this should be done by watching the IO and formatting threads instead
        import time
        time.sleep(1)

        def read_callback(packet) -> None:
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
        ssl_handshake(ssl_sock)
        authlog("ssl handshake complete")
        from xpra.net.bytestreams import SSLSocketConnection
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint, new_socktype)
        self._protocol = self.make_protocol(ssl_conn)
        self._protocol.start()

    ########################################
    # Authentication
    def _process_challenge(self, packet: PacketType) -> None:
        authlog(f"processing challenge: {packet[1:]}")
        if not self.validate_challenge_packet(packet):
            return
        start_thread(self.do_process_challenge, "call-challenge-handlers", True, (packet,))

    def do_process_challenge(self, packet: PacketType) -> None:
        digest = str(packet[3])
        authlog(f"challenge handlers: {self.challenge_handlers}, digest: {digest}")
        while self.challenge_handlers:
            handler = self.pop_challenge_handler(digest)
            try:
                challenge = strtobytes(packet[1])
                prompt = "password"
                if len(packet) >= 6:
                    prompt = std(str(packet[5]), extras="-,./: '")
                authlog(f"calling challenge handler {handler}")
                value = handler.handle(challenge=challenge, digest=digest, prompt=prompt)
                authlog(f"{handler.handle}({packet})={obsc(value)}")
                if value:
                    self.send_challenge_reply(packet, value)
                    # stop since we have sent the reply
                    return
            except InitExit as e:
                # the handler is telling us to give up
                # (ie: pinentry was cancelled by the user)
                authlog(f"{handler.handle}({packet}) raised {e!r}")
                log.info(f"exiting: {e}")
                GLib.idle_add(self.disconnect_and_quit, e.status, str(e))
                return
            except Exception as e:
                authlog(f"{handler.handle}({packet})", exc_info=True)
                authlog.error(f"Error in {handler} challenge handler:")
                authlog.estr(e)
                continue
        authlog.warn("Warning: failed to connect, authentication required")
        GLib.idle_add(self.disconnect_and_quit, ExitCode.PASSWORD_REQUIRED, "authentication required")

    def pop_challenge_handler(self, digest: str = ""):
        # find the challenge handler most suitable for this digest type,
        # otherwise take the first one
        digest_type = digest.split(":")[0]  # ie: "kerberos:value" -> "kerberos"
        index = 0
        for i, handler in enumerate(self.challenge_handlers):
            if handler.get_digest() == digest_type:
                index = i
                break
        return self.challenge_handlers.pop(index)

    # utility method used by some authentication handlers,
    # and overridden in UI client to provide a GUI dialog
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
        self.show_progress(100, "challenge prompt")
        from xpra.platform.paths import get_nodock_command
        cmd = get_nodock_command() + ["_pass", prompt]
        try:
            from subprocess import Popen, PIPE
            proc = Popen(cmd, stdout=PIPE)
            getChildReaper().add_process(proc, "password-prompt", cmd, True, True)
            out, err = proc.communicate(None, 60)
            authlog("err(%s)=%s", cmd, err)
            password = out.decode()
            return password
        except OSError:
            log("Error: failed to show GUI for password prompt", exc_info=True)
            return None

    def auth_error(self, code: ExitValue,
                   message: str,
                   server_message: str | ConnectionMessage = ConnectionMessage.AUTHENTICATION_FAILED) -> None:
        authlog.error("Error: authentication failed:")
        authlog.error(f" {message}")
        self.disconnect_and_quit(code, server_message)

    def validate_challenge_packet(self, packet) -> bool:
        p = self._protocol
        if not p:
            return False
        digest = str(packet[3]).split(":", 1)[0]
        # don't send XORed password unencrypted:
        if digest in ("xor", "des"):
            # verify that the connection is already encrypted,
            # or that it will be configured for encryption in `send_challenge_reply`:
            encrypted = p.is_sending_encrypted() or bool(self.get_encryption())
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
        if len(packet) >= 5:
            salt_digest = str(packet[4])
        if salt_digest in ("xor", "des"):
            self.auth_error(ExitCode.INCOMPATIBLE_VERSION, f"server uses legacy salt digest {salt_digest!r}")
            return False
        return True

    def get_challenge_prompt(self, prompt="password") -> str:
        text = f"Please enter the {prompt}"
        try:
            from xpra.net.bytestreams import pretty_socket  # pylint: disable=import-outside-toplevel
            conn = self._protocol._conn
            text += f",\n connecting to {conn.socktype} server {pretty_socket(conn.remote)}"
        except (AttributeError, TypeError):
            pass
        return text

    def send_challenge_reply(self, packet: PacketType, value) -> None:
        if not value:
            self.auth_error(ExitCode.PASSWORD_REQUIRED,
                            "this server requires authentication and no password is available")
            return
        encryption = self.get_encryption()
        if encryption:
            assert len(packet) >= 3, "challenge does not contain encryption details to use for the response"
            server_cipher = typedict(packet[2])
            key = self.get_encryption_key()
            if not self.set_server_encryption(server_cipher, key):
                return
        # some authentication handlers give us the response and salt,
        # ready to use without needing to use the digest
        # (ie: u2f handler)
        if isinstance(value, (tuple, list)) and len(value) == 2:
            self.do_send_challenge_reply(*value)
            return
        password = value
        # all server versions support a client salt,
        # they also tell us which digest to use:
        server_salt = strtobytes(packet[1])
        digest = str(packet[3])
        actual_digest = digest.split(":", 1)[0]
        if actual_digest == "des":
            salt = client_salt = server_salt
        else:
            length = len(server_salt)
            salt_digest = "xor"
            if len(packet) >= 5:
                salt_digest = str(packet[4])
            if salt_digest == "xor":
                # with xor, we have to match the size
                if length < 16:
                    raise ValueError(f"server salt is too short: only {length} bytes, minimum is 16")
                if length > 256:
                    raise ValueError(f"server salt is too long: {length} bytes, maximum is 256")
            else:
                # other digest, 32 random bytes is enough:
                length = 32
            client_salt = get_salt(length)
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

    def do_send_challenge_reply(self, challenge_response: bytes, client_salt: bytes) -> None:
        self.password_sent = True
        if self._protocol.TYPE == "rfb":
            self._protocol.send_challenge_reply(challenge_response)
            return
        # call send_hello from the UI thread:
        GLib.idle_add(self.send_hello, challenge_response, client_salt)

    ########################################
    # Encryption
    def set_server_encryption(self, caps: typedict, key: bytes) -> bool:
        caps = typedict(caps.dictget("encryption") or {})
        cipher = caps.strget("cipher")
        cipher_mode = caps.strget("mode", DEFAULT_MODE)
        cipher_iv = caps.strget("iv")
        key_salt = caps.bytesget("key_salt")
        key_hash = caps.strget("key_hash", DEFAULT_KEY_HASH)
        key_size = caps.intget("key_size", DEFAULT_KEYSIZE)
        key_stretch = caps.strget("key_stretch", DEFAULT_KEY_STRETCH)
        iterations = caps.intget("key_stretch_iterations")
        padding = caps.strget("padding", DEFAULT_PADDING)
        always_pad = caps.boolget("always-pad", DEFAULT_ALWAYS_PAD)
        stream = caps.boolget("stream", DEFAULT_STREAM)
        ciphers = get_ciphers()
        key_hashes = get_key_hashes()
        # server may tell us what it supports,
        # either from hello response or from challenge packet:
        self.server_padding_options = caps.strtupleget("padding.options", (DEFAULT_PADDING,))

        def fail(msg) -> bool:
            self.warn_and_quit(ExitCode.ENCRYPTION, msg)
            return False

        if key_stretch != "PBKDF2":
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
        p.set_cipher_out(cipher + "-" + cipher_mode, strtobytes(cipher_iv),
                         key, key_salt, key_hash, key_size,
                         iterations, padding, always_pad, stream)
        return True

    def get_encryption(self) -> str:
        p = self._protocol
        if not p:
            return ""
        conn = p._conn
        if not conn:
            return ""
        # prefer the socket option, fallback to "--encryption=" option:
        encryption = conn.options.get("encryption", self.encryption)
        cryptolog(f"get_encryption() connection options encryption={encryption!r}")
        # specifying keyfile or keydata is enough:
        if not encryption and any(conn.options.get(x) for x in ("encryption-keyfile", "keyfile", "keydata")):
            encryption = f"AES-{DEFAULT_MODE}"
            cryptolog(f"found keyfile or keydata attribute, enabling {encryption!r} encryption")
        if not encryption and os.environ.get("XPRA_ENCRYPTION_KEY"):
            encryption = f"AES-{DEFAULT_MODE}"
            cryptolog("found encryption key environment variable, enabling {encryption!r} encryption")
        return encryption

    def get_encryption_key(self) -> bytes:
        conn = self._protocol._conn
        keydata = parse_encoded_bin_data(conn.options.get("keydata", ""))
        cryptolog(f"get_encryption_key() connection options keydata={Ellipsizer(keydata)}")
        if keydata:
            return keydata
        keyfile = conn.options.get("encryption-keyfile") or conn.options.get("keyfile") or self.encryption_keyfile
        if keyfile:
            if not os.path.isabs(keyfile):
                keyfile = os.path.abspath(keyfile)
            if os.path.exists(keyfile):
                keydata = filedata_nocrlf(keyfile)
                if keydata:
                    cryptolog("get_encryption_key() loaded %i bytes from '%s'", len(keydata or b""), keyfile)
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

    def _process_hello(self, packet: PacketType) -> None:
        if LOG_HELLO:
            netlog.info("received hello:")
            print_nested_dict(packet[1], print_fn=netlog.info)
        self.remove_packet_handlers("challenge")
        self.remove_packet_handlers("ssl-upgrade")
        if not self.password_sent and self.has_password():
            p = self._protocol
            if not p or p.TYPE == "xpra":
                self.warn_and_quit(ExitCode.NO_AUTHENTICATION, "the server did not request our password")
                return
        try:
            caps = typedict(packet[1])
            netlog("processing hello from server: %s", Ellipsizer(caps))
            if not self.server_connection_established(caps):
                self.warn_and_quit(ExitCode.FAILURE, "failed to establish connection")
            else:
                self.connection_established = True
        except Exception as e:
            netlog.error("Error processing hello packet from server", exc_info=True)
            netlog("hello data: %s", packet)
            self.warn_and_quit(ExitCode.FAILURE, f"error processing hello packet from server: {e}")

    def server_connection_established(self, caps: typedict) -> bool:
        assert caps and self._protocol
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
        self.add_control_commands()
        return True

    def parse_server_capabilities(self, c: typedict) -> bool:
        netlog("parse_server_capabilities(..)")
        for bc in (ServerInfoMixin, FilePrintMixin):
            if not bc.parse_server_capabilities(self, c):
                log.info(f"server capabilities rejected by {bc}")
                return False
        self.server_client_shutdown = c.boolget("client-shutdown", True)
        self.server_compressors = c.strtupleget("compressors", )
        netlog("parse_server_capabilities(..) done")
        return True

    def parse_network_capabilities(self, caps: typedict) -> bool:
        netlog("parse_network_capabilities(..)")
        p = self._protocol
        if not p:
            log.warn("Warning: cannot parse network capabilities, no connection!")
            return False
        if p.TYPE == "rfb":
            return True
        if not p.enable_encoder_from_caps(caps):
            return False
        p.set_compression_level(self.compression_level)
        p.enable_compressor_from_caps(caps)
        p.parse_remote_caps(caps)
        self.server_packet_types = caps.strtupleget("packet-types")
        netlog(f"parse_network_capabilities(..) server_packet_types={self.server_packet_types}")
        return True

    def parse_encryption_capabilities(self, caps: typedict) -> bool:
        p = self._protocol
        if not p:
            return False
        encryption = self.get_encryption()
        if encryption:
            # server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(caps, key):
                return False
        return True

    def _process_startup_complete(self, packet: PacketType) -> None:
        # can be received if we connect with "xpra stop" or other command line client
        # as the server is starting up
        self.completed_startup = packet

    def _process_gibberish(self, packet: PacketType) -> None:
        log("process_gibberish(%s)", Ellipsizer(packet))
        message, bdata = packet[1:3]
        from xpra.net.socket_util import guess_packet_type  # pylint: disable=import-outside-toplevel
        packet_type = guess_packet_type(bdata)
        p = self._protocol
        exit_code = ExitCode.PACKET_FAILURE
        pcount = p.input_packetcount if p else 0
        data = bytestostr(bdata).strip("\n\r")
        show_as_text = pcount <= 1 and len(data) < 128 and all((c in string.printable) or c in "\n\r" for c in data)
        if pcount <= 1:
            exit_code = ExitCode.CONNECTION_FAILED
            netlog.error("Error: failed to connect")
        else:
            netlog.error("Error: received an invalid packet")
        if packet_type == "xpra":
            netlog.error(" xpra server bug or mangled packet")
        if not packet_type and data.startswith("disconnect: "):
            netlog.error(" %s", bytestostr(data).split(": ", 1)[1])
            data = ""
        elif packet_type and packet_type != "xpra":
            netlog.error(f" this is a {packet_type!r} packet,")
            netlog.error(" not from an xpra server?")
        else:
            parts = message.split(" read buffer=", 1)
            netlog.error(" received uninterpretable nonsense:")
            if not show_as_text:
                netlog.error(f" {parts[0]}")
                if len(parts) == 2:
                    text = bytestostr(parts[1])
                    netlog.error(" %s", text)
                    show_as_text = not data.startswith(text)
        if data.strip("\n\r \0"):
            if show_as_text:
                if data.find("\n") >= 0:
                    netlog.error(" data:")
                    for x in data.split("\n"):
                        netlog.error("  %r", x.split("\0")[0])
                else:
                    netlog.error(f" {data!r}")
            else:
                netlog.error(f" packet no {pcount} data: {repr_ellipsized(data)}")
        self.quit(exit_code)

    def _process_invalid(self, packet: PacketType) -> None:
        message, data = packet[1:3]
        netlog.info(f"Received invalid packet: {message}")
        netlog(" data: %s", Ellipsizer(data))
        p = self._protocol
        exit_code = ExitCode.PACKET_FAILURE
        if not p or p.input_packetcount <= 1:
            exit_code = ExitCode.CONNECTION_FAILED
        self.quit(exit_code)

    ######################################################################
    # generic control command methods
    # the actual hooking of "control" requests is done in:
    # * `NetworkListener` for local sockets
    # * `UIXpraClient` for server connections
    def add_control_commands(self) -> None:
        try:
            from xpra.net.control.common import HelloCommand, HelpCommand, DisabledCommand
            from xpra.net.control.debug import DebugControl
        except ImportError:
            return
        self.control_commands |= {
            "hello": HelloCommand(),
            "debug": DebugControl(),
            "help": HelpCommand(self.control_commands),
            "*": DisabledCommand(),
        }

    def add_control_command(self, name: str, control) -> None:
        self.control_commands[name] = control

    def _process_control(self, packet: PacketType) -> None:
        args = packet[1:]
        code, msg = self.process_control_command(self._protocol, *args)
        log.warn(f"{code}, {msg!r}")

    def process_control_command(self, proto, *args) -> tuple[int, str]:
        from xpra.net.control.common import process_control_command
        return process_control_command(proto, self.control_commands, *args)

    ######################################################################
    # packets:
    def init_packet_handlers(self) -> None:
        self.add_packets("hello")
        self.add_packets("challenge", "disconnect", CONNECTION_LOST, GIBBERISH, INVALID, main_thread=True)
        if SSL_UPGRADE:
            self.add_packets("ssl-upgrade")

    def init_authenticated_packet_handlers(self) -> None:
        FilePrintMixin.init_authenticated_packet_handlers(self)
        self.add_packets("startup-complete", "control", main_thread=True)

    def process_packet(self, proto, packet) -> None:
        self.dispatch_packet(proto, packet, True)

    def call_packet_handler(self, handler: Callable, proto, packet) -> None:
        handler(packet)
