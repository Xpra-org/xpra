# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
import string
from time import time
from typing import Any, NoReturn
from types import FrameType
from collections.abc import Callable, Sequence

from xpra.scripts.config import InitExit
from xpra.common import noerr, noop, may_show_progress, stop_asyncio_loop
from xpra.net.constants import ConnectionMessage
from xpra.net.common import (
    Packet, PacketElement, PacketHandlerType,
    disconnect_is_an_error,
    FULL_INFO, LOG_HELLO, BACKWARDS_COMPATIBLE,
)
from xpra.net.dispatch import PacketDispatcher
from xpra.net.protocol.factory import get_client_protocol_class
from xpra.net.packet_type import CONNECTION_LOST, GIBBERISH, INVALID, SHUTDOWN_SERVER
from xpra.util.thread import is_main_thread
from xpra.util.version import get_version_info
from xpra.net.digest import get_salt
from xpra.client.base.factory import get_client_subsystems
from xpra.util.child_reaper import get_child_reaper, reaper_cleanup
from xpra.util.system import SIGNAMES, register_SIGUSR_signals
from xpra.util.io import stderr_print
from xpra.util.objects import typedict, merge_dicts
from xpra.util.str_fn import (
    Ellipsizer, repr_ellipsized, print_nested_dict,
    bytestostr, hexstr,
)
from xpra.util.env import envbool
from xpra.exit_codes import ExitCode, ExitValue, exit_str
from xpra.log import Logger

BASE_SUBSYSTEMS = get_client_subsystems()

log = Logger("client")
netlog = Logger("network")
sublog = Logger("subsystems")

LOG_DISCONNECT = envbool("XPRA_LOG_DISCONNECT", True)

sublog("Client subsystems: %s", BASE_SUBSYSTEMS)


