# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import socket
import signal
import threading
from time import sleep, time, monotonic
from types import FrameType
from typing import Any, NoReturn
from collections.abc import Callable, Sequence

from xpra.util.version import XPRA_VERSION, version_str, version_compat_check, protocol_compat_check
from xpra.exit_codes import ExitCode, ExitValue
from xpra.server import ServerExitMode
from xpra.server.glib_server import GLibServer
from xpra.util import subsystem as dispatch
from xpra.util.parsing import TRUE_OPTIONS
from xpra.net.common import (
    is_request_allowed, Packet,
    FULL_INFO, LOG_HELLO, MIN_PROTOCOL_VERSION,
)
from xpra.net.constants import ConnectionMessage
from xpra.net.digest import get_caps as get_digest_caps
from xpra.net.net_util import get_network_caps
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.platform import set_name, threaded_server_init
from xpra.os_util import force_quit, OSX, gi_import
from xpra.util.system import register_SIGUSR_signals, get_run_info, deadly_signal
from xpra.util.io import load_binary_file
from xpra.util.background_worker import get_worker, quit_worker
from xpra.util.thread import start_thread, check_main_thread
from xpra.common import noop, noerr, stop_asyncio_loop
from xpra.util.objects import merge_dicts
from xpra.util.pysystem import dump_all_frames
from xpra.util.objects import typedict
from xpra.util.str_fn import Ellipsizer, print_nested_dict
from xpra.util.env import envint, envbool, restore_script_env
from xpra.log import Logger

# pylint: disable=import-outside-toplevel

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")

main_thread = threading.current_thread()

SIMULATE_SERVER_HELLO_ERROR = envbool("XPRA_SIMULATE_SERVER_HELLO_ERROR", False)
UNAUTHENTICATED_HELLO_REQUESTS = tuple(
    x.strip() for x in
    os.environ.get("XPRA_UNAUTHENTICATED_HELLO_REQUESTS", "version,connect_test,id").split(",") if x.strip()
)

SYSCONFIG = envbool("XPRA_SYSCONFIG", FULL_INFO > 1)
INIT_THREAD_TIMEOUT = envint("XPRA_INIT_THREAD_TIMEOUT", 10)

ENV_BLOCKLIST = ("LS_COLORS", )


# class used to distinguish internal errors
# which should not be shown to the client,
# from useful messages we do want to pass on
class ClientException(Exception):
    pass


def get_instance_subsystem_classes() -> tuple[type, ...]:
    """
    Subsystem classes for ServerCore. Each is instantiated and stored in
    `self.subsystems` keyed by `cls.PREFIX`.
    """
    from xpra.server.auth import AuthenticationManager
    from xpra.server.subsystem.platform import PlatformServer
    from xpra.server.subsystem.splash import SplashServer
    from xpra.server.subsystem.info import InfoServer
    from xpra.server.subsystem.control import ControlHandler
    from xpra.server.subsystem.daemon import DaemonServer
    from xpra.server.subsystem.id import IDServer
    from xpra.server.subsystem.sessionfiles import SessionFilesServer
    from xpra.server.subsystem.version import VersionServer
    from xpra.server.subsystem.process import ProcessServer
    from xpra.server import features
    classes: list[type] = []
    if features.landlock:
        # Confine before the remaining subsystems and listeners start.
        from xpra.server.subsystem.landlock import LandLock
        classes.append(LandLock)
    # NetworkServer must exist before `init()`,
    # as the bind sockets are created before the other subsystems:
    from xpra.server.subsystem.network import NetworkServer
    classes.append(NetworkServer)
    # IDServer must come before any subsystem that reads the server uuid.
    # SessionFilesServer must come before any subsystem that appends to
    # its `session_files` list during init().
    classes.extend((
        AuthenticationManager,
        PlatformServer,
        SplashServer,
        IDServer,
        SessionFilesServer,
        ProcessServer,
        DaemonServer,
        InfoServer,
        VersionServer,
    ))
    if features.control:
        classes.append(ControlHandler)
    if features.mdns:
        from xpra.server.subsystem.mdns import MdnsServer
        classes.append(MdnsServer)
    return tuple(classes)


INSTANCE_SUBSYSTEM_CLASSES = get_instance_subsystem_classes()

