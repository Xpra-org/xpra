# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import errno
import socket
import signal
import threading
from weakref import WeakKeyDictionary
from time import sleep, time, monotonic
from types import FrameType
from typing import Any, NoReturn
from collections.abc import Callable, Sequence, Iterable

from xpra.util.version import XPRA_VERSION, version_str, version_compat_check
from xpra.scripts.server import deadly_signal
from xpra.exit_codes import ExitValue, ExitCode
from xpra.server import ServerExitMode
from xpra.server import features
from xpra.server.auth import AuthenticatedServer
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS, parse_bool_or
from xpra.net.common import (
    MAX_PACKET_SIZE, SSL_UPGRADE, PACKET_TYPES,
    is_request_allowed, Packet, has_websocket_handler, HttpResponse, HTTP_UNSUPORTED,
)
from xpra.net.digest import get_caps as get_digest_caps
from xpra.net.socket_util import (
    PEEK_TIMEOUT_MS, SOCKET_PEEK_TIMEOUT_MS,
    setup_local_sockets, add_listen_socket, accept_connection, guess_packet_type,
    peek_connection, close_sockets, SocketListener, socket_fast_read,
)
from xpra.net.bytestreams import (
    Connection, SSLSocketConnection, SocketConnection,
    log_new_connection, pretty_socket, SOCKET_TIMEOUT
)
from xpra.net.net_util import get_network_caps, import_netifaces, get_all_ips
from xpra.net.protocol.factory import get_server_protocol_class
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.net.protocol.constants import CONNECTION_LOST, GIBBERISH, INVALID
from xpra.net.digest import get_salt, gendigest
from xpra.platform import set_name, threaded_server_init
from xpra.platform.paths import get_app_dir, get_system_conf_dirs, get_user_conf_dirs
from xpra.os_util import (
    force_quit, POSIX,
    get_username_for_uid, get_hex_uuid, getuid, gi_import,
)
from xpra.util.system import register_SIGUSR_signals
from xpra.util.io import load_binary_file, find_libexec_command
from xpra.util.background_worker import add_work_item, quit_worker
from xpra.util.thread import start_thread
from xpra.common import (
    LOG_HELLO, FULL_INFO, DEFAULT_XDG_DATA_DIRS,
    noop, ConnectionMessage, noerr, init_memcheck, subsystem_name,
)
from xpra.util.pysystem import dump_all_frames
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, print_nested_dict, nicestr, strtobytes, hexstr
from xpra.util.env import envint, envbool, envfloat, first_time
from xpra.log import Logger

# pylint: disable=import-outside-toplevel

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")
ssllog = Logger("ssl")
httplog = Logger("http")
wslog = Logger("websocket")

main_thread = threading.current_thread()

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_MAX_CONCURRENT_CONNECTIONS", 100)
SIMULATE_SERVER_HELLO_ERROR = envbool("XPRA_SIMULATE_SERVER_HELLO_ERROR", False)
SERVER_SOCKET_TIMEOUT = envfloat("XPRA_SERVER_SOCKET_TIMEOUT", 0.1)
UNAUTHENTICATED_HELLO_REQUESTS = tuple(
    x.strip() for x in
    os.environ.get("XPRA_UNAUTHENTICATED_HELLO_REQUESTS", "version,connect_test,id").split(",") if x.strip()
)

SYSCONFIG = envbool("XPRA_SYSCONFIG", FULL_INFO > 1)
SHOW_NETWORK_ADDRESSES = envbool("XPRA_SHOW_NETWORK_ADDRESSES", True)
INIT_THREAD_TIMEOUT = envint("XPRA_INIT_THREAD_TIMEOUT", 10)
HTTP_HTTPS_REDIRECT = envbool("XPRA_HTTP_HTTPS_REDIRECT", True)
SSL_PEEK = envbool("XPRA_SSL_PEEK", True)


# class used to distinguish internal errors
# which should not be shown to the client,
# from useful messages we do want to pass on
class ClientException(Exception):
    pass


def force_close_connection(conn) -> None:
    try:
        conn.close()
    except OSError:
        netlog("close_connection()", exc_info=True)


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server.subsystem.control import ControlHandler
    from xpra.server.glib_server import GLibServer
    from xpra.server.subsystem.platform import PlatformServer
    from xpra.server.subsystem.daemon import DaemonServer
    from xpra.server.subsystem.sessionfiles import SessionFilesServer
    from xpra.server.subsystem.splash import SplashServer
    from xpra.server.subsystem.id import IDServer
    from xpra.server.subsystem.info import InfoServer
    from xpra.server.subsystem.version import VersionServer
    classes: list[type] = [
        GLibServer, PlatformServer, DaemonServer, SessionFilesServer,
        AuthenticatedServer, ControlHandler, SplashServer,
        IDServer, InfoServer, VersionServer,
    ]
    from xpra.server import features
    if features.mdns:
        from xpra.server.subsystem.mdns import MdnsServer
        classes.append(MdnsServer)
    return tuple(classes)


SERVER_BASES = get_server_base_classes()
ServerBaseClass = type("ServerBaseClass", SERVER_BASES, {})
log("ServerBaseClass%s", SERVER_BASES)
SIGNALS: dict[str, int] = {}
for base_class in SERVER_BASES:
    SIGNALS.update(getattr(base_class, "__signals__", {}))
SIGNALS.update({
    "init-thread-ended": 0,
    "running": 0,
})