class XpraClientBase(PacketDispatcher):
    """
    Base class for Xpra clients.
    Provides the glue code for:
    * sending packets via Protocol
    * handling packets received via _process_packet
    """
    __signals__ = ["startup-complete"]

    @staticmethod
    def get_subsystem_classes() -> dict[str, type]:
        """
        The subsystem classes to compose, keyed by `PREFIX`. Concrete toolkit
        clients (`UIXpraClient`, `GTKXpraClient`, `XpraWin32Client`, ...) override
        this to extend or patch entries returned by their superclass's version -
        e.g. substituting a toolkit-specific subclass for "display", or adding a
        toolkit-only subsystem like "dialogs" (see `xpra.client.gui.ui_client_base`
        and `xpra.client.gtk3.client_base`). Called polymorphically via `self.` in
        `__init__`, so a single call already picks up every override in the
        concrete class's MRO.
        """
        return {cls.PREFIX: cls for cls in BASE_SUBSYSTEMS}

    def __init__(self):
        self.defaults_init()
        PacketDispatcher.__init__(self)
        # registry of composed subsystem instances, keyed by `PREFIX`
        # (see `StubClientMixin.get_subsystem`):
        self.subsystems: dict[str, Any] = {}
        for prefix, cls in self.get_subsystem_classes().items():
            subsystem = cls(client=self)
            sublog("%s=%s", prefix, subsystem)
            self.subsystems[prefix] = subsystem
        self.init_packet_handlers()
        self.exit_code: ExitValue | None = None
        self.start_time = int(time())

    def get_subsystem(self, name: str):
        """
        look up a composed (or still-muxed) subsystem by its `PREFIX`.
        Defined directly here (mirroring `StubClientMixin.get_subsystem`, not
        inherited from it) because every `base/*` mixin is composed out now,
        so this class has no mixed-in base to pick up `StubClientMixin` from.
        """
        return self.subsystems.get(name)

    def add_control_command(self, name: str, control) -> None:
        # delegate to the `control` subsystem (mirror of `ServerCore.add_control_command`),
        # so other subsystems can register a command without depending on the MRO:
        control_subsystem = self.subsystems.get("control")
        if control_subsystem:
            control_subsystem.add_control_command(name, control)

    def _call_subsystem(self, cls, method: str, *args):
        # dispatch one subsystem's lifecycle/caps call:
        # to its real instance if it has been composed out, otherwise to the
        # muxed client (identical to the old `cls.method(self, *args)`).
        instance = self.subsystems.get(getattr(cls, "PREFIX", ""))
        if instance is not None and instance is not self:
            return getattr(instance, method)(*args)
        return getattr(cls, method)(self, *args)

    def _dispatch_fire(self, method: str, *args, reverse: bool = False) -> None:
        # fan a lifecycle call out to every composed subsystem (mirror of `ServerCore._dispatch_fire`).
        # every `PREFIX`-bearing subsystem is composed now, so `subsystems.values()` are real,
        # distinct instances - safe to call directly (no risk of re-entering `self`'s own method).
        subs = list(self.subsystems.values())
        if reverse:
            subs.reverse()
        for sub in subs:
            fn = getattr(sub, method, None)
            if fn is None:
                sublog.warn("Warning: no %r on %s", method, sub)
                continue
            try:
                fn(*args)
            except Exception:
                sublog.warn(f"Error: in {sub}.{method}", exc_info=True)

    def _dispatch_merge(self, method: str, *args) -> dict:
        # merge a dict-returning call across every composed subsystem (mirror of `ServerCore._dispatch_merge`).
        info: dict = {}
        for sub in self.subsystems.values():
            fn = getattr(sub, method, None)
            try:
                d = fn(*args)
            except Exception:
                sublog.warn(f"Error: in {sub}.{method}", exc_info=True)
                continue
            if d:
                merge_dicts(info, d)
        return info

    def idle_add(self, fn: Callable, *args, **kwargs) -> int:
        ...

    def timeout_add(self, timeout: int, fn: Callable, *args, **kwargs) -> int:
        ...

    def source_remove(self, tid: int) -> None:
        ...

    def defaults_init(self) -> None:
        # skip warning when running the client
        from xpra.util import child_reaper
        child_reaper.POLL_WARNING = False
        get_child_reaper()
        log("XpraClientBase.defaults_init() os.environ:")
        for k, v in os.environ.items():
            log(f" {k}={v!r}")
        # client state:
        self.exit_code: ExitValue | None = None
        self.exit_on_signal = False
        self.display_desc = {}
        self._on_handshake: Sequence[tuple[Callable, Sequence[Any]]] | None = []
        # connection attributes:
        self.hello_extra = {}
        self.has_password = False
        self.display = None
        self.server_client_shutdown = True
        self.verify_connected_timer = 0
        # identity: concrete clients (and `GObjectClientAdapter`, which runs before
        # subsystem composition) freely override this; the `clientid` subsystem just
        # reports whatever it finds here (see `IDClient.get_caps`):
        self.client_type = "python"
        # protocol stuff:
        self._protocol = None
        self._priority_packets: list[Packet] = []
        self._ordinary_packets: list[Packet] = []
        # server state and caps:
        self.connection_established = False
        self.completed_startup = False
        self.have_more = noop

    def init(self, opts) -> None:
        self._dispatch_fire("init", opts)
        self.display = opts.display
        self.install_signal_handlers()

    def init_ui(self, opts) -> None:
        self._dispatch_fire("init_ui", opts)

    def load(self) -> None:
        self._dispatch_fire("load")

    def run(self) -> ExitValue:
        self._dispatch_fire("run")
        return ExitCode.OK

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
        self.timeout_add(0, self.signal_disconnect_and_quit, 128 + signum, reason)

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
        register_SIGUSR_signals(self.idle_add)

    # noinspection PyUnreachableCode
    def signal_disconnect_and_quit(self, exit_code: ExitValue, reason: str) -> None:
        log("signal_disconnect_and_quit(%s, %s) exit_on_signal=%s", exit_code, reason, self.exit_on_signal)
        if not self.exit_on_signal:
            # if we get another signal, we'll try to exit without idle_add...
            self.exit_on_signal = True
            self.idle_add(self.disconnect_and_quit, exit_code, reason)
            self.idle_add(self.quit, exit_code)
            self.idle_add(self.exit)
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
            self.idle_add(self.quit, exit_code)

        if p:
            p.send_disconnect([str(reason)], done_callback=protocol_closed)
        self.timeout_add(1000, self.quit, exit_code)

    def exit(self) -> NoReturn:
        log("XpraClientBase.exit() calling %s", sys.exit)
        may_show_progress(self, 100, "terminating")
        log(f"exit() calling {sys.exit}")
        sys.exit(int(self.exit_code or ExitCode.OK))

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"pid": os.getpid()}
        info.update(PacketDispatcher.get_info(self))
        merge_dicts(info, self._dispatch_merge("get_info"))
        return info

    def get_caps(self) -> dict[str, Any]:
        """
        `XpraClientBase` itself has no `PREFIX` and is never composed, so this
        is never actually reached via `_call_subsystem` - it stays as the
        documented no-op contract for that dispatch mechanism.
        """
        return {}

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
        self.idle_add(self.send_hello)
        return protocol

    def cancel_verify_connected_timer(self):
        if vct := self.verify_connected_timer:
            self.verify_connected_timer = 0
            self.source_remove(vct)

    def schedule_verify_connected(self):
        conn = getattr(self._protocol, "_conn", None)
        if not conn:
            return
        self.verify_connected_timer = self.timeout_add(round(conn.timeout + conn.connection_delay) * 1000, self.verify_connected)

    def setup_connection(self, conn) -> None:
        self._dispatch_fire("setup_connection", conn)

    def send_hello(self, challenge_response=b"", client_salt=b"") -> None:
        if not self._protocol:
            log("send_hello(..) skipped, no protocol (listen mode?)")
            return
        try:
            if self.has_password and not challenge_response:
                # avoid sending the full hello: tell the server we want
                # a packet challenge first
                hello = self.make_hello_base()
                hello["challenge"] = True
            else:
                hello = self.make_hello()
            if BACKWARDS_COMPATIBLE:
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
        """
        Minimal hello sent to request a password challenge, before authentication:
        only the base (non-UI) subsystems' capabilities are included
        (see `make_hello`, used for the normal, fully authenticated case).
        """
        capabilities = {}
        for bc in BASE_SUBSYSTEMS:
            # FIXME: digests should be added to!
            capabilities.update(self._call_subsystem(bc, "get_caps"))
        return self._add_common_hello(capabilities)

    def _add_common_hello(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        # shared by `make_hello_base` and `make_hello`:
        # difficult to move this attribute:
        if self.display:
            capabilities["display"] = self.display
        session = self.get_session_caps()
        if session:
            capabilities["session"] = session
        capabilities.update(self.hello_extra)
        return capabilities

    def get_session_caps(self) -> dict[str, str]:
        """
        Identifying hints used by intermediaries (e.g. a proxy server with
        --session-registry=mdns) to pick the target session. Populated from
        --session-name and from the parsed display description.
        """
        session: dict[str, str] = {}
        desc = self.display_desc
        name = getattr(self, "session_name", "") or desc.get("session-name", "")
        if name:
            session["name"] = name
        if self.display or desc.get("display"):
            session["display"] = self.display or desc.get("display", "")
        uuid = desc.get("uuid", "")
        if uuid:
            session["uuid"] = str(uuid)
        log("get_session_caps()=%s from %s", session, (desc, self.display))
        return session

    @staticmethod
    def get_version_info() -> dict[str, Any]:
        return get_version_info(FULL_INFO)

    def make_hello(self) -> dict[str, Any]:
        """
        Full hello, sent once authenticated (or when no password is required):
        gathers `get_caps` from every composed subsystem generically - for a
        `UIXpraClient` instance, `self.subsystems` already holds both the base
        and the UI subsystems (see `get_subsystem_classes`), so this one call
        covers both.
        """
        capabilities = self._dispatch_merge("get_caps")
        capabilities = self._add_common_hello(capabilities)
        if BACKWARDS_COMPATIBLE:
            capabilities.setdefault("keyboard", False)
        return capabilities

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        packet = Packet(packet_type, *parts)
        self._ordinary_packets.append(packet)
        self.have_more()

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        packet = Packet(packet_type, *parts)
        self._priority_packets.append(packet)
        self.have_more()

    def next_packet(self) -> tuple[Packet, bool, bool]:
        # naughty dependency on the `pointer` subsystem (absent on non-UI clients):
        pointer = self.get_subsystem("pointer")
        mouse_position = pointer.position if pointer else None
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
            pointer.position = mouse_position = None
        else:
            packet = ("none", )
        has_more = packet is not None and (
            bool(self._priority_packets) or bool(self._ordinary_packets) or mouse_position is not None
        )
        return packet, synchronous, has_more

    def cleanup(self) -> None:
        self._dispatch_fire("cleanup")
        self.cancel_verify_connected_timer()
        p = self._protocol
        log("XpraClientBase.cleanup() protocol=%s", p)
        if p:
            self._protocol = None
            log("calling %s", p.close)
            p.close()
        stop_asyncio_loop()
        reaper_cleanup()
        log("cleanup done")

    def quit(self, exit_code: ExitValue = 0) -> None:
        raise NotImplementedError()

    def warn_and_quit(self, exit_code: ExitValue, message: str) -> None:
        log.warn(message)
        if is_main_thread():
            self.quit(exit_code)
        else:
            self.idle_add(self.quit, exit_code)

    def send_shutdown_server(self) -> None:
        assert self.server_client_shutdown
        self.send(SHUTDOWN_SERVER)

    def _process_connection_close(self, packet: Packet) -> None:
        # ie: ("disconnect", "version error", "incompatible version")
        netlog("%s", packet)
        if self.exit_code is not None:
            return
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
        transport_error = getattr(p, "error", ExitCode.OK)
        if transport_error != ExitCode.OK:
            exit_code = transport_error
        elif p and p.input_raw_packetcount == 0:
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
        try:
            caps = typedict(hello_data)
            netlog("processing hello from server: %s", Ellipsizer(caps))
            if not self.server_connection_established(caps):
                self.warn_and_quit(ExitCode.FAILURE, "failed to establish connection")
                return
            self.cancel_verify_connected_timer()
            self.connection_accepted(caps)
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
        netlog("server_connection_established(..) adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        return True

    def connection_accepted(self, caps: typedict) -> None:
        log("accepted caps=%s", Ellipsizer(caps))
        self.connection_established = True
        self.handshake_complete()

    def handshake_complete(self) -> None:
        oh = self._on_handshake
        self._on_handshake = None
        for cb, args in oh:
            with log.trap_error("Error processing handshake callback %s", cb):
                self.idle_add(cb, *args)

    def after_handshake(self, cb: Callable, *args) -> None:
        log("after_handshake(%s, %s) on_handshake=%s", cb, args, Ellipsizer(self._on_handshake))
        if self._on_handshake is None:
            # handshake has already occurred, just call it:
            self.idle_add(cb, *args)
        else:
            self._on_handshake.append((cb, args))

    def parse_server_capabilities(self, c: typedict) -> bool:
        netlog("parse_server_capabilities(..)")
        for sub in self.subsystems.values():
            try:
                if not sub.parse_server_capabilities(c):
                    sublog.info(f"server capabilities rejected by {sub}")
                    return False
            except Exception:
                sublog.error("Error parsing server capabilities using %s", sub, exc_info=True)
                return False
        self.server_client_shutdown = c.boolget("client-shutdown", True)
        netlog("parse_server_capabilities(..) done")
        return True

    def _process_startup_complete(self, packet: Packet) -> None:
        # can be received if we connect with "xpra stop" or other command line client
        # as the server is starting up
        self.completed_startup = packet
        self.emit("startup-complete")

    def _process_gibberish(self, packet: Packet) -> None:
        log("process_gibberish(%s)", Ellipsizer(packet))
        if self.exit_code is not None:
            return
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
        log("process-invalid: %s", packet)
        if self.exit_code is not None:
            return
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
        # lifecycle packets are registered as default UI handlers so they bypass the
        # is_closed() gate in dispatch_packet but still run on the UI thread
        # (they tear down GTK/X11 resources via cleanup(), which must not happen
        # from the network parse thread):
        self._default_ui_packet_handlers["connection-close"] = self._process_connection_close
        self._default_ui_packet_handlers[CONNECTION_LOST] = self._process_connection_lost
        self._default_ui_packet_handlers[GIBBERISH] = self._process_gibberish
        self._default_ui_packet_handlers[INVALID] = self._process_invalid
        self.add_legacy_alias("disconnect", "connection-close")
        self._dispatch_fire("init_packet_handlers")

    def init_authenticated_packet_handlers(self) -> None:
        self._dispatch_fire("init_authenticated_packet_handlers")

    def call_packet_handler(self, main: bool, handler: PacketHandlerType, _proto, packet: Packet) -> None:
        """
        The client packet handlers don't need the `proto` argument,
        so `call_packet_handler` is overriden here so we can drop it.
        """
        def call() -> None:
            handler(packet)
        if main:
            self.idle_add(call)
        else:
            call()

    def process_packet(self, proto, packet) -> None:
        self.dispatch_packet(proto, packet, True)
