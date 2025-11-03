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

from xpra.scripts.config import InitExit
from xpra.common import (
    FULL_INFO, LOG_HELLO,
    ConnectionMessage, disconnect_is_an_error, noerr, NotificationID, noop,
)
from xpra.net import compression
from xpra.net.common import Packet, PacketElement
from xpra.net.protocol.factory import get_client_protocol_class
from xpra.net.protocol.constants import CONNECTION_LOST, GIBBERISH, INVALID
from xpra.util.version import get_version_info, vparts, XPRA_VERSION
from xpra.net.digest import get_salt
from xpra.platform.info import get_name, get_username
from xpra.client.base.factory import get_client_base_classes
from xpra.os_util import get_machine_id, get_user_uuid, gi_import, BITS
from xpra.util.child_reaper import get_child_reaper, reaper_cleanup
from xpra.util.system import SIGNAMES, register_SIGUSR_signals
from xpra.util.io import stderr_print
from xpra.util.objects import typedict
from xpra.util.str_fn import (
    Ellipsizer, repr_ellipsized, print_nested_dict,
    bytestostr, hexstr,
)
from xpra.util.env import envbool
from xpra.exit_codes import ExitCode, ExitValue, exit_str
from xpra.log import Logger

GLib = gi_import("GLib")

CLIENT_BASES = get_client_base_classes()
ClientBaseClass = type('ClientBaseClass', CLIENT_BASES, {})

log = Logger("client")
netlog = Logger("network")

EXTRA_TIMEOUT = 10
LOG_DISCONNECT = envbool("XPRA_LOG_DISCONNECT", True)

log("Client base classes: %s", CLIENT_BASES)