SIGNALS: dict[str, int] = {
    "init-thread-ended": 0,
    "running": 0,
    "client-exited": 0,
    "last-client-exited": 0,
    "new-ui-driver": 0,
    # (setting, value, source): `source` is `None` for the server wide settings
    "setting-changed": 3,
}


# noinspection PyMethodMayBeStatic
class ServerCore(GLibServer):
    """
        This is the simplest base class for servers.
        It handles the initial handshake and authentication,
        the connection layer is handled by the `network` subsystem.
    """
    __signals__ = SIGNALS

    def __init__(self):
        log("ServerCore.__init__()")
        # `self.subsystems` (keyed by PREFIX) is declared by `PacketDispatcher.__init__`,
        # which also routes packets to it; it is populated by subclass __init__
        # methods (ServerBase, ProxyServer, ...) as they instantiate their
        # subsystem classes.
        self.hello_request_handlers: dict[str, Callable[[Any, typedict], bool]] = {
            "connect_test": self._handle_hello_request_connect_test,
        }
        GLibServer.__init__(self)
        # construct standalone instance-based subsystems and register them:
        for cls in INSTANCE_SUBSYSTEM_CLASSES:
            self.add_subsystem(cls)
        self.start_time = time()
        self.session_type: str = "unknown"
        self._closing: bool = False
        self._exit_mode = ServerExitMode.UNSET
        self.session_name = ""

        # Features:
        self.readonly = False
        self.compression_level = 1

        self._default_packet_handlers: dict[str, Callable] = {}

    def init_subsystems(self) -> None:
        """
        Hook for server variants that register backend-specific subsystems after
        construction. Core subsystems are registered during __init__.
        """

    def add_subsystem(self, cls):
        instance = cls(self)
        self.subsystems[cls.PREFIX] = instance
        return instance

    def init(self, opts) -> None:
        log("ServerCore.init(%s)", opts)
        # This shared worker must predate every filtered thread.  Otherwise the
        # first add_work_item() from one of them would create a worker which
        # inherits that thread's seccomp policy.
        get_worker()
        self.session_name = str(opts.session_name)
        set_name("Xpra", self.session_name or "Xpra")
        self.compression_level = opts.compression_level
        self.readonly = opts.readonly
        dispatch.call(self.subsystems, "init", opts)

    def setup(self) -> None:
        log("starting component init")
        # the `landlock` subsystem comes first, so its `setup` confines the server
        # after all the `early_setup` calls and before any other `setup`:
        dispatch.call(self.subsystems, "early_setup")
        dispatch.call(self.subsystems, "setup")
        self.network.start_listen_sockets()
        self.init_packet_handlers()

    ######################################################################
    # run / stop:
    def signal_quit(self, signum, _frame=None) -> None:
        self.closing()
        self.install_signal_handlers(deadly_signal)
        GLib.idle_add(self.clean_quit)
        GLib.idle_add(sys.exit, 128 + signum)

    def clean_quit(self, exit_mode=ServerExitMode.NORMAL) -> None:
        log("clean_quit(%s)", exit_mode)
        if self._exit_mode == ServerExitMode.UNSET:
            self._exit_mode = exit_mode
        GLib.timeout_add(5000, self.force_quit)
        self.closing()
        self.cleanup()
        self.quit_worker()

    def force_quit(self, exit_code: ExitValue = ExitCode.FAILURE) -> NoReturn:
        log("force_quit()")
        force_quit(int(exit_code))

    def quit_worker(self) -> None:
        quit_worker(self.quit)

    def quit(self, exit_mode=ServerExitMode.NORMAL) -> None:
        log("quit(%s)", exit_mode)
        if self._exit_mode == ServerExitMode.UNSET:
            self._exit_mode = exit_mode
        self.closing()
        noerr(sys.stdout.flush)
        stop = self._exit_mode not in (ServerExitMode.EXIT, ServerExitMode.UPGRADE)
        self.late_cleanup(stop=stop)
        self.do_quit()
        log("quit(%s) do_quit done!", exit_mode)
        dump_all_frames()

    def closing(self) -> None:
        if not self._closing:
            self._closing = True
            self.log_closing_message()

    def log_closing_message(self) -> None:
        exiting = self._exit_mode in (ServerExitMode.EXIT, ServerExitMode.UPGRADE)
        log.info("%s server is %s", self.session_type, ["terminating", "exiting"][exiting])

    def install_signal_handlers(self, callback: Callable[[int], None]) -> None:
        def os_signal(signum: signal.Signals | int, _frame: FrameType | None = None) -> None:
            callback(signum)

        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        register_SIGUSR_signals(GLib.idle_add)

    def threaded_init(self) -> None:
        log("threaded_init() servercore start")
        # platform specific init:
        threaded_server_init()
        self.emit("init-thread-ended")

    def get_child_env(self) -> dict[str, str]:
        # base child env: filtered os.environ with script-launcher overrides reverted,
        # followed by subsystem contributions.
        env = {k: v for k, v in os.environ.items() if k not in ENV_BLOCKLIST}
        if OSX:
            env = restore_script_env(env)
        env.update(dispatch.merge(self.subsystems, "get_child_env"))
        return env

    # --------------------------------------------------------------------
    # subsystem lookup and dispatch helpers
    # `self.subsystems` stores subsystem instances, keyed by PREFIX.
    # --------------------------------------------------------------------

    @property
    def network(self):
        """ the `network` subsystem, which owns the sockets and the connections """
        return self.subsystems["network"]

    def get_subsystem(self, prefix: str):
        return self.subsystems.get(prefix)

    @property
    def _server_sources(self) -> dict:
        client_session = self.get_subsystem("client-session")
        return client_session.sources if client_session else {}

    @property
    def ui_driver(self):
        client_session = self.get_subsystem("client-session")
        return client_session.ui_driver if client_session else None

    def get_server_source(self, proto):
        if client_session := self.get_subsystem("client-session"):
            return client_session.get_server_source(proto)
        return None

    def get_sources_by_type(self, atype=object, exclude=None) -> Sequence:
        if client_session := self.get_subsystem("client-session"):
            return client_session.get_sources_by_type(atype, exclude)
        return ()

    def set_ui_driver(self, source) -> None:
        if client_session := self.get_subsystem("client-session"):
            client_session.set_ui_driver(source)

    def setting_changed(self, setting: str, value: Any) -> None:
        if settings := self.get_subsystem("setting"):
            settings.setting_changed(setting, value)

    def parse_hello(self, ss, caps: typedict) -> str | ConnectionMessage:
        return dispatch.first_truthy(self.subsystems, "parse_hello", ss, caps) or ""

    def add_new_client(self, ss, caps: typedict) -> None:
        dispatch.call(self.subsystems, "add_new_client", ss, caps)

    def send_initial_data(self, ss) -> None:
        dispatch.call(self.subsystems, "send_initial_data", ss)

    def client_startup_complete(self, ss) -> None:
        if client_session := self.get_subsystem("client-session"):
            client_session.client_startup_complete(ss)

    def sanity_checks(self, proto, caps: typedict) -> bool:
        if client_session := self.get_subsystem("client-session"):
            return client_session.sanity_checks(proto, caps)
        return True

    def disconnect_all(self) -> None:
        if client_session := self.get_subsystem("client-session"):
            client_session.disconnect_all()

    def cleanup_source(self, source) -> None:
        if client_session := self.get_subsystem("client-session"):
            client_session.do_cleanup_source(source)

    def last_client_exited(self) -> None:
        if client_session := self.get_subsystem("client-session"):
            client_session.last_client_exited()

    def cleanup(self) -> None:
        dispatch.call(self.subsystems, "cleanup", reverse=True)
        network = self.network
        network.cancel_touch_timer()
        network.cleanup_all_protocols()
        self.do_cleanup()
        network.cleanup_sockets()
        stop_asyncio_loop()
        netlog("cleanup() done for server core")

    def do_cleanup(self) -> None:
        # allow just a bit of time for the protocol packet flush
        sleep(0.1)

    def late_cleanup(self, stop=True) -> None:
        dispatch.call(self.subsystems, "late_cleanup", stop, reverse=True)
        network = self.network
        network.cleanup_all_protocols(force=True)
        network._potential_protocols = []
        from xpra.util.child_reaper import reaper_cleanup
        reaper_cleanup()

    def print_run_info(self) -> None:
        for run_info in get_run_info(f"{self.session_type} server"):
            log.info(run_info)

    def notify_new_user(self, ss) -> None:
        if notifications := self.get_subsystem("notifications"):
            notifications.notify_new_user(ss)

    # #####################################################################
    # packets / protocols:
    def init_packet_handlers(self) -> None:
        # the `network` subsystem adds its own unauthenticated packet handlers:
        self._default_packet_handlers = {
            "hello": self._process_hello,
        }
        netlog("initializing packet handlers for %s", list(self.subsystems))
        dispatch.call(self.subsystems, "init_packet_handlers")

    def cleanup_protocol(self, protocol: SocketProtocol):
        try:
            self.network._potential_protocols.remove(protocol)
        except ValueError:
            pass
        source = None
        if client_session := self.get_subsystem("client-session"):
            source = client_session.cleanup_client_protocol(protocol)
        dispatch.call(self.subsystems, "cleanup_protocol", protocol)
        return source

    # #####################################################################
    # hello / authentication:
    def send_version_info(self, proto: SocketProtocol, full: bool = False) -> None:
        version = version_str() if (full and FULL_INFO) else XPRA_VERSION.split(".", 1)[0]
        proto.send_now(Packet("hello", {"version": version}))
        # client is meant to close the connection itself, but just in case:
        GLib.timeout_add(5 * 1000, self.network.send_disconnect, proto, ConnectionMessage.DONE, "version sent")

    def _process_hello(self, proto: SocketProtocol, packet: Packet) -> None:
        capabilities = packet.get_dict(1)
        c = typedict(capabilities)
        if LOG_HELLO:
            netlog.info(f"hello from {proto}:")
            print_nested_dict(c, print_fn=netlog.info)
        # the client can lower the compression level, but not raise it above ours (CPU cost):
        proto.set_compression_level(max(0, min(self.compression_level, c.intget("compression_level", self.compression_level))))
        proto.enable_compressor_from_caps(c)
        if not proto.enable_encoder_from_caps(c):
            # this should never happen:
            # if we got here, we parsed a packet from the client!
            # (maybe the client used an encoding it claims not to support?)
            self.network.disconnect_client(proto, ConnectionMessage.PROTOCOL_ERROR, "failed to negotiate a packet encoder")
            return

        log("process_hello: capabilities=%s", capabilities)
        request = c.strget("request")
        if request in UNAUTHENTICATED_HELLO_REQUESTS:
            # these never proceed to authentication, even if they fail:
            self.do_handle_hello_request(request, proto, c)
            return

        # verify version:
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.network.disconnect_client(proto, ConnectionMessage.VERSION_ERROR, f"incompatible version: {verr!r}")
            proto.close()
            return
        # the client may require a more recent server version,
        # (peers that do not expose it are older than v7, the version check above rejects them)
        if perr := protocol_compat_check(c.inttupleget("protocol-version")):
            self.network.disconnect_client(proto, ConnectionMessage.VERSION_ERROR, f"incompatible version: {perr!r}")
            proto.close()
            return

        # try to auto upgrade to ssl:
        packet_types = c.strtupleget("packet-types", ())
        encryption_caps = c.dictget("encryption")
        conn = getattr(proto, "_conn", None)
        if self.network.ssl_upgrade and not encryption_caps and "ssl-upgrade" in packet_types and conn and conn.socktype in ("tcp",):
            options = conn.options
            if options.get("ssl-upgrade", "yes").lower() in TRUE_OPTIONS:
                ssl_options = self.network.get_ssl_socket_options(options)
                if cert := ssl_options.get("cert", ""):
                    log.info(f"sending ssl upgrade for {conn}")

                    # read the certificate from disk on the main thread, not the parse
                    # thread we are running on (which the seccomp filter forbids from
                    # opening files - see `docs/Usage/Seccomp.md`):
                    def send_ssl_upgrade() -> bool:
                        cert_data = load_binary_file(cert)
                        ssl_attrs = {"cert-data": cert_data}
                        proto.send_now(Packet("ssl-upgrade", ssl_attrs))
                        return False
                    GLib.idle_add(send_ssl_upgrade)
                    return

        # if we're here, then we should have read everything that was sent by the client,
        # including any data we potentially peeked at:
        disable_peek = getattr(conn, "disable_peek", noop)
        disable_peek()

        # this will call call_hello_oked if successful
        # it may also just send challenge packets,
        # in which case we'll end up here parsing the hello again.
        # Spawn the authentication thread from the main thread (via `idle_add`) rather
        # than from the network parse thread we are running on: authentication modules
        # are instantiated here and may open files, sockets or subprocesses, and a
        # thread spawned by the parse thread would inherit its seccomp filter
        # (see `docs/Usage/Seccomp.md`).
        def authenticate() -> bool:
            start_thread(self.verify_auth, "authenticate connection", daemon=True, args=(proto, packet, c))
            return False
        GLib.idle_add(authenticate)

    def verify_auth(self, proto: SocketProtocol, packet, c: typedict) -> None:
        if auth := self.get_subsystem("auth"):
            auth.verify_auth(proto, packet, c)
            return
        capabilities = packet.get_dict(1)
        self.call_hello_oked(proto, typedict(capabilities), {})

    def call_hello_oked(self, proto: SocketProtocol, c: typedict, auth_caps: dict) -> None:
        check_main_thread()
        try:
            if SIMULATE_SERVER_HELLO_ERROR:
                raise RuntimeError("Simulating a server error")
            self.hello_oked(proto, c, auth_caps)
        except ClientException as e:
            log("call_hello_oked(%s, %s, %s)", proto, Ellipsizer(c), auth_caps, exc_info=True)
            log.error("Error setting up new connection for")
            log.error(" %s:", proto)
            log.estr(e)
            self.network.disconnect_client(proto, ConnectionMessage.CONNECTION_ERROR, str(e))
        except Exception as e:
            # log exception but don't disclose internal details to the client
            log.error("server error processing new connection from %s: %s", proto, e, exc_info=True)
            self.network.disconnect_client(proto, ConnectionMessage.CONNECTION_ERROR, "error accepting new connection")

    def hello_oked(self, proto: SocketProtocol, c: typedict, auth_caps: dict) -> bool:
        if self._closing:
            self.network.disconnect_client(proto, ConnectionMessage.SERVER_EXIT, "server is shutting down")
            return True
        if request := c.strget("request"):
            return self.handle_hello_request(request, proto, c)
        if client_session := self.get_subsystem("client-session"):
            return client_session.hello_oked(proto, c, auth_caps)
        return False

    def handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        if not is_request_allowed(proto, request):
            msg = f"{request!r} requests are not enabled for this connection"
            log.error(f"Error: {msg}")
            self.network.send_disconnect(proto, ConnectionMessage.PERMISSION_ERROR, msg)
            return False
        return self.do_handle_hello_request(request, proto, caps)

    def do_handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        handler = self.hello_request_handlers.get(request)
        log("do_handle_hello_request(%s, %s, ..) handler=%s", request, proto, handler)
        if not handler:
            msg = f"no handler for hello request {request!r}"
            log.error(f"Error: {msg}")
            self.network.send_disconnect(proto, ConnectionMessage.PROTOCOL_ERROR, msg)
            return False
        if not handler(proto, caps):
            self.network.send_disconnect(proto, ConnectionMessage.PERMISSION_ERROR, f"hello request {request!r} rejected")
            return False
        return True

    def _handle_hello_request_connect_test(self, proto, caps: typedict) -> bool:
        ctr = caps.strget("connect_test_request")
        response = {"connect_test_response": ctr}
        proto.send_now(Packet("hello", response))
        return True

    def get_caps(self, source) -> dict:
        return dispatch.merge(self.subsystems, "get_caps", source)

    def make_hello(self, source) -> dict[str, Any]:
        now = time()
        capabilities = get_network_caps(FULL_INFO)
        capabilities |= self.get_caps(source)
        capabilities |= get_digest_caps()
        capabilities |= {
            "start_time": int(self.start_time),
            "current_time": int(now),
            "elapsed_time": int(now - self.start_time),
            "server.mode": self.session_type,
            # the minimum version we are willing to talk to:
            "protocol-version": MIN_PROTOCOL_VERSION,
        }
        if FULL_INFO > 0:
            capabilities["hostname"] = socket.gethostname()
        if source and "packet-types" in source.wants:
            packet_types = []
            packet_types += self.get_packet_types()
            packet_types += list(self._default_packet_handlers)
            capabilities["packet-types"] = packet_types
        if self.session_name:
            capabilities["session_name"] = self.session_name
        if source and "features" in source.wants:
            capabilities.update(self.get_server_features(source))
        return capabilities

    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        """Collect information that must be queried from the UI thread."""
        info: dict[str, Any] = {}
        subsystems = kwargs.get("subsystems", ())
        log("ServerCore.get_ui_info(%s, %s) subsystems=%s", proto, kwargs, subsystems)
        for prefix, sub in self.subsystems.items():
            if subsystems and prefix not in subsystems:
                continue
            fn = getattr(sub, "get_ui_info", None)
            if not callable(fn):
                continue
            try:
                # noinspection calling-non-callable
                mixin_info = fn(proto, **kwargs)
                log("%s.get_ui_info(%s, ..)=%r", prefix, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
            except Exception:
                log.warn("Error collecting UI info from %s", prefix, exc_info=True)
        return info

    def get_server_features(self, source=None) -> dict[str, Any]:
        readonly = self.readonly
        if source and hasattr(source, "server_enforced_readonly"):
            readonly = source.server_enforced_readonly()
        caps: dict[str, Any] = {
            "readonly-server": True,
            "readonly": readonly,
        }
        if FULL_INFO:
            from xpra.scripts.parsing import get_subcommands
            caps["subcommands"] = get_subcommands()
        if server_log := os.environ.get("XPRA_SERVER_LOG", ""):
            caps["server-log"] = server_log
        return caps

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        log("ServerCore.get_threaded_info(%s, %s)", proto, kwargs)
        start = monotonic()
        # this function is for non UI thread info, see also: `get_ui_info`
        info = {
            "subsystems": tuple(self.subsystems.keys()),
        }
        subsystems = kwargs.get("subsystems", ())
        for prefix, sub in self.subsystems.items():
            if subsystems and prefix not in subsystems:
                continue
            with log.trap_error(f"Error collecting information from {prefix}"):
                cstart = monotonic()
                mixin_info = sub.get_info(proto)
                # log("%s.get_info(%s)=%r", prefix, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
                cend = monotonic()
                log("%s.get_info(%s) took %ims", prefix, proto, int(1000 * (cend - cstart)))

        if self.get_subsystem("info"):
            authenticated = bool(proto and proto.authenticators)
            socktype = getattr(getattr(proto, "_conn", None), "socktype", "")
            local = socktype in ("socket", "named-pipe")
            log("get_threaded_info(%s, %s) authenticated=%s, subsystems=%s, local=%s",
                proto, kwargs, authenticated, subsystems, local)
            full = FULL_INFO > 0 or authenticated or local
            server_info = self.get_server_info(full)
            merge_dicts(server_info, info)
            info = server_info
            if full and (not subsystems or "threads" in subsystems):
                from xpra.server.subsystem.info import get_thread_info
                info["threads"] = get_thread_info(proto)

        end = monotonic()
        log("ServerCore.get_info took %ims", (end - start) * 1000)
        return info

    def get_server_info(self, full=False) -> dict[str, Any]:
        if info := self.get_subsystem("info"):
            return info.get_server_info(full)
        return {}

    def get_session_id_info(self) -> dict[str, Any]:
        if id_subsystem := self.get_subsystem("id"):
            return id_subsystem.get_session_id_info()
        return {}

    def get_minimal_server_info(self) -> dict[str, Any]:
        if info := self.get_subsystem("info"):
            return info.get_minimal_server_info()
        return {}

    ######################################################################
    # packet handling:
    def process_packet(self, proto, packet) -> None:
        authenticated = bool(self.get_server_source(proto))
        super().dispatch_packet(proto, packet, authenticated)

    def handle_invalid_packet(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        detached = ss is None and proto not in self.network._potential_protocols
        if detached:
            netlog("packet from detached protocol %s: %s", proto, packet)
        elif not self._closing and not proto.is_closed() and (ss is None or not ss.is_closed()):
            netlog("invalid packet: %s", packet)
            packet_type = packet.get_type()
            netlog.error(f"Error: unknown or invalid packet type {packet_type!r}")
            netlog.error(f" received from {proto}")
        if not ss:
            proto.close()