# noinspection PyMethodMayBeStatic
class ServerCore(ServerBaseClass):
    """
        This is the simplest base class for servers.
        It only handles the connection layer:
        authentication and the initial handshake.
    """
    __signals__ = SIGNALS

    def __init__(self):
        log("ServerCore.__init__()")
        for bc in SERVER_BASES:
            bc.__init__(self)
        self.start_time = time()
        self.hello_request_handlers.update({
            "connect_test": self._handle_hello_request_connect_test,
            "screenshot": self._handle_hello_request_screenshot,
        })
        self.uuid = ""
        self.session_type: str = "unknown"
        self._closing: bool = False
        self._exit_mode = ServerExitMode.UNSET
        # networking bits:
        self.sockets: list[SocketListener] = []
        self._potential_protocols: list[SocketProtocol] = []
        self._rfb_upgrade: int = 0
        self._ssl_attributes: dict = {}
        self._accept_timeout: int = SOCKET_TIMEOUT + 1
        self.ssl_mode: str = ""
        self.ssl_upgrade = False
        self.websocket_upgrade = has_websocket_handler()
        self.ssh_upgrade = False
        self.rdp_upgrade = False
        self.http = False
        self._html: bool = False
        self._www_dir: str = ""
        self._http_headers_dirs: list[str] = []
        self.socket_cleanup: list[Callable] = []
        self.socket_verify_timer: WeakKeyDictionary[SocketProtocol, int] = WeakKeyDictionary()
        self.socket_rfb_upgrade_timer: WeakKeyDictionary[SocketProtocol, int] = WeakKeyDictionary()
        self._max_connections: int = MAX_CONCURRENT_CONNECTIONS
        self._socket_timeout: float = SERVER_SOCKET_TIMEOUT
        self._ws_timeout: int = 5
        self._socket_dir: str = ""
        self._socket_dirs: list = []
        self.unix_socket_paths: list[str] = []
        self.touch_timer: int = 0
        self.session_files: list[str] = [
            "cmdline", "server.env", "config", "server.log*",
            # notifications may use a TMP dir:
            "tmp/*", "tmp",
        ]
        self.session_name = ""

        # Features:
        self.readonly = False
        self.compression_level = 1
        self.exit_with_client = False

        self.init_thread = None

        self._default_packet_handlers: dict[str, Callable] = {}

    def init(self, opts) -> None:
        log("ServerCore.init(%s)", opts)
        self.session_name = str(opts.session_name)
        set_name("Xpra", self.session_name or "Xpra")
        self.unix_socket_paths = []
        self._socket_dir = opts.socket_dir or ""
        if not self._socket_dir and opts.socket_dirs:
            self._socket_dir = opts.socket_dirs[0]
        self._socket_dirs = opts.socket_dirs
        self.compression_level = opts.compression_level
        self.exit_with_client = opts.exit_with_client
        self.readonly = opts.readonly
        self.http = opts.http
        self.websocket_upgrade = opts.websocket_upgrade
        self.ssh_upgrade = opts.ssh_upgrade
        self.rdp_upgrade = opts.rdp_upgrade
        if self.http:
            self.init_html_proxy(opts)
        for bc in SERVER_BASES:
            bc.init(self, opts)
        self.init_ssl(opts)

    def init_ssl(self, opts) -> None:
        self.ssl_mode = opts.ssl
        try:
            from xpra.net.ssl.file import get_ssl_attributes
        except ImportError as e:
            netlog("init_ssl(..) no ssl: %s", e)
            self.ssl_upgrade = False
            return
        self._ssl_attributes = get_ssl_attributes(opts, True)
        netlog("init_ssl(..) ssl attributes=%s", self._ssl_attributes)
        self.ssl_upgrade = opts.ssl.lower() not in FALSE_OPTIONS

    def setup(self) -> None:
        self.init_uuid()
        for bc in SERVER_BASES:
            bc.setup(self)
        self.start_listen_sockets()
        self.init_control_commands()
        self.init_packet_handlers()
        # for things that can take longer:
        self.init_thread = start_thread(target=self.threaded_init, name="server-init-thread")

    def init_control_commands(self) -> None:
        self.add_default_control_commands(features.control)

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
        init_memcheck()
        add_work_item(self.print_run_info)
        self.threaded_setup()
        self.emit("init-thread-ended")

    def threaded_setup(self) -> None:
        log("threaded_setup() servercore start")
        for c in SERVER_BASES:
            with log.trap_error("Error during threaded setup of %s", c):
                c.threaded_setup(self)
        log("threaded_setup() servercore end")

    def wait_for_threaded_init(self) -> None:
        if not self.init_thread:
            # looks like we didn't make it as far as calling setup()
            log("wait_for_threaded_init() no init thread")
            return
        log("wait_for_threaded_init() %s.is_alive()=%s", self.init_thread, self.init_thread.is_alive())
        if self.init_thread.is_alive():
            log("waiting for initialization thread to complete")
            self.init_thread.join(INIT_THREAD_TIMEOUT)
            if self.init_thread.is_alive():
                log.warn("Warning: initialization thread is still active")

    def get_subsystems(self) -> list[str]:
        return [subsystem_name(c) for c in SERVER_BASES]

    def run(self) -> ExitValue:
        self.install_signal_handlers(self.signal_quit)
        GLib.idle_add(self.server_is_ready)
        self.do_run()
        log("run()")
        return 0

    def server_is_ready(self) -> None:
        self.emit("running")
        log.info("xpra is ready.")
        noerr(sys.stdout.flush)

    def cleanup(self) -> None:
        for bc in SERVER_BASES:
            bc.cleanup(self)
        self.cancel_touch_timer()
        self.cleanup_all_protocols()
        self.do_cleanup()
        self.cleanup_sockets()
        netlog("cleanup() done for server core")

    def do_cleanup(self) -> None:
        # allow just a bit of time for the protocol packet flush
        sleep(0.1)

    def late_cleanup(self, stop=True) -> None:
        for bc in SERVER_BASES:
            bc.late_cleanup(self, stop)
        self.cleanup_all_protocols(force=True)
        self._potential_protocols = []
        from xpra.util.child_reaper import reaper_cleanup
        reaper_cleanup()

    def cleanup_sockets(self) -> None:
        sockets = self.sockets
        self.sockets = []
        close_sockets(sockets)

    def init_uuid(self) -> None:
        # Define a server UUID if needed:
        self.uuid = os.environ.get("XPRA_PROXY_START_UUID", "") or self.get_server_uuid() or get_hex_uuid()
        log(f"server uuid is {self.uuid}")

    def get_server_uuid(self) -> str:
        return ""

    def init_html_proxy(self, opts) -> None:
        httplog(f"init_html_proxy(..) options: html={opts.html!r}")
        # opts.html can contain a boolean, "auto" or the path to the webroot
        www_dir = ""
        html = opts.html or ""
        if html and os.path.isabs(html):
            www_dir = html
            self._html = True
        elif not html or (html.lower() in FALSE_OPTIONS or html.lower() in TRUE_OPTIONS or html.lower() == "auto"):
            self._html = parse_bool_or("html", html)
        else:
            # assume that the html option is a request to open a browser
            self._html = True
            # find a socket we can connect the browser to:
            for mode, bind in {
                "ws": opts.bind_ws,
                "wss": opts.bind_wss,
                "tcp": opts.bind_tcp,
                "ssl": opts.bind_ssl,
            }.items():
                if bind:  # ie: ["0.0.0.0:10000", "127.0.0.1:20000"]
                    from xpra.net.common import open_html_url
                    # open via timeout_add so that the server is running by then,
                    # plus a slight delay so that it can settle down:
                    GLib.timeout_add(1000, open_html_url, html, mode, bind[0])
                    break
            else:
                log.warn("Warning: cannot open html client in a browser")
                log.warn(" no compatible socket found")
        if self._html is not False:  # True or None (for "auto")
            if not (opts.bind_tcp or opts.bind_ws or opts.bind_wss or opts.bind or opts.bind_ssl):
                # we need a socket!
                if self._html:
                    # html was enabled, so log an error:
                    httplog.error("Error: cannot use the html server without a socket")
                self._html = False
        httplog("init_html_proxy(..) html=%s", self._html)
        if not has_websocket_handler():
            if self._html is None:  # auto mode
                httplog.info("html server unavailable, cannot find websocket module")
            elif self._html:
                httplog.error("Error: cannot import websocket connection handler:")
                httplog.error(" the html server will not be available")
            self._html = False
            self.websocket_upgrade = False
        # make sure we have the web root:
        from xpra.platform.paths import get_resources_dir
        if www_dir:
            self._www_dir = str(www_dir)
        else:
            # this is the default value which will be shown in the warning if we don't find a valid one:
            self._www_dir = os.path.abspath(os.path.join(get_resources_dir(), "www"))
            dirs: dict[str, str] = {
                get_resources_dir(): "html5",
                get_resources_dir(): "www",
                get_app_dir(): "www",
            }
            if POSIX:
                xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS)
                for d in xdg_data_dirs.split(":"):
                    dirs[d] = "www"
                for d in ("/usr/share/xpra", "/usr/local/share/xpra"):
                    dirs[d] = "www"
                dirs["/var/www/xpra"] = "www"
            for ad, d in dirs.items():
                www_dir = os.path.abspath(os.path.join(ad, d))
                if os.path.exists(www_dir):
                    self._www_dir = www_dir
                    httplog("found html5 client in '%s'", www_dir)
                    break
        if not os.path.exists(self._www_dir) and self._html is not False:
            httplog.error("Error: cannot find the html web root")
            httplog.error(f" {self._www_dir!r} does not exist")
            httplog.error(" install the `xpra-html5` package")
            httplog.error(" or turn off the builtin web server using `html=no`")
            self._www_dir = "/usr/share/xpra/www/"
            self._html = False
        if self._html is not False:
            httplog.info(f"serving html content from {self._www_dir!r}")
            self._http_headers_dirs = []
            for d in get_system_conf_dirs():
                self._http_headers_dirs.append(os.path.join(d, "http-headers"))
            if not POSIX or getuid() > 0:
                for d in get_user_conf_dirs():
                    self._http_headers_dirs.append(os.path.join(d, "http-headers"))
            self._http_headers_dirs.append(os.path.abspath(os.path.join(self._www_dir, "../http-headers")))
            self._html = True

    def print_run_info(self) -> None:
        from xpra.common import get_run_info
        for run_info in get_run_info(f"{self.session_type} server"):
            log.info(run_info)

    def notify_new_user(self, ss) -> None:
        pass

    # #####################################################################
    # sockets / connections / packets:
    def init_sockets(self, sockets: list[SocketListener]) -> None:
        self.sockets += sockets

    def init_local_sockets(self, opts, display_name: str, clobber: bool) -> None:
        uid = int(opts.uid)
        gid = int(opts.gid)
        username = get_username_for_uid(uid)
        session_dir = os.environ.get("XPRA_SESSION_DIR", "")
        netlog(f"init_local_sockets(.., {clobber}) {uid=}, {gid=}, {username=!r}, {session_dir=!r}")
        # setup unix domain socket:
        local_sockets = setup_local_sockets(
            opts.bind,  # noqa: F821
            opts.socket_dir, opts.socket_dirs, session_dir,  # noqa: F821
            display_name, clobber,  # noqa: F821
            opts.mmap_group, opts.socket_permissions,  # noqa: F821
            username, uid, gid)
        netlog(f"done setting up local sockets: {local_sockets}")
        self.sockets += local_sockets

        # all unix domain sockets:
        ud_paths = [sock.address for sock in local_sockets if sock.socktype in ("socket", "named-pipe")]
        if ud_paths:
            os.environ["XPRA_SERVER_SOCKET"] = ud_paths[0]
            if opts.forward_xdg_open:
                xdg_open = find_libexec_command("xdg-open")
                if xdg_open:
                    libexec_dir = os.path.dirname(xdg_open)
                    os.environ["PATH"] = libexec_dir + os.pathsep + os.environ.get("PATH", "")
        else:
            log.warn("Warning: no local server sockets,")
            if opts.forward_xdg_open:
                log.warn(" forward-xdg-open cannot be enabled")
            log.warn(" non-embedded ssh connections will not be available")

    def can_upgrade(self, socktype: str, tosocktype: str, options: dict[str, str]) -> bool:
        to_option_str = options.get(tosocktype, "")
        to_option = to_option_str.lower() in TRUE_OPTIONS
        netlog(f"can_upgrade%s {to_option_str=}, {to_option}", (socktype, tosocktype, options))
        if tosocktype in ("ws", "wss") and not has_websocket_handler():
            return False
        if tosocktype == "rfb":
            # only available with the RFBServer
            return getattr(self, "_rfb_upgrade", False)
        if tosocktype == "rdp":
            return self.rdp_upgrade
        if socktype in ("tcp", "socket", "vsock", "named-pipe"):
            if tosocktype == "ssl":
                if to_option_str:
                    return to_option
                return self.ssl_upgrade
            if tosocktype == "ws":
                if to_option_str:
                    return to_option
                return self.websocket_upgrade
            if tosocktype == "wss":
                if to_option_str:
                    return to_option
                return self.websocket_upgrade and self.ssl_upgrade
        if socktype == "ws" and tosocktype == "wss":
            if to_option_str:
                return to_option
            return self.ssl_upgrade
        if socktype == "ssl" and tosocktype == "wss":
            if to_option_str:
                return to_option
            return self.websocket_upgrade
        if tosocktype == "ssh":
            if to_option_str:
                return to_option
            return self.ssh_upgrade
        return False

    def start_listen_sockets(self) -> None:
        # All right, we're ready to accept customers:
        netlog("start_listen_sockets() sockets=%s", self.sockets)
        for listener in self.sockets:
            netlog(" add_listen_socket: %s", listener)
            GLib.idle_add(self.add_listen_socket, listener)
            address = listener.address
            if listener.socktype == "socket" and address:
                if address.startswith("@"):
                    # abstract sockets can't be 'touch'ed
                    continue
                path = os.path.abspath(address)
                self.unix_socket_paths.append(path)
                netlog("added unix socket path: %s", path)
        if self.unix_socket_paths:
            self.touch_sockets()
            self.touch_timer = GLib.timeout_add(60 * 1000, self.touch_sockets)

    def cancel_touch_timer(self) -> None:
        tt = self.touch_timer
        if tt:
            self.touch_timer = 0
            GLib.source_remove(tt)

    def touch_sockets(self) -> bool:
        netlog("touch_sockets() unix socket paths=%s", self.unix_socket_paths)
        for sockpath in self.unix_socket_paths:
            if sockpath.startswith("@"):
                continue
            if not os.path.exists(sockpath):
                if first_time(f"missing-socket-{sockpath}"):
                    log.warn("Warning: the unix domain socket cannot be found:")
                    log.warn(" '%s'", sockpath)
                    log.warn(" was it deleted by mistake?")
                continue
            try:
                os.utime(sockpath, None)
            except OSError as e:
                if first_time(f"touch-{sockpath}"):
                    netlog.warn(f"Warning: unable to set modified time on {sockpath!r}: {e}")
                netlog("touch_sockets() error on %s", sockpath, exc_info=True)
        return True

    def init_packet_handlers(self) -> None:
        self._default_packet_handlers = {
            "hello": self._process_hello,
            "disconnect": self._process_disconnect,
            "ssl-upgrade": self._process_ssl_upgrade,
            CONNECTION_LOST: self._process_connection_lost,
            GIBBERISH: self._process_gibberish,
            INVALID: self._process_invalid,
        }
        netlog("initializing packet handlers for %s", SERVER_BASES)
        for c in SERVER_BASES:
            c.init_packet_handlers(self)

    def cleanup_all_protocols(self, reason: str | ConnectionMessage = "", force=False) -> None:
        protocols = self.get_all_protocols()
        self.cleanup_protocols(protocols, reason=reason, force=force)

    def get_all_protocols(self) -> Sequence[SocketProtocol]:
        return tuple(self._potential_protocols)

    def cleanup_protocols(self, protocols, reason: str | ConnectionMessage = "", force=False) -> None:
        if not reason:
            reason = {
                ServerExitMode.EXIT: ConnectionMessage.SERVER_EXIT,
                ServerExitMode.UPGRADE: ConnectionMessage.SERVER_UPGRADE,
            }.get(self._exit_mode, ConnectionMessage.SERVER_SHUTDOWN)
        netlog("cleanup_protocols(%s, %s, %s)", protocols, reason, force)
        for protocol in protocols:
            if force:
                self.force_disconnect(protocol)
            else:
                self.disconnect_protocol(protocol, reason)

    def add_listen_socket(self, listener: SocketListener) -> None:
        netlog("add_listen_socket(%s)", listener)
        add_listen_socket(listener, self, self._new_connection)

    def _new_connection(self, listener: SocketListener, handle=0) -> bool:
        """
            Accept the new connection,
            verify that there aren't too many,
            start a thread to dispatch it to the correct handler.
        """
        log("_new_connection%s", (listener, handle))
        if self._closing:
            netlog("ignoring new connection during shutdown")
            return False
        socktype = listener.socktype
        if socktype == "named-pipe":
            from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
            conn: Connection = NamedPipeConnection(listener.socket.pipe_name, handle, listener.options)
            netlog.info("New %s connection received on %s", socktype, conn.target)
            self.make_protocol(socktype, conn, listener.options)
            return True

        conn = accept_connection(listener, self._socket_timeout)
        if conn is None:
            return True
        # limit number of concurrent network connections:
        if socktype != "socket" and len(self._potential_protocols) >= self._max_connections:
            netlog.error("Error: too many connections (%i)", len(self._potential_protocols))
            netlog.error(" ignoring new one: %s", conn.endpoint)
            force_close_connection(conn)
            return True
        # from here on, we run in a thread, so we can poll (peek does)
        start_thread(self.handle_new_connection, f"new-{socktype}-connection", True,
                     args=(listener, conn))
        return True

    def new_conn_err(self, conn, sock, socktype: str, address, packet_type: str, msg="") -> None:
        # not an xpra client
        netlog("new_conn_err", exc_info=True)
        log_fn = netlog.debug if packet_type == "http" else netlog.error
        log_fn("Error: %s connection failed:", socktype)
        if conn.remote:
            log_fn(" packet from %s", pretty_socket(conn.remote))
        if address:
            log_fn(" received on %s", pretty_socket(address))
        if packet_type:
            log_fn(" this packet looks like a '%s' packet", packet_type)
        else:
            log_fn(" invalid packet format, not an xpra client?")
        if msg:
            log_fn(" %s", msg)

        if packet_type == "xpra":
            # try xpra packet format:
            from xpra.net.packet_encoding import pack_one_packet
            packet_data = pack_one_packet(("disconnect", "invalid protocol for this port"))
        elif packet_type == "http":
            # HTTP 400 error:
            packet_data = HTTP_UNSUPORTED
        else:
            packet_data = b"disconnect: connection setup failed"
            if msg:
                packet_data += b", %s?" % strtobytes(msg)
            packet_data += b"\n"
        try:
            # default to plain text:
            sock.settimeout(1)
            conn.write(packet_data)
        except IOError as e:
            netlog("error sending %r: %s", packet_data, e)
        GLib.timeout_add(500, force_close_connection, conn)

    def peek_connection(self, conn) -> bytes:
        timeout = PEEK_TIMEOUT_MS
        if conn.socktype == "rfb":
            # rfb does not send any data, waits for a server packet
            # so don't bother waiting for something that should never come:
            timeout = 0
        elif conn.socktype == "socket":
            timeout = SOCKET_PEEK_TIMEOUT_MS
        peek_data = b""
        if timeout > 0:
            peek_data = peek_connection(conn, timeout)
        return peek_data

    def guess_packet_type(self, peek_data: bytes):
        if peek_data:
            line1 = peek_data.split(b"\n")[0]
            netlog("socket peek hex=%s", hexstr(peek_data[:128]))
            netlog("socket peek line1=%s", Ellipsizer(line1))
        packet_type = guess_packet_type(peek_data)
        netlog("guess_packet_type(..)=%s", packet_type)
        return packet_type

    def handle_new_connection(self, listener: SocketListener, conn) -> None:
        try:
            self.do_handle_new_connection(listener, conn)
        except ValueError as e:
            sock = conn._socket
            self.new_conn_err(conn, sock, conn.socktype, conn.remote, "", str(e))
        except OSError as e:
            netlog("handle_new_connection(%s, %s) socket wrapping failed", listener, conn, exc_info=True)
            sock = conn._socket
            self.new_conn_err(conn, sock, conn.socktype, conn.remote, "", str(e))

    def do_handle_new_connection(self, listener: SocketListener, conn) -> None:
        """
            Use peek to decide what sort of connection this is,
            and start the appropriate handler for it.
        """
        socket_options = listener.options
        sock = conn._socket
        address = conn.remote
        socktype = conn.socktype
        peername = conn.endpoint

        sockname = sock.getsockname()
        target = peername or sockname
        sock.settimeout(self._socket_timeout)

        netlog("handle_new_connection%s sockname=%s, target=%s", (listener, conn), sockname, target)
        # peek so we can detect invalid clients early,
        # or handle non-xpra / wrapped traffic:
        peek_data = self.peek_connection(conn)
        netlog("socket peek=%s", Ellipsizer(peek_data, limit=512))
        packet_type = self.guess_packet_type(peek_data)

        def can_upgrade_to(to_socktype: str) -> bool:
            return self.can_upgrade(socktype, to_socktype, socket_options)

        def conn_err(msg: str) -> tuple[bool, Any, bytes]:
            self.new_conn_err(conn, conn._socket, socktype, address, packet_type, msg)
            return False, None, b""

        if socktype in ("ssl", "wss"):
            # verify that this isn't plain HTTP / xpra:
            if packet_type not in ("ssl", ""):
                conn_err(f"packet is {packet_type!r} and not ssl")
                return
            # always start by wrapping with SSL:
            ssl_conn = self.ssl_wrap(conn, socket_options)
            if not ssl_conn:
                return
            http = socktype == "wss"
            can_peek = SSL_PEEK and (self.ssl_mode.lower() in TRUE_OPTIONS or self.ssl_mode == "auto")
            if can_peek and socktype == "ssl" and can_upgrade_to("wss"):
                # look for HTTPS request to handle:
                line1 = peek_data.split(b"\n")[0]
                if line1.find(b"HTTP/") > 0 or peek_data.find(b"\x08http/") > 0:
                    http = True
                else:
                    ssl_conn.enable_peek()
                    peek_data = peek_connection(ssl_conn)
                    line1 = peek_data.split(b"\n")[0]
                    http = line1.find(b"HTTP/") > 0
                    netlog("looking for 'HTTP' in %r: %s", line1, http)
            if http:
                if not self.http:
                    conn_err("the builtin http server is not enabled")
                    return
                self.start_http_socket(socktype, ssl_conn, socket_options, True, peek_data)
                return
            ssl_conn._socket.settimeout(self._socket_timeout)
            log_new_connection(ssl_conn, address)
            self.make_protocol(socktype, ssl_conn, socket_options)
            return

        if socktype == "ws":
            self.handle_ws_socket(conn, socket_options, peek_data)
            return

        if socktype == "rfb":
            self.handle_rfb_connection(conn)
            return

        if socktype == "rdp":
            self.handle_rdp_connection(conn)
            return

        if socktype == "ssh":
            conn = self.handle_ssh_connection(conn, socket_options)
            if not conn:
                return
            peek_data, packet_type = b"", ""

        if socktype in ("tcp", "socket", "named-pipe") and peek_data:
            # see if the packet data is actually xpra or something else
            # that we need to handle via a SSL wrapper or the websocket adapter:
            cont, conn, peek_data = self.may_wrap_socket(conn, socktype, address, socket_options, peek_data)
            netlog("may_wrap_socket(..)=(%s, %s, %r)", cont, conn, Ellipsizer(peek_data))
            if not cont:
                return
            packet_type = guess_packet_type(peek_data)

        pre_read = []
        if socktype == "socket" and not peek_data:
            # try to read from this socket,
            # so short-lived probes don't go through the whole protocol instantiation
            pre = socket_fast_read(conn)
            if not pre:
                netlog("closing %s connection: no data", socktype)
                force_close_connection(conn)
                return
            pre_read.append(pre)
            packet_type = guess_packet_type(pre)

        if packet_type not in ("xpra", ""):
            conn_err("packet type is not xpra")
            return

        # get the new socket object as we may have wrapped it with ssl:
        sock = getattr(conn, "_socket", sock)
        sock.settimeout(self._socket_timeout)
        log_new_connection(conn, address)
        proto = self.make_protocol(socktype, conn, socket_options, pre_read=pre_read)
        if socktype == "tcp" and not peek_data and self._rfb_upgrade > 0:
            t = GLib.timeout_add(self._rfb_upgrade * 1000, self.try_upgrade_to_rfb, proto)
            self.socket_rfb_upgrade_timer[proto] = t

    def ssl_wrap(self, conn, socket_options: dict[str, Any]) -> SSLSocketConnection | None:
        sock = conn._socket
        socktype = conn.socktype
        ssl_sock = self._ssl_wrap_socket(socktype, sock, socket_options)
        ssllog("ssl wrapped socket(%s)=%s", sock, ssl_sock)
        if ssl_sock is None:
            return None
        address = conn.remote
        peername = conn.endpoint
        sockname = ssl_sock.getsockname()
        target = peername or sockname
        ssl_conn = SSLSocketConnection(ssl_sock, sockname, address, target, socktype, socket_options=socket_options)
        ssllog("ssl_wrap(%s, %s)=%s", conn, socket_options, ssl_conn)
        return ssl_conn

    def get_ssl_socket_options(self, socket_options: dict) -> dict[str, Any]:
        ssllog(f"get_ssl_socket_options({socket_options})")
        kwargs = {k.replace("-", "_"): v for k, v in self._ssl_attributes.items()}
        for k, v in socket_options.items():
            # options use '-' but attributes and parameters use '_':
            k = k.replace("-", "_")
            if k.startswith("ssl_"):
                k = k[4:]
                kwargs[k] = v
        ssllog(f"get_ssl_socket_options({socket_options})={kwargs}")
        return kwargs

    def _ssl_wrap_socket(self, socktype: str, sock, socket_options):
        ssllog("ssl_wrap_socket(%s, %s, %s)", socktype, sock, socket_options)
        kwargs = self.get_ssl_socket_options(socket_options)
        try:
            from xpra.net.ssl.socket import ssl_wrap_socket
            ssl_sock = ssl_wrap_socket(sock, **kwargs)
            ssllog("_ssl_wrap_socket(%s, %s)=%s", sock, kwargs, ssl_sock)
            if ssl_sock is None:
                # None means EOF! (we don't want to import ssl bits here)
                ssllog("ignoring SSL EOF error")
            return ssl_sock
        except Exception as e:
            ssllog("SSL error", exc_info=True)
            ssl_paths = [socket_options.get(x, kwargs.get(x)) for x in ("ssl-cert", "ssl-key")]
            cpaths = csv(f"{x!r}" for x in ssl_paths if x)
            log_fn = log.error if first_time(f"ssl-wrap-{socktype}-{socket_options}") else log.debug
            log_fn("Error: failed to create SSL socket")
            log_fn(" from %s socket: %s", socktype, sock)
            if not cpaths:
                log_fn(" no certificate paths specified")
            else:
                log_fn(" check your certificate paths: %s", cpaths)
            log_fn(" %s", e)
            noerr(sock.close)
            return None

    def handle_ws_socket(self, conn, socket_options: dict[str, Any], peek_data: bytes) -> None:
        packet_type = self.guess_packet_type(peek_data)
        if peek_data:
            if packet_type == "ssl" and self.can_upgrade(conn.socktype, "wss", socket_options):
                ssllog("ws socket receiving ssl, upgrading to wss")
                conn = self.ssl_wrap(conn, socket_options)
                if conn is None:
                    return
            elif packet_type not in (None, "http"):
                raise ValueError(f"packet type is {packet_type!r} and not http")
        self.start_http_socket(conn.socktype, conn, socket_options, False, peek_data)

    def handle_ssh_connection(self, conn, socket_options: dict[str, Any]):
        from xpra.server.ssh import make_ssh_server_connection, log as sshlog
        socktype = conn.socktype_wrapped
        none_auth = not self.auth_classes[socktype]
        sshlog("handle_ssh_connection(%s, %s) socktype wrapped=%s", conn, socket_options, socktype)

        def ssh_password_authenticate(username, password) -> bool:
            if not POSIX or getuid() != 0:
                import getpass
                sysusername = getpass.getuser()
                if sysusername != username:
                    sshlog.warn("Warning: ssh password authentication failed,")
                    sshlog.warn(" username does not match:")
                    sshlog.warn(" expected '%s', got '%s'", sysusername, username)
                    return False
            auth_modules = self.make_authenticators(socktype, {"username": username}, conn)
            sshlog("ssh_password_authenticate auth_modules(%s, %s)=%s", username, "*" * len(password), auth_modules)
            for auth in auth_modules:
                # mimic a client challenge:
                digests = ("xor", )
                try:
                    salt, digest = auth.get_challenge(digests)
                    salt_digest = auth.choose_salt_digest(digests)
                    if digest != "xor":
                        raise ValueError(f"unexpected digest {digest}")
                    if salt_digest != "xor":
                        raise ValueError(f"unexpected salt digest {salt_digest}")
                except ValueError as e:
                    sshlog("authentication with %s", auth, exc_info=True)
                    sshlog.warn("Warning: ssh transport cannot use %r authentication:", auth)
                    sshlog.warn(" %s", e)
                    return False
                else:
                    client_salt = get_salt(len(salt))
                    combined_salt = gendigest("xor", client_salt, salt)
                    xored_password = gendigest("xor", password, combined_salt)
                    r = auth.authenticate(xored_password, client_salt)
                    sshlog("%s.authenticate(..)=%s", auth, r)
                    if not r:
                        return False
            return True

        return make_ssh_server_connection(
            conn, socket_options,
            none_auth=none_auth,
            password_auth=ssh_password_authenticate,
            display_name=self.display,
        )

    def try_upgrade_to_rfb(self, proto) -> bool:
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto.is_closed():
            netlog("try_upgrade_to_rfb() protocol is already closed")
            return False
        conn = proto._conn
        netlog("try_upgrade_to_rfb() input_bytecount=%i", conn.input_bytecount)
        if conn.input_bytecount == 0:
            self.upgrade_protocol_to_rfb(proto)
        return False

    def upgrade_protocol_to_rfb(self, proto: SocketProtocol, data: bytes = b"") -> None:
        conn = proto.steal_connection()
        netlog("upgrade_protocol_to_rfb(%s) connection=%s", proto, conn)
        self._potential_protocols.remove(proto)
        proto.wait_for_io_threads_exit(1)
        conn.set_active(True)
        self.handle_rfb_connection(conn, data)

    def cancel_upgrade_to_rfb_timer(self, protocol) -> None:
        t = self.socket_rfb_upgrade_timer.pop(protocol, None)
        if t:
            GLib.source_remove(t)

    def make_protocol(self, socktype: str, conn, socket_options, protocol_class=SocketProtocol, pre_read=()):
        """ create a new xpra Protocol instance and start it """
        log("make_protocol%s", (socktype, conn, socket_options, protocol_class, pre_read))

        def xpra_protocol_class(conn):
            """ adds xpra protocol tweaks after creating the instance """
            protocol = protocol_class(conn, self.process_packet)
            protocol.large_packets.append("info-response")
            return protocol

        return self.do_make_protocol(socktype, conn, socket_options, xpra_protocol_class, pre_read)

    def do_make_protocol(self, socktype: str, conn, socket_options: dict[str, Any], protocol_class,
                         pre_read: Iterable[bytes] = ()) -> SocketProtocol:
        """ create a new Protocol instance and start it """
        netlog("make_protocol%s", (socktype, conn, socket_options, protocol_class, pre_read))
        socktype = socktype.lower()
        protocol = protocol_class(conn)
        protocol._pre_read = list(pre_read)
        protocol.socket_type = socktype
        self._potential_protocols.append(protocol)
        protocol.authenticators = ()
        protocol.invalid_header = self.invalid_header
        # weak dependency on EncryptionServer:
        parse_encryption = getattr(self, "parse_encryption", noop)
        parse_encryption(protocol, socket_options)
        netlog(f"starting {socktype} protocol")
        protocol.start()
        self.schedule_verify_connection_accepted(protocol, self._accept_timeout)
        return protocol

    def may_wrap_socket(self, conn, socktype: str, address, socket_options: dict, peek_data=b"") \
            -> tuple[bool, Any, bytes]:
        """
            Returns:
            * a flag indicating if we should continue processing this connection
            *  (False for webosocket and tcp proxies as they take over the socket)
            * the connection object (which may now be wrapped, ie: for ssl)
            * new peek data (which may now be empty),
        """
        if not peek_data:
            netlog("may_wrap_socket: no data, not wrapping")
            return True, conn, peek_data
        line1 = peek_data.split(b"\n")[0]
        packet_type = self.guess_packet_type(peek_data)
        if packet_type == "xpra":
            netlog("may_wrap_socket: xpra protocol header '%s', not wrapping", peek_data[0])
            # xpra packet header, no need to wrap this connection
            return True, conn, peek_data
        frominfo = pretty_socket(conn.remote)
        netlog("may_wrap_socket(..) peek_data=%s from %s", Ellipsizer(peek_data), frominfo)
        netlog("may_wrap_socket(..) peek_data got %i bytes", len(peek_data))
        netlog("may_wrap_socket(..) packet_type=%s", packet_type)

        def can_upgrade_to(to_socktype: str) -> bool:
            return self.can_upgrade(socktype, to_socktype, socket_options)

        def conn_err(msg: str) -> tuple[bool, Any, bytes]:
            self.new_conn_err(conn, conn._socket, socktype, address, packet_type, msg)
            return False, None, b""

        if packet_type == "ssh":
            if not can_upgrade_to("ssh"):
                conn_err("ssh upgrades are not enabled")
                return False, None, b""
            conn = self.handle_ssh_connection(conn, socket_options)
            return conn is not None, conn, b""
        if packet_type == "ssl":
            sock, sockname, address, endpoint = conn._socket, conn.local, conn.remote, conn.endpoint
            sock = self._ssl_wrap_socket(socktype, sock, socket_options)
            if sock is None:
                return False, None, b""
            conn = SSLSocketConnection(sock, sockname, address, endpoint, "ssl", socket_options=socket_options)
            conn.socktype_wrapped = socktype
            # we cannot peek on SSL sockets, just clear the unencrypted data:
            http = False
            ssl_mode = (socket_options.get("ssl-mode", "") or self.ssl_mode).lower()
            if ssl_mode == "tcp":
                http = False
            elif ssl_mode == "www":
                http = True
            elif ssl_mode == "auto" or ssl_mode in TRUE_OPTIONS and can_upgrade_to("wss"):
                # use the header to guess:
                if line1.find(b"HTTP/") > 0 or peek_data.find(b"\x08http/1.1") > 0:
                    http = True
                else:
                    conn.enable_peek()
                    peek_data = peek_connection(conn)
                    line1 = peek_data.split(b"\n")[0]
                    http = line1.find(b"HTTP/") > 0
            ssllog("may_wrap_socket SSL: %s, ssl mode=%s, http=%s", conn, ssl_mode, http)
            to_socktype = "wss" if http else "ssl"
            if not can_upgrade_to(to_socktype):
                conn_err(f"{to_socktype} upgrades are not enabled for this socket")
                return False, None, b""
            is_ssl = True
        else:
            http = line1.find(b"HTTP/") > 0
            is_ssl = False
        if http:
            if not has_websocket_handler():
                conn_err("websocket module is not installed")
                return False, None, b""
            ws_protocol = "wss" if is_ssl else "ws"
            if not can_upgrade_to(ws_protocol):
                conn_err(f"{ws_protocol} upgrades are not enabled for this socket")
                return False, None, b""
            self.start_http_socket(socktype, conn, socket_options, is_ssl, peek_data)
            return False, conn, b""
        return True, conn, peek_data

    def invalid_header(self, proto: SocketProtocol, data: bytes, msg="") -> None:
        netlog("invalid header: %s, input_packetcount=%s, websocket_upgrade=%s, ssl=%s",
               Ellipsizer(data), proto.input_packetcount, self.websocket_upgrade, bool(self._ssl_attributes))
        if data == b"RFB " and self._rfb_upgrade > 0:
            netlog("RFB header, trying to upgrade protocol")
            self.cancel_upgrade_to_rfb_timer(proto)
            self.upgrade_protocol_to_rfb(proto, data)
            return
        packet_type = self.guess_packet_type(data)
        # RFBServerProtocol doesn't support `steal_connection`:
        if packet_type == "http" and hasattr(proto, "steal_connection"):
            # try again to wrap this socket:
            bufs = [data]

            def addbuf(buf) -> None:
                bufs.append(buf)

            conn = proto.steal_connection(addbuf)
            self.cancel_verify_connection_accepted(proto)
            self.cancel_upgrade_to_rfb_timer(proto)
            netlog(f"stole connection: {type(conn)}")
            # verify that it is not wrapped yet:
            if isinstance(conn, SocketConnection) and conn.socktype_wrapped == conn.socktype:
                conn.enable_peek(b"".join(bufs))
                conn.set_active(True)
                cont, conn, peek_data = self.may_wrap_socket(conn, conn.socktype, conn.info, conn.options,
                                                             b"".join(bufs))
                netlog("wrap : may_wrap_socket(..)=(%s, %s, %r)", cont, conn, Ellipsizer(peek_data))
                if not cont:
                    return
            if conn:
                # the connection object is now removed from the protocol object,
                # so we have to close it explicitly if we have not wrapped it successfully:
                force_close_connection(conn)
        proto._invalid_header(proto, data, msg)

    # #####################################################################
    # http / websockets:
    def start_http_socket(self, socktype: str, conn, socket_options: dict[str, Any], is_ssl: bool = False,
                          peek_data: bytes = b""):
        frominfo = pretty_socket(conn.remote)
        line1 = peek_data.split(b"\n")[0]
        http_proto = "http" + ["", "s"][int(is_ssl)]
        netlog("start_http_socket(%s, %s, %s, %s, ..) http proto=%s, line1=%r",
               socktype, conn, socket_options, is_ssl, http_proto, line1)
        if line1.startswith(b"GET ") or line1.startswith(b"POST "):
            parts = line1.decode("latin1").split(" ")
            httplog("New %s %s request received from %s for '%s'", http_proto, parts[0], frominfo, parts[1])
            tname = parts[0] + "-request"
            req_info = http_proto + " " + parts[0]
        else:
            httplog("New %s connection received from %s", http_proto, frominfo)
            req_info = "wss" if is_ssl else "ws"
            tname = f"{req_info}-proxy"
        # we start a new thread,
        # only so that the websocket handler thread is named correctly:
        start_thread(self.start_http, f"{tname}-for-{frominfo}",
                     daemon=True, args=(socktype, conn, socket_options, is_ssl, req_info, line1, conn.remote))

    def start_http(self, socktype: str, conn, socket_options: dict[str, Any], is_ssl: bool, req_info: str,
                   line1: bytes, frominfo) -> None:
        httplog("start_http(%s, %s, %s, %s, %s, %r, %s) www dir=%s, headers dir=%s",
                socktype, conn, socket_options, is_ssl, req_info, line1, frominfo,
                self._www_dir, self._http_headers_dirs)
        try:
            from xpra.net.websockets.handler import WebSocketRequestHandler
            sock = conn._socket
            sock.settimeout(self._ws_timeout)

            def new_websocket_client(wsh) -> None:
                from xpra.net.websockets.protocol import WebSocketProtocol
                wslog("new_websocket_client(%s) socket=%s, headers=%s", wsh, sock, wsh.headers)
                newsocktype = "wss" if is_ssl else "ws"
                socket_options["http-headers"] = dict(wsh.headers)
                self.make_protocol(newsocktype, conn, socket_options, WebSocketProtocol)

            scripts = self.get_http_scripts()
            conn.socktype = "wss" if is_ssl else "ws"
            redirect_https = False
            if HTTP_HTTPS_REDIRECT and req_info not in ("ws", "wss"):
                ssl_mode = (socket_options.get("ssl-mode", "") or self.ssl_mode).lower()
                redirect_https = not is_ssl and ssl_mode in TRUE_OPTIONS
            WebSocketRequestHandler(sock, frominfo, new_websocket_client,
                                    self._www_dir, self._http_headers_dirs, scripts,
                                    redirect_https)
            return
        except (OSError, ValueError) as e:
            # don't log a full backtrace for `SSLV3_ALERT_CERTIFICATE_UNKNOWN`
            # and detect it without importing the ssl module
            exc_info = True
            if type(e).__name__ == "SSLError":
                reason = getattr(e, "reason", "")
                log(f"ssl socket error: {e}, library=%s, reason=%s", getattr(e, "library", ""), reason)
                if reason == "SSLV3_ALERT_CERTIFICATE_UNKNOWN":
                    exc_info = False
            httplog("start_http%s", (socktype, conn, is_ssl, req_info, frominfo), exc_info=exc_info)
            err = e.args[0]
            if err == 1 and line1 and line1[0] == 0x16:
                log_fn = httplog.debug
            elif err in (errno.EPIPE, errno.ECONNRESET):
                log_fn = httplog.debug
            else:
                log_fn = httplog.error
                log_fn("Error: %s request failure", req_info)
                log_fn(" errno=%s", err)
            log_fn(" for client %s:", pretty_socket(frominfo))
            if line1 and line1[0] >= 128 or line1[0] == 0x16:
                log_fn(" request as hex: '%s'", hexstr(line1))
            else:
                log_fn(" request: %r", line1)
            log_fn(" %s", e)
        force_close_connection(conn)

    def get_http_scripts(self) -> dict[str, Callable[[str], HttpResponse]]:
        # loose coupling with xpra.server.subsystem.http:
        return getattr(self, "_http_scripts", {})

    def is_timedout(self, protocol: SocketProtocol) -> bool:
        # subclasses may override this method (ServerBase does)
        v = not protocol.is_closed() and protocol in self._potential_protocols
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def schedule_verify_connection_accepted(self, protocol: SocketProtocol, timeout: int = 60) -> None:
        t = GLib.timeout_add(timeout * 1000, self.verify_connection_accepted, protocol)
        self.socket_verify_timer[protocol] = t

    def verify_connection_accepted(self, protocol: SocketProtocol) -> None:
        self.cancel_verify_connection_accepted(protocol)
        if self.is_timedout(protocol):
            conn = getattr(protocol, "_conn", None)
            elapsed = round(monotonic() - protocol.start_time)
            messages = [
                "Error: connection timed out",
                " " + str(conn or protocol),
                f" after {elapsed} seconds",
            ]
            if conn:
                messages += [
                    f" sent {conn.output_bytecount} bytes",
                    f" received {conn.input_bytecount} bytes",
                ]
                if conn.input_bytecount == 0:
                    try:
                        data = conn.peek(200)
                    except (OSError, ValueError):
                        log("cannot peek on %s", conn)
                        data = b""
                    if data:
                        messages.append(f" read buffer={data!r}")
                        packet_type = self.guess_packet_type(data)
                        if packet_type:
                            messages.append(f" looks like {packet_type!r}")
                    else:
                        # no data was ever received,
                        # this can happen with probes or browser connections,
                        # log at debug level only to avoid spamming the log:
                        for msg in messages:
                            netlog(msg)
                        messages = []
            for msg in messages:
                netlog.error(msg)
            self.send_disconnect(protocol, ConnectionMessage.LOGIN_TIMEOUT)

    def cancel_verify_connection_accepted(self, protocol: SocketProtocol) -> None:
        t = self.socket_verify_timer.pop(protocol, None)
        if t:
            GLib.source_remove(t)

    def send_disconnect(self, proto: SocketProtocol, *reasons) -> None:
        netlog("send_disconnect(%s, %s)", proto, reasons)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto.is_closed():
            return
        proto.send_disconnect(reasons)
        GLib.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto: SocketProtocol) -> None:
        netlog("force_disconnect(%s)", proto)
        self.cleanup_protocol(proto)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        proto.close()

    def disconnect_client(self, protocol: SocketProtocol, reason: str | ConnectionMessage, *extra) -> None:
        netlog("disconnect_client(%s, %s, %s)", protocol, reason, extra)
        if protocol and not protocol.is_closed():
            self.disconnect_protocol(protocol, reason, *extra)

    def disconnect_protocol(self, protocol: SocketProtocol, *reasons) -> None:
        netlog("disconnect_protocol(%s, %s)", protocol, reasons)
        i = nicestr(reasons[0])
        if len(reasons) > 1:
            i += " (%s)" % csv(reasons[1:])
        proto_info = f" {protocol}"
        try:
            conn = protocol._conn
            info = conn.get_info()
            endpoint = info.get("endpoint")
            if endpoint:
                proto_info = " " + pretty_socket(endpoint)
            else:
                proto_info = " " + pretty_socket(conn.local)
        except (KeyError, AttributeError):
            pass
        self.cancel_verify_connection_accepted(protocol)
        self.cancel_upgrade_to_rfb_timer(protocol)
        if not protocol.is_closed():
            self._log_disconnect(protocol, "Disconnecting client%s:", proto_info)
            self._log_disconnect(protocol, " %s", i)
            protocol.send_disconnect(reasons)
        self.cleanup_protocol(protocol)

    def cleanup_protocol(self, protocol: SocketProtocol) -> None:
        """ some subclasses perform extra cleanup here """

    def _process_disconnect(self, proto: SocketProtocol, packet: Packet) -> None:
        info = packet.get_str(1)
        if len(packet) > 2:
            info += " (%s)" % csv(str(x) for x in packet[2:])
        # only log protocol info if there is more than one client:
        proto_info = self._disconnect_proto_info(proto)
        self._log_disconnect(proto, "client%s has requested disconnection: %s", proto_info, info)
        self.disconnect_protocol(proto, ConnectionMessage.CLIENT_REQUEST)

    def _log_disconnect(self, _proto: SocketProtocol, *args) -> None:
        netlog.info(*args)

    def _disconnect_proto_info(self, _proto) -> str:
        # overridden in server_base in case there is more than one protocol
        return ""

    def _process_connection_lost(self, proto: SocketProtocol, packet: Packet) -> None:
        netlog("process_connection_lost(%s, %s)", proto, packet)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto in self._potential_protocols:
            if not proto.is_closed():
                self._log_disconnect(proto, "Connection lost")
                for extra in packet[1:]:
                    self._log_disconnect(proto, " %s", extra)
            self._potential_protocols.remove(proto)
        self.cleanup_protocol(proto)

    def _process_gibberish(self, proto: SocketProtocol, packet: Packet) -> None:
        message = packet.get_str(1)
        data = packet.get_bytes(2)
        netlog("Received uninterpretable nonsense from %s: %s", proto, message)
        netlog(" data: %s", Ellipsizer(data))
        self.disconnect_client(proto, message)

    def _process_invalid(self, protocol: SocketProtocol, packet: Packet) -> None:
        message = packet.get_str(1)
        data = packet.get_bytes(2)
        netlog(f"Received invalid packet: {message}")
        netlog(" data: %s", Ellipsizer(data))
        self.disconnect_client(protocol, message)

    # #####################################################################
    # hello / authentication:
    def send_version_info(self, proto: SocketProtocol, full: bool = False) -> None:
        version = version_str() if (full and FULL_INFO) else XPRA_VERSION.split(".", 1)[0]
        proto.send_now(Packet("hello", {"version": version}))
        # client is meant to close the connection itself, but just in case:
        GLib.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.DONE, "version sent")

    def _process_hello(self, proto: SocketProtocol, packet: Packet) -> None:
        capabilities = packet.get_dict(1)
        c = typedict(capabilities)
        if LOG_HELLO:
            netlog.info(f"hello from {proto}:")
            print_nested_dict(c, print_fn=netlog.info)
        proto.set_compression_level(c.intget("compression_level", self.compression_level))
        proto.enable_compressor_from_caps(c)
        if not proto.enable_encoder_from_caps(c):
            # this should never happen:
            # if we got here, we parsed a packet from the client!
            # (maybe the client used an encoding it claims not to support?)
            self.disconnect_client(proto, ConnectionMessage.PROTOCOL_ERROR, "failed to negotiate a packet encoder")
            return

        log("process_hello: capabilities=%s", capabilities)
        request = c.strget("request")
        if request in UNAUTHENTICATED_HELLO_REQUESTS and self.do_handle_hello_request(request, proto, c):
            return

        # verify version:
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, ConnectionMessage.VERSION_ERROR, f"incompatible version: {verr!r}")
            proto.close()
            return

        # try to auto upgrade to ssl:
        packet_types = c.strtupleget("packet-types", ())
        encryption_caps = c.dictget("encryption")
        conn = getattr(proto, "_conn", None)
        if SSL_UPGRADE and not encryption_caps and "ssl-upgrade" in packet_types and conn and conn.socktype in ("tcp",):
            options = conn.options
            if options.get("ssl-upgrade", "yes").lower() in TRUE_OPTIONS:
                ssl_options = self.get_ssl_socket_options(options)
                cert = ssl_options.get("cert", "")
                if cert:
                    log.info(f"sending ssl upgrade for {conn}")
                    cert_data = load_binary_file(cert)
                    ssl_attrs = {"cert-data": cert_data}
                    proto.send_now(Packet("ssl-upgrade", ssl_attrs))
                    return

        # if we're here, then we should have read everything that was sent by the client,
        # including any data we potentially peeked at:
        disable_peek = getattr(conn, "disable_peek", noop)
        disable_peek()

        # this will call auth_verified if successful
        # it may also just send challenge packets,
        # in which case we'll end up here parsing the hello again
        start_thread(AuthenticatedServer.verify_auth, "authenticate connection", daemon=True, args=(self, proto, packet, c))

    def _process_ssl_upgrade(self, proto: SocketProtocol, packet: Packet) -> None:
        socktype = proto._conn.socktype
        new_socktype = {"tcp": "ssl", "ws": "wss"}.get(socktype)
        if not new_socktype:
            raise ValueError(f"cannot upgrade {socktype} to ssl")
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        ssllog("ssl-upgrade: %s", packet[1:])
        conn = proto.steal_connection()
        # threads should be able to terminate immediately
        # as there's no traffic yet:
        ioe = proto.wait_for_io_threads_exit(1)
        if not ioe:
            self.disconnect_protocol(proto, "failed to terminate network threads for ssl upgrade")
            force_close_connection(conn)
            return
        options = conn.options
        socktype = conn.socktype
        ssl_sock = self._ssl_wrap_socket(socktype, conn._socket, options)
        if not ssl_sock:
            self.disconnect_protocol(proto, "failed to upgrade socket to ssl")
            force_close_connection(conn)
            return
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint, "ssl", socket_options=options)
        ssl_conn.socktype_wrapped = socktype
        protocol_class = get_server_protocol_class(new_socktype)
        self.make_protocol(new_socktype, ssl_conn, options, protocol_class)
        ssllog.info("upgraded %s to %s", conn, new_socktype)

    def call_hello_oked(self, proto: SocketProtocol, c: typedict, auth_caps: dict) -> None:
        try:
            if SIMULATE_SERVER_HELLO_ERROR:
                raise RuntimeError("Simulating a server error")
            self.hello_oked(proto, c, auth_caps)
        except ClientException as e:
            log("call_hello_oked(%s, %s, %s)", proto, Ellipsizer(c), auth_caps, exc_info=True)
            log.error("Error setting up new connection for")
            log.error(" %s:", proto)
            log.estr(e)
            self.disconnect_client(proto, ConnectionMessage.CONNECTION_ERROR, str(e))
        except Exception as e:
            # log exception but don't disclose internal details to the client
            log.error("server error processing new connection from %s: %s", proto, e, exc_info=True)
            self.disconnect_client(proto, ConnectionMessage.CONNECTION_ERROR, "error accepting new connection")

    def hello_oked(self, proto: SocketProtocol, c: typedict, _auth_caps: dict) -> bool:
        if self._closing:
            self.disconnect_client(proto, ConnectionMessage.SERVER_EXIT, "server is shutting down")
            return True
        request = c.strget("request")
        if request and self.handle_hello_request(request, proto, c):
            return True
        return False

    def handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        if not is_request_allowed(proto, request):
            msg = f"{request!r} requests are not enabled for this connection"
            log.warn(f"Warning: {msg}")
            self.send_disconnect(proto, ConnectionMessage.PERMISSION_ERROR, msg)
            return True
        return self.do_handle_hello_request(request, proto, caps)

    def do_handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        handler = self.hello_request_handlers.get(request)
        log("do_handle_hello_request(%s, %s, ..) handler=%s", request, proto, handler)
        if not handler:
            log.warn(f"Warning: no handler for hello request {request!r}")
            return False
        return handler(proto, caps)

    def _handle_hello_request_connect_test(self, proto, caps: typedict) -> bool:
        ctr = caps.strget("connect_test_request")
        response = {"connect_test_response": ctr}
        proto.send_now(Packet("hello", response))
        return True

    def _handle_hello_request_screenshot(self, proto, _caps: typedict) -> bool:
        packet = self.make_screenshot_packet()
        proto.send_now(packet)
        return True

    def accept_client(self, proto: SocketProtocol, c: typedict) -> None:
        # max packet size from client (the biggest we can get are clipboard packets)
        netlog("accept_client(%s, %s)", proto, c)
        # note: when uploading files, we send them in chunks smaller than this size
        proto.max_packet_size = MAX_PACKET_SIZE
        proto.parse_remote_caps(c)
        self.accept_protocol(proto)

    def accept_protocol(self, proto: SocketProtocol) -> None:
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)

    def make_hello(self, source) -> dict[str, Any]:
        now = time()
        capabilities = get_network_caps(FULL_INFO)
        for bc in SERVER_BASES:
            capabilities |= bc.get_caps(self, source)
        capabilities |= get_digest_caps()
        capabilities |= {
            "start_time": int(self.start_time),
            "current_time": int(now),
            "elapsed_time": int(now - self.start_time),
            "server_type": "core",
            "server.mode": self.session_type,
        }
        if FULL_INFO > 0:
            capabilities["hostname"] = socket.gethostname()
        if source is None or "features" in source.wants:
            capabilities |= {
                "readonly-server": True,
                "readonly": self.readonly,
            }
            server_log = os.environ.get("XPRA_SERVER_LOG", "")
            if server_log:
                capabilities["server-log"] = server_log
        if source and "packet-types" in source.wants:
            capabilities["packet-types"] = PACKET_TYPES
        if self.session_name:
            capabilities["session_name"] = self.session_name
        return capabilities

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        log.warn("ServerCore.get_threaded_info(%s, %s)", proto, kwargs)
        start = monotonic()
        # this function is for non UI thread info, see also: `get_ui_info`
        info = {}
        subsystems = kwargs.get("subsystems", ())
        for bc in SERVER_BASES:
            if subsystems and subsystem_name(bc) not in subsystems:
                continue
            info.update(bc.get_info(self, proto))

        end = monotonic()
        log("ServerCore.get_info took %ims", (end - start) * 1000)
        return info

    def get_socket_info(self) -> dict[str, Any]:
        si: dict[str, Any] = {}

        def add_listener(socktype: str, info) -> None:
            si.setdefault(socktype, {}).setdefault("listeners", []).append(info)

        def add_address(socktype: str, address, port: int) -> None:
            addresses = si.setdefault(socktype, {}).setdefault("addresses", [])
            if (address, port) not in addresses:
                addresses.append((address, port))
            if socktype == "tcp":
                if self.websocket_upgrade:
                    add_address("ws", address, port)
                if self._ssl_attributes:
                    add_address("ssl", address, port)
                if self.ssh_upgrade:
                    add_address("ssh", address, port)
            if socktype == "ws" and self._ssl_attributes:
                add_address("wss", address, port)

        netifaces = import_netifaces()
        for sock in self.sockets:
            socktype = sock.socktype
            address = sock.address
            if not address:
                continue
            add_listener(socktype, address)
            if not SHOW_NETWORK_ADDRESSES:
                continue
            if socktype not in ("tcp", "ssl", "ws", "wss", "ssh"):
                # we expose addresses only for TCP sockets
                continue
            upnp_address = sock.options.get("upnp-address", ())
            if upnp_address:
                add_address(socktype, *upnp_address)
            if len(address) != 2 or not isinstance(address[0], str) or not isinstance(address[1], int):
                # unsupported listener info format
                continue
            host, port = address
            if host not in ("0.0.0.0", "::/0", "::"):
                # not a wildcard address, use it as-is:
                add_address(socktype, host, port)
                continue
            if not netifaces:
                if first_time("netifaces-socket-address"):
                    netlog("get_socket_info()", backtrace=True)
                    netlog.warn("Warning: netifaces is missing")
                    netlog.warn(" socket addresses cannot be queried")
            else:
                for ip in get_all_ips():
                    add_address(socktype, ip, port)

        for socktype, auth_classes in self.auth_classes.items():
            if auth_classes:
                authenticators = si.setdefault(socktype, {}).setdefault("authenticator", {})
                for i, auth_class in enumerate(auth_classes):
                    authenticators[i] = auth_class[0], auth_class[3]
        return si

    ######################################################################
    # packet handling:
    def process_packet(self, proto, packet) -> None:
        return super().dispatch_packet(proto, packet)

    def handle_rfb_connection(self, conn, data: bytes = b"") -> None:
        log.error("Error: RFB protocol is not supported by this server")
        log("handle_rfb_connection%s", (conn, data))
        force_close_connection(conn)

    def handle_rdp_connection(self, conn, data: bytes = b"") -> None:
        if data and data[:2] != b"\x03\x00":
            raise ValueError("packet is not valid RDP")
        log.error("Error: RDP protocol is not supported by this server")
        log("handle_rdp_connection%s", (conn, data))
        force_close_connection(conn)