class XpraClientBase(ClientBaseClass):
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
            self.defaults_init()
            for bc in CLIENT_BASES:
                bc.__init__(self)
            self.init_packet_handlers()
        self._init_done = False
        self.exit_code: ExitValue | None = None
        self.start_time = int(monotonic())

    def defaults_init(self) -> None:
        # skip warning when running the client
        from xpra.util import child_reaper
        child_reaper.POLL_WARNING = False
        get_child_reaper()
        log("XpraClientBase.defaults_init() os.environ:")
        for k, v in os.environ.items():
            log(f" {k}={v!r}")
        self.client_type = "python"
        # client state:
        self.exit_code: ExitValue | None = None
        self.exit_on_signal = False
        self.display_desc = {}
        # connection attributes:
        self.hello_extra = {}
        self.has_password = False
        self.compression_level = 0
        self.display = None
        self.server_client_shutdown = True
        self.server_compressors = []
        self.verify_connected_timer = 0
        # protocol stuff:
        self._protocol = None
        self._priority_packets: list[Packet] = []
        self._ordinary_packets: list[Packet] = []
        # server state and caps:
        self.server_packet_types = ()
        self.connection_established = False
        self.completed_startup = False
        self.uuid: str = get_user_uuid()
        self.session_id: str = uuid.uuid4().hex
        self.have_more = noop

    def init(self, opts) -> None:
        if self._init_done:
            # the gtk client classes can inherit this method
            # from multiple parents, skip initializing twice
            return
        self._init_done = True
        for bc in CLIENT_BASES:
            bc.init(self, opts)
        self.compression_level = opts.compression_level
        self.display = opts.display
        self.install_signal_handlers()

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

    def handle_os_signal(self, signum: int | signal.Signals, _frame: FrameType | None = None) -> None:
        if self.exit_code is None:
            try:
                stderr_print()
                log.info("client got signal %s", SIGNAMES.get(signum, signum))
            except IOError:
                pass
        self.handle_app_signal(int(signum))

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.handle_os_signal)
        signal.signal(signal.SIGTERM, self.handle_os_signal)
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

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"pid": os.getpid()}
        for bc in CLIENT_BASES:
            info.update(bc.get_info(self))
        return info

    def make_protocol(self, conn):
        if not conn:
            raise ValueError("no connection")
        self.add_packet_handler("setting-change", noop)
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
        self.have_more = protocol.source_has_more
        process = getattr(conn, "process", None)  # ie: ssh is handled by another process
        if process:
            proc, name, command = process
            if proc:
                get_child_reaper().add_process(proc, name, command, ignore=True, forget=False)
        netlog("setup_connection(%s) protocol=%s", conn, protocol)
        self.setup_connection(conn)
        return protocol

    def cancel_verify_connected_timer(self):
        vct = self.verify_connected_timer
        if vct:
            self.verify_connected_timer = 0
            GLib.source_remove(vct)

    def schedule_verify_connected(self):
        conn = getattr(self._protocol, "_conn", None)
        if not conn:
            return
        self.verify_connected_timer = GLib.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)

    def setup_connection(self, conn) -> None:
        for bc in CLIENT_BASES:
            bc.setup_connection(self, conn)

    def send_hello(self, challenge_response=b"", client_salt=b"") -> None:
        if not self._protocol:
            log("send_hello(..) skipped, no protocol (listen mode?)")
            return
        try:
            hello = self.make_hello_base()
            if self.has_password and not challenge_response:
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
        self.cancel_verify_connected_timer()
        self.schedule_verify_connected()

    def verify_connected(self) -> None:
        if not self.connection_established:
            # server has not said hello yet
            self.warn_and_quit(ExitCode.CONNECTION_FAILED, "connection timed out")

    def make_hello_base(self) -> dict[str, Any]:
        capabilities = {}
        for bc in CLIENT_BASES:
            # FIXME: digests should be added to!
            capabilities.update(bc.get_caps(self))
        capabilities |= {
            "uuid": self.uuid,
            "compression_level": self.compression_level,
            "version": vparts(XPRA_VERSION, FULL_INFO + 1),
        }
        if self.display:
            capabilities["display"] = self.display
        if FULL_INFO > 0:
            capabilities |= {
                "client_type": self.client_type,
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
        vi = self.get_version_info()
        capabilities["build"] = vi
        mid = get_machine_id()
        if mid:
            capabilities["machine_id"] = mid
        capabilities.update(self.hello_extra)
        return capabilities

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
        packet = Packet(packet_type, *parts)
        self._ordinary_packets.append(packet)
        self.have_more()

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        packet = Packet(packet_type, *parts)
        self._priority_packets.append(packet)
        self.have_more()

    def next_packet(self) -> tuple[Packet, bool, bool]:
        # naughty dependency on pointer:
        mouse_position = getattr(self, "_mouse_position", None)
        netlog("next_packet() packets in queues: priority=%i, ordinary=%i, mouse=%s",
               len(self._priority_packets), len(self._ordinary_packets), bool(mouse_position))
        synchronous = True
        if self._priority_packets:
            packet = self._priority_packets.pop(0)
        elif self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif mouse_position is not None:
            packet = mouse_position
            synchronous = False
            self._mouse_position = mouse_position = None
        else:
            packet = ("none", )
        has_more = packet is not None and (
            bool(self._priority_packets) or bool(self._ordinary_packets) or mouse_position is not None
        )
        return packet, synchronous, has_more

    def cleanup(self) -> None:
        reaper_cleanup()
        for bc in CLIENT_BASES:
            with log.trap_error(f"Error cleaning {bc!r} handler"):
                bc.cleanup(self)
        self.cancel_verify_connected_timer()
        p = self._protocol
        log("XpraClientBase.cleanup() protocol=%s", p)
        if p:
            self._protocol = None
            log("calling %s", p.close)
            p.close()
        log("cleanup done")

    def run(self) -> ExitValue:
        self.start_protocol()
        return 0

    def start_protocol(self) -> None:
        # protocol may be None in "listen" mode
        if self._protocol:
            self._protocol.start()

    def quit(self, exit_code: ExitValue = 0) -> None:
        raise NotImplementedError()

    def warn_and_quit(self, exit_code: ExitValue, message: str) -> None:
        log.warn(message)
        self.quit(exit_code)

    def send_shutdown_server(self) -> None:
        assert self.server_client_shutdown
        self.send("shutdown-server")

    def _process_disconnect(self, packet: Packet) -> None:
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

    def _process_connection_lost(self, _packet: Packet) -> None:
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

    def _process_hello(self, packet: Packet) -> None:
        hello_data = packet.get_dict(1)
        if LOG_HELLO:
            netlog.info("received hello:")
            print_nested_dict(hello_data, print_fn=netlog.info)
        self.remove_packet_handlers("challenge")
        self.remove_packet_handlers("ssl-upgrade")
        try:
            caps = typedict(hello_data)
            netlog("processing hello from server: %s", Ellipsizer(caps))
            if not self.server_connection_established(caps):
                self.warn_and_quit(ExitCode.FAILURE, "failed to establish connection")
            else:
                self.cancel_verify_connected_timer()
                self.connection_established = True
        except Exception as e:
            netlog.error("Error processing hello packet from server", exc_info=True)
            netlog("hello data: %s", packet)
            self.warn_and_quit(ExitCode.FAILURE, f"error processing hello packet from server: {e}")

    def server_connection_established(self, caps: typedict) -> bool:
        assert caps and self._protocol
        netlog("server_connection_established(..)")
        if not self.parse_server_capabilities(caps):
            netlog("server_connection_established(..) failed server capabilities")
            return False
        if not self.parse_network_capabilities(caps):
            netlog("server_connection_established(..) failed network capabilities")
            return False
        netlog("server_connection_established(..) adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        return True

    def parse_server_capabilities(self, c: typedict) -> bool:
        netlog("parse_server_capabilities(..)")
        for bc in CLIENT_BASES:
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

    def _process_startup_complete(self, packet: Packet) -> None:
        # can be received if we connect with "xpra stop" or other command line client
        # as the server is starting up
        self.completed_startup = packet
        for bc in CLIENT_BASES:
            bc.startup_complete(self)

    def _process_gibberish(self, packet: Packet) -> None:
        log("process_gibberish(%s)", Ellipsizer(packet))
        message = packet.get_str(1)
        bdata = packet.get_bytes(2)
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

    def _process_invalid(self, packet: Packet) -> None:
        message = packet.get_str(1)
        data = packet.get_bytes(2)
        netlog.info(f"Received invalid packet: {message}")
        netlog(" data: %s", Ellipsizer(data))
        p = self._protocol
        exit_code = ExitCode.PACKET_FAILURE
        if not p or p.input_packetcount <= 1:
            exit_code = ExitCode.CONNECTION_FAILED
        self.quit(exit_code)

    ######################################################################
    # packets:
    def init_packet_handlers(self) -> None:
        self.add_packets("hello")
        self.add_packets("disconnect", CONNECTION_LOST, GIBBERISH, INVALID, main_thread=True)
        for bc in CLIENT_BASES:
            bc.init_packet_handlers(self)

    def init_authenticated_packet_handlers(self) -> None:
        for bc in CLIENT_BASES:
            bc.init_authenticated_packet_handlers(self)

    def process_packet(self, proto, packet) -> None:
        self.dispatch_packet(proto, packet, True)
