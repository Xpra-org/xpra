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
import platform
import threading
from weakref import WeakKeyDictionary
from time import sleep, time, monotonic
from threading import Lock
from types import FrameType
from typing import Any, NoReturn
from collections.abc import Callable, Sequence, Iterable

from xpra.util.version import (
    XPRA_VERSION, XPRA_NUMERIC_VERSION, vparts, version_str, version_compat_check, get_version_info,
    get_build_info, get_platform_info, get_host_info, parse_version,
)
from xpra.scripts.server import deadly_signal
from xpra.scripts.session import rm_session_dir, clean_session_files
from xpra.exit_codes import ExitValue, ExitCode
from xpra.server import ServerExitMode
from xpra.server import features
from xpra.server.mixins.control import ControlHandler
from xpra.server.util import write_pidfile, rm_pidfile
from xpra.scripts.config import str_to_bool, parse_bool_or, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.net.common import (
    SOCKET_TYPES, MAX_PACKET_SIZE, SSL_UPGRADE, PACKET_TYPES,
    is_request_allowed, PacketType, get_ssh_port, has_websocket_handler, HttpResponse, HTTP_UNSUPORTED,
)
from xpra.net.socket_util import (
    PEEK_TIMEOUT_MS, SOCKET_PEEK_TIMEOUT_MS,
    add_listen_socket, accept_connection, guess_packet_type,
    peek_connection, )
from xpra.net.bytestreams import (
    Connection, SSLSocketConnection, SocketConnection,
    log_new_connection, pretty_socket, SOCKET_TIMEOUT
)
from xpra.net.net_util import (
    get_network_caps, get_info as get_net_info,
    import_netifaces, get_interfaces_addresses,
)
from xpra.net.glib_handler import GLibPacketHandler
from xpra.net.protocol.factory import get_server_protocol_class
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.net.protocol.constants import CONNECTION_LOST, GIBBERISH, INVALID
from xpra.net.digest import get_salt, gendigest, choose_digest
from xpra.platform import set_name, threaded_server_init
from xpra.platform.info import get_username
from xpra.platform.paths import get_app_dir, get_system_conf_dirs, get_user_conf_dirs
from xpra.platform.events import add_handler, remove_handler
from xpra.platform.dotxpra import DotXpra
from xpra.os_util import force_quit, get_machine_id, get_user_uuid, get_hex_uuid, getuid, gi_import, POSIX
from xpra.util.system import get_env_info, get_sysconfig_info, register_SIGUSR_signals
from xpra.util.parsing import parse_encoded_bin_data
from xpra.util.io import load_binary_file, filedata_nocrlf
from xpra.server.background_worker import add_work_item, quit_worker
from xpra.auth.auth_helper import get_auth_module, AuthDef
from xpra.util.thread import start_thread
from xpra.common import LOG_HELLO, FULL_INFO, SSH_AGENT_DISPATCH, DEFAULT_XDG_DATA_DIRS, ConnectionMessage, noerr
from xpra.util.pysystem import dump_all_frames, get_frame_info
from xpra.util.objects import typedict, notypedict, merge_dicts
from xpra.util.str_fn import csv, Ellipsizer, repr_ellipsized, print_nested_dict, nicestr, strtobytes, hexstr
from xpra.util.env import envint, envbool, envfloat, osexpand, first_time
from xpra.log import Logger, get_info as get_log_info

# pylint: disable=import-outside-toplevel

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")
ssllog = Logger("ssl")
httplog = Logger("http")
wslog = Logger("websocket")
proxylog = Logger("proxy")
authlog = Logger("auth")
cryptolog = Logger("crypto")
timeoutlog = Logger("timeout")
mdnslog = Logger("mdns")

main_thread = threading.current_thread()

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_MAX_CONCURRENT_CONNECTIONS", 100)
SIMULATE_SERVER_HELLO_ERROR = envbool("XPRA_SIMULATE_SERVER_HELLO_ERROR", False)
SERVER_SOCKET_TIMEOUT = envfloat("XPRA_SERVER_SOCKET_TIMEOUT", 0.1)
CHALLENGE_TIMEOUT = envint("XPRA_CHALLENGE_TIMEOUT", 120)

SYSCONFIG = envbool("XPRA_SYSCONFIG", FULL_INFO > 1)
SHOW_NETWORK_ADDRESSES = envbool("XPRA_SHOW_NETWORK_ADDRESSES", True)
INIT_THREAD_TIMEOUT = envint("XPRA_INIT_THREAD_TIMEOUT", 10)
HTTP_HTTPS_REDIRECT = envbool("XPRA_HTTP_HTTPS_REDIRECT", True)

POWER_EVENTS = envbool("XPRA_POWER_EVENTS", True)

ENCRYPTED_SOCKET_TYPES = os.environ.get("XPRA_ENCRYPTED_SOCKET_TYPES", "tcp,ws")


# class used to distinguish internal errors
# which should not be shown to the client,
# from useful messages we do want to pass on
class ClientException(Exception):
    pass


def get_server_info() -> dict[str, Any]:
    # this function is for non UI thread info
    build = {} if FULL_INFO < 1 else get_build_info()
    build.update(get_version_info())
    info = {
        "platform": get_platform_info(),
        "build": build,
    }
    return info


def get_thread_info(proto=None) -> dict[Any, Any]:
    # threads:
    if proto:
        info_threads = proto.get_threads()
    else:
        info_threads = ()
    return get_frame_info(info_threads)


def proto_crypto_caps(proto) -> dict[str, Any]:
    if not proto:
        return {}
    if FULL_INFO > 1 or proto.encryption:
        from xpra.net.crypto import get_crypto_caps
        return get_crypto_caps(FULL_INFO)
    return {}


def force_close_connection(conn) -> None:
    try:
        conn.close()
    except OSError:
        log("close_connection()", exc_info=True)


# noinspection PyMethodMayBeStatic
class ServerCore(ControlHandler, GLibPacketHandler):
    """
        This is the simplest base class for servers.
        It only handles the connection layer:
        authentication and the initial handshake.
    """

    def __init__(self):
        log("ServerCore.__init__()")
        ControlHandler.__init__(self)
        GLibPacketHandler.__init__(self)
        self.start_time = time()
        self.uuid = ""
        self.auth_classes: dict[str, Sequence[AuthDef]] = {}
        self.child_reaper = None
        self.session_type: str = "unknown"
        self.display_name: str = ""
        self.display_options = ""
        self.dotxpra = None
        self._closing: bool = False
        self._exit_mode = ServerExitMode.UNSET
        # networking bits:
        self._socket_info: dict = {}
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
        self.socket_info: dict[Any, dict] = {}
        self.socket_options: dict[Any, dict] = {}
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
        self.exec_cwd = os.getcwd()
        self.pidfile = ""
        self.pidinode: int = 0
        self.session_files: list[str] = [
            "cmdline", "server.env", "config", "server.log*",
            # notifications may use a TMP dir:
            "tmp/*", "tmp",
        ]
        if SSH_AGENT_DISPATCH:
            self.session_files.append("ssh/agent")
            self.session_files.append("ssh/agent.default")
            # glob that matches agent uuid symlinks:
            self.session_files.append("ssh/????????????????????????????????????????????????????????????????")
            self.session_files.append("ssh")
        self.splash_process = None

        self.session_name = ""

        # Features:
        self.readonly = False
        self.mdns = False
        self.mdns_publishers = {}
        self.encryption = ""
        self.encryption_keyfile = ""
        self.tcp_encryption = ""
        self.tcp_encryption_keyfile = ""
        self.password_file: Iterable[str] = ()
        self.compression_level = 1
        self.exit_with_client = False
        self.server_idle_timeout = 0
        self.server_idle_timer = 0

        self.init_thread = None
        self.init_thread_callbacks: list[tuple[Callable, tuple]] = []
        self.init_thread_lock = Lock()
        self.menu_provider = None

        self.init_uuid()
        self._default_packet_handlers: dict[str, Callable] = {}

    def get_server_mode(self) -> str:
        return self.session_type

    def init(self, opts) -> None:
        log("ServerCore.init(%s)", opts)
        self.session_name = str(opts.session_name)
        set_name("Xpra", self.session_name or "Xpra")
        self.pidfile = osexpand(opts.pidfile)
        if self.pidfile:
            self.pidinode = write_pidfile(os.path.normpath(self.pidfile))

        self.unix_socket_paths = []
        self._socket_dir = opts.socket_dir or ""
        if not self._socket_dir and opts.socket_dirs:
            self._socket_dir = opts.socket_dirs[0]
        self._socket_dirs = opts.socket_dirs
        self.encryption = opts.encryption
        self.encryption_keyfile = opts.encryption_keyfile
        self.tcp_encryption = opts.tcp_encryption
        self.tcp_encryption_keyfile = opts.tcp_encryption_keyfile
        if self.encryption or self.tcp_encryption:
            from xpra.net.crypto import crypto_backend_init  # pylint: disable=import-outside-toplevel
            crypto_backend_init()
        self.password_file = opts.password_file
        self.compression_level = opts.compression_level
        self.exit_with_client = opts.exit_with_client
        self.server_idle_timeout = opts.server_idle_timeout
        self.readonly = opts.readonly
        self.http = opts.http
        self.websocket_upgrade = opts.websocket_upgrade
        self.ssh_upgrade = opts.ssh_upgrade
        self.rdp_upgrade = opts.rdp_upgrade
        self.mdns = opts.mdns
        if opts.start_new_commands:
            # must be initialized before calling init_html_proxy
            from xpra.server.menu_provider import get_menu_provider
            self.menu_provider = get_menu_provider()
        if self.http:
            self.init_html_proxy(opts)
        self.init_auth(opts)
        self.init_ssl(opts)
        self.dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs + opts.client_socket_dirs)

    def init_ssl(self, opts) -> None:
        self.ssl_mode = opts.ssl
        try:
            from xpra.net.ssl_util import get_ssl_attributes
        except ImportError as e:
            netlog("init_ssl(..) no ssl: %s", e)
        else:
            self._ssl_attributes = get_ssl_attributes(opts, True)
            netlog("init_ssl(..) ssl attributes=%s", self._ssl_attributes)
        if opts.ssl.lower() not in FALSE_OPTIONS:
            self.ssl_upgrade = opts.ssl_upgrade

    def validate(self) -> bool:
        return True

    def server_init(self) -> None:
        if self.mdns:
            add_work_item(self.mdns_publish)
        self.start_listen_sockets()

    def setup(self) -> None:
        self.init_control_commands()
        self.init_packet_handlers()
        # for things that can take longer:
        self.init_thread = start_thread(target=self.threaded_init, name="server-init-thread")

    def init_control_commands(self):
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
        self.late_cleanup(stop=self._exit_mode not in (ServerExitMode.EXIT, ServerExitMode.UPGRADE))
        if self._exit_mode not in (ServerExitMode.EXIT, ServerExitMode.UPGRADE):
            self.clean_session_files()
            rm_session_dir()
        self.do_quit()
        log("quit(%s) do_quit done!", exit_mode)
        dump_all_frames()

    def closing(self) -> None:
        if not self._closing:
            self._closing = True
            self.log_closing_message()

    def log_closing_message(self) -> None:
        exiting = self._exit_mode in (ServerExitMode.EXIT, ServerExitMode.UPGRADE)
        log.info("%s server is %s", self.get_server_mode(), ["terminating", "exiting"][exiting])

    def do_quit(self) -> None:
        raise NotImplementedError()

    def install_signal_handlers(self, callback: Callable[[int], None]) -> None:
        def os_signal(signum: signal.Signals | int, _frame: FrameType | None = None) -> None:
            callback(signum)

        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        register_SIGUSR_signals(GLib.idle_add)

    def threaded_init(self) -> None:
        log("threaded_init() servercore start")
        self.threaded_setup()
        self.call_init_thread_callbacks()

    def threaded_setup(self) -> None:
        log("threaded_setup() servercore start")
        # platform specific init:
        threaded_server_init()
        # populate the platform info cache:
        get_platform_info()
        if self.menu_provider:
            self.menu_provider.setup()
        add_work_item(self.print_run_info)
        GLib.idle_add(self.reset_server_timeout)
        log("threaded_setup() servercore end")

    def call_init_thread_callbacks(self) -> None:
        # run the init callbacks:
        with self.init_thread_lock:
            log("call_init_thread_callbacks() init_thread_callbacks=%s", self.init_thread_callbacks)
            for cb, args in self.init_thread_callbacks:
                try:
                    log("calling %s%s", cb, args)
                    cb(*args)
                except Exception as e:
                    log("threaded_init()", exc_info=True)
                    log.error("Error in initialization thread callback")
                    log.error(" calling %s%s", cb, args, exc_info=True)
                    log.estr(e)

    def add_init_thread_callback(self, callback: Callable, *args) -> None:
        log("add_init_thread_callback(%s, %s)", callback, args)
        self.init_thread_callbacks.append((callback, args))

    def after_threaded_init(self, callback: Callable, *args) -> None:
        log("after_threaded_init(%s, %s)", callback, args)
        with self.init_thread_lock:
            if self.init_thread is None or self.init_thread.is_alive():
                self.add_init_thread_callback(callback, *args)
            else:
                callback(*args)

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

    def run(self) -> ExitValue:
        self.install_signal_handlers(self.signal_quit)
        GLib.idle_add(self.register_power_events)
        GLib.idle_add(self.server_is_ready)
        self.stop_splash_process()
        self.do_run()
        log("run()")
        return 0

    def register_power_events(self):
        if not POWER_EVENTS:
            return
        add_handler("suspend", self.suspend_event)
        add_handler("resume", self.resume_event)

    def remove_power_events(self):
        remove_handler("suspend", self.suspend_event)
        remove_handler("resume", self.resume_event)

    def suspend_event(self, _args):
        log.info("suspending")

    def resume_event(self, _args):
        log.info("resuming")

    def server_is_ready(self) -> None:
        log.info("xpra is ready.")
        noerr(sys.stdout.flush)

    def do_run(self) -> None:
        raise NotImplementedError()

    def cleanup(self) -> None:
        self.stop_splash_process()
        self.cancel_touch_timer()
        self.remove_power_events()
        self.mdns_cleanup()
        self.cleanup_all_protocols()
        self.do_cleanup()
        self.cleanup_sockets()
        self.cleanup_menu_provider()
        netlog("cleanup() done for server core")

    def do_cleanup(self) -> None:
        # allow just a bit of time for the protocol packet flush
        sleep(0.1)

    def late_cleanup(self, stop=True) -> None:
        self.cleanup_all_protocols(force=True)
        self._potential_protocols = []
        if self.pidfile:
            netlog("cleanup removing pidfile %s", self.pidfile)
            rm_pidfile(self.pidfile, self.pidinode)
            self.pidinode = 0
        from xpra.util.child_reaper import reaper_cleanup
        reaper_cleanup()

    def clean_session_files(self) -> None:
        self.do_clean_session_files(*self.session_files)

    def do_clean_session_files(self, *filenames) -> None:
        log("do_clean_session_files%s", filenames)
        clean_session_files(*filenames)

    def stop_splash_process(self) -> None:
        sp = self.splash_process
        if sp:
            self.splash_process = None
            try:
                sp.terminate()
            except OSError:
                log("stop_splash_process()", exc_info=True)

    def cleanup_menu_provider(self) -> None:
        mp = self.menu_provider
        if mp:
            self.menu_provider = None
            mp.cleanup()

    def cleanup_sockets(self) -> None:
        netlog("cleanup_sockets() %s", self.socket_cleanup)
        # stop listening for IO events:
        for sc in self.socket_cleanup:
            sc()
        # actually close the socket:
        si = self._socket_info
        self._socket_info = {}
        for socktype, _, info, cleanup in si:
            log("cleanup_sockets() calling %s for %s %s", cleanup, socktype, info)
            try:
                cleanup()
            except OSError:
                log("cleanup error on %s", cleanup, exc_info=True)

    def init_uuid(self) -> None:
        # Define a server UUID if needed:
        self.uuid = os.environ.get("XPRA_PROXY_START_UUID") or self.get_uuid()
        if not self.uuid:
            self.uuid = get_hex_uuid()
            self.save_uuid()
        log(f"server uuid is {self.uuid}")

    def get_uuid(self) -> str:
        return ""

    def save_uuid(self) -> None:
        """ X11 servers use this method to save the uuid as a root window property """

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

    ######################################################################
    # authentication:
    def init_auth(self, opts) -> None:
        for x in SOCKET_TYPES:
            if x == "hyperv":
                # we don't support listening on hyperv sockets yet
                continue
            if x in ("socket", "named-pipe"):
                # use local-auth for these:
                opts_value = opts.auth
            else:
                opts_value = getattr(opts, f"{x}_auth")
            self.auth_classes[x] = self.get_auth_modules(x, opts_value)
        authlog(f"init_auth(..) auth={self.auth_classes}")

    def get_auth_modules(self, socket_type: str, auth_strs: Iterable[str]) -> Sequence[AuthDef]:
        authlog(f"get_auth_modules({socket_type}, {auth_strs}, ..)")
        if not auth_strs:
            return ()
        return tuple(get_auth_module(auth_str) for auth_str in auth_strs)

    def print_run_info(self) -> None:
        from xpra.common import get_run_info
        for run_info in get_run_info(f"{self.get_server_mode()} server"):
            log.info(run_info)
        GLib.idle_add(self.print_screen_info)

    def notify_new_user(self, ss) -> None:
        pass

    ######################################################################
    # screen / display:
    def get_display_bit_depth(self) -> int:
        return 0

    def print_screen_info(self) -> None:
        """ see subclasses for actual implementations """

    # #####################################################################
    # sockets / connections / packets:
    def init_sockets(self, sockets) -> None:
        self._socket_info = sockets

    def mdns_publish(self) -> None:
        if not self.mdns:
            return
        # find all the records we want to publish:
        mdns_recs: dict[str, list[tuple[str, int]]] = {}
        for sock_def, options in self._socket_info.items():
            socktype, _, info, _ = sock_def
            socktypes = self.get_mdns_socktypes(socktype, options)
            mdns_option = options.get("mdns")
            if mdns_option:
                v = str_to_bool(mdns_option, False)
                if not v:
                    mdnslog("mdns_publish() mdns(%s)=%s, skipped", info, mdns_option)
                    continue
            mdnslog("mdns_publish() info=%s, socktypes(%s)=%s", info, socktype, socktypes)
            for st in socktypes:
                if st == "socket":
                    continue
                recs = mdns_recs.setdefault(st, [])
                if socktype == "socket":
                    if st != "ssh":
                        log.error(f"Error: unexpected {st!r} socket type for {socktype}")
                        continue
                    host = "*"
                    iport = get_ssh_port()
                    if not iport:
                        continue
                    hosts = ["0.0.0.0"]
                    import socket
                    if socket.has_ipv6:
                        hosts.append("::")
                else:
                    host, iport = info
                    hosts = [host]
                for h in hosts:
                    rec = (h, iport)
                    if rec not in recs:
                        recs.append(rec)
                mdnslog("mdns_publish() recs[%s]=%s", st, recs)
        if not mdns_recs:
            return
        mdns_info = self.get_mdns_info()
        self.mdns_publishers = {}
        from xpra.net.mdns.util import mdns_publish
        for mdns_mode, listen_on in mdns_recs.items():
            info = dict(mdns_info)
            info["mode"] = mdns_mode
            aps = mdns_publish(self.display_name, listen_on, info)
            for ap in aps:
                ap.start()
                self.mdns_publishers[ap] = mdns_mode

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

    def get_mdns_socktypes(self, socktype: str, options: dict[str, str]) -> Sequence[str]:
        # for a given socket type,
        # what socket types we should expose via mdns
        if socktype in ("vsock", "named-pipe"):
            # cannot be accessed remotely
            return ()
        if socktype == "quic":
            return "quic", "webtransport"
        socktypes = [socktype]
        if socktype == "tcp":
            for tosocktype in ("ssl", "ws", "wss", "ssh", "rfb", "rdp"):
                if self.can_upgrade(socktype, tosocktype, options):
                    socktypes.append(tosocktype)
        elif socktype in ("ws", "ssl") and self.can_upgrade(socktype, "wss", options):
            socktypes.append("wss")
        elif socktype == "socket" and self.ssh_upgrade and get_ssh_port() > 0:
            socktypes = ["ssh"]
        return tuple(socktypes)

    def get_mdns_info(self) -> dict[str, Any]:
        mdns_info = {
            "display": self.display_name,
            "username": get_username(),
            "uuid": self.uuid,
            "platform": sys.platform,
            "type": self.session_type,
        }
        MDNS_EXPOSE_NAME = envbool("XPRA_MDNS_EXPOSE_NAME", True)
        if MDNS_EXPOSE_NAME and self.session_name:
            mdns_info["name"] = self.session_name
        return mdns_info

    def mdns_cleanup(self) -> None:
        if self.mdns_publishers:
            add_work_item(self.do_mdns_cleanup)

    def do_mdns_cleanup(self) -> None:
        mp = dict(self.mdns_publishers)
        self.mdns_publishers = {}
        for ap in tuple(mp.keys()):
            ap.stop()

    def mdns_update(self) -> None:
        if not self.mdns:
            return
        txt = self.get_mdns_info()
        for mdns_publisher, mode in dict(self.mdns_publishers).items():
            info = dict(txt)
            info["mode"] = mode
            try:
                mdns_publisher.update_txt(info)
            except Exception as e:
                mdnslog("mdns_update: %s(%s)", mdns_publisher.update_txt, info, exc_info=True)
                mdnslog.warn("Warning: mdns update failed")
                mdnslog.warn(" %s", e)

    def start_listen_sockets(self) -> None:
        # All right, we're ready to accept customers:
        for sock_def, options in self._socket_info.items():
            socktype, sock, info, _ = sock_def
            netlog("init_sockets(%s) will add %s socket %s (%s)", self._socket_info, socktype, sock, info)
            self.socket_info[sock] = info
            self.socket_options[sock] = options
            GLib.idle_add(self.add_listen_socket, socktype, sock, options)
            if socktype == "socket" and info:
                if info.startswith("@"):
                    # abstract sockets can't be 'touch'ed
                    continue
                try:
                    p = os.path.abspath(info)
                    self.unix_socket_paths.append(p)
                    netlog("added unix socket path: %s", p)
                except Exception as e:
                    log.error("failed to set socket path to %s: %s", info, e)
                    del e
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
        netlog("initializing packet handlers")
        self._default_packet_handlers = {
            "hello": self._process_hello,
            "disconnect": self._process_disconnect,
            "ssl-upgrade": self._process_ssl_upgrade,
            CONNECTION_LOST: self._process_connection_lost,
            GIBBERISH: self._process_gibberish,
            INVALID: self._process_invalid,
        }

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

    def add_listen_socket(self, socktype: str, sock, options: dict) -> None:
        info = self.socket_info.get(sock)
        netlog("add_listen_socket(%s, %s, %s) info=%s", socktype, sock, options, info)
        cleanup = add_listen_socket(socktype, sock, info, self, self._new_connection, options)
        if cleanup:
            self.socket_cleanup.append(cleanup)

    def _new_connection(self, socktype: str, listener, handle: int = 0):
        """
            Accept the new connection,
            verify that there aren't too many,
            start a thread to dispatch it to the correct handler.
        """
        log("_new_connection%s", (listener, socktype, handle))
        if self._closing:
            netlog("ignoring new connection during shutdown")
            return False
        if not socktype:
            netlog.error(f"Error: cannot find socket type for {listener!r}")
            return True
        # TODO: just like add_listen_socket above, this needs refactoring
        socket_options = self.socket_options.get(listener, {})
        if socktype == "named-pipe":
            from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
            conn: Connection = NamedPipeConnection(listener.pipe_name, handle, socket_options)
            netlog.info("New %s connection received on %s", socktype, conn.target)
            self.make_protocol(socktype, conn, socket_options)
            return True

        conn = accept_connection(socktype, listener, self._socket_timeout, socket_options)
        if conn is None:
            return True
        # limit number of concurrent network connections:
        if socktype != "socket" and len(self._potential_protocols) >= self._max_connections:
            netlog.error("Error: too many connections (%i)", len(self._potential_protocols))
            netlog.error(" ignoring new one: %s", conn.endpoint)
            force_close_connection(conn)
            return True
        # from here on, we run in a thread, so we can poll (peek does)
        socket_info = self.socket_info.get(listener)
        start_thread(self.handle_new_connection, f"new-{socktype}-connection", True,
                     args=(conn, socket_info, socket_options))
        return True

    def new_conn_err(self, conn, sock, socktype: str, socket_info, packet_type: str, msg=None) -> None:
        # not an xpra client
        netlog("new_conn_err", exc_info=True)
        log_fn = netlog.debug if packet_type == "http" else netlog.error
        log_fn("Error: %s connection failed:", socktype)
        if conn.remote:
            log_fn(" packet from %s", pretty_socket(conn.remote))
        if socket_info:
            log_fn(" received on %s", pretty_socket(socket_info))
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

    def handle_new_connection(self, conn, socket_info, socket_options: dict) -> None:
        """
            Use peek to decide what sort of connection this is,
            and start the appropriate handler for it.
        """
        sock = conn._socket
        address = conn.remote
        socktype = conn.socktype
        peername = conn.endpoint

        sockname = sock.getsockname()
        target = peername or sockname
        sock.settimeout(self._socket_timeout)

        netlog("handle_new_connection%s sockname=%s, target=%s",
               (conn, socket_info, socket_options), sockname, target)
        # peek so we can detect invalid clients early,
        # or handle non-xpra / wrapped traffic:
        timeout = PEEK_TIMEOUT_MS
        if socktype == "rfb":
            # rfb does not send any data, waits for a server packet
            # so don't bother waiting for something that should never come:
            timeout = 0
        elif socktype == "socket":
            timeout = SOCKET_PEEK_TIMEOUT_MS
        peek_data = b""
        if timeout > 0:
            peek_data = peek_connection(conn, timeout)
        line1 = peek_data.split(b"\n")[0]
        netlog("socket peek=%s", Ellipsizer(peek_data, limit=512))
        packet_type = guess_packet_type(peek_data)
        if peek_data:
            netlog("socket peek hex=%s", hexstr(peek_data[:128]))
            netlog("socket peek line1=%s", Ellipsizer(line1))
            netlog("guess_packet_type(..)=%s", packet_type)

        def ssl_wrap() -> SSLSocketConnection | None:
            ssl_sock = self._ssl_wrap_socket(socktype, sock, socket_options)
            ssllog("ssl wrapped socket(%s)=%s", sock, ssl_sock)
            if ssl_sock is None:
                return None
            ssl_conn = SSLSocketConnection(ssl_sock, sockname, address, target, socktype, socket_options=socket_options)
            ssllog("ssl_wrap()=%s", ssl_conn)
            return ssl_conn

        def can_upgrade_to(to_socktype: str) -> bool:
            return self.can_upgrade(socktype, to_socktype, socket_options)

        if socktype in ("ssl", "wss"):
            # verify that this isn't plain HTTP / xpra:
            if packet_type not in ("ssl", ""):
                self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                return
            # always start by wrapping with SSL:
            ssl_conn = ssl_wrap()
            if not ssl_conn:
                return
            http = False
            if socktype == "wss":
                http = True
            else:
                assert socktype == "ssl"
                if can_upgrade_to("wss") and self.ssl_mode.lower() in TRUE_OPTIONS or self.ssl_mode == "auto":
                    # look for HTTPS request to handle:
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
                    self.new_conn_err(conn, sock, socktype, socket_info, packet_type,
                                      "the builtin http server is not enabled")
                    return
                self.start_http_socket(socktype, ssl_conn, socket_options, True, peek_data)
            else:
                ssl_conn._socket.settimeout(self._socket_timeout)
                log_new_connection(ssl_conn, socket_info)
                self.make_protocol(socktype, ssl_conn, socket_options)
            return

        if socktype == "ws":
            if peek_data:
                if packet_type == "ssl" and can_upgrade_to("wss"):
                    ssllog("ws socket receiving ssl, upgrading to wss")
                    conn = ssl_wrap()
                    if conn is None:
                        return
                elif packet_type not in (None, "http"):
                    self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                    return
            self.start_http_socket(socktype, conn, socket_options, False, peek_data)
            return

        if socktype == "rfb":
            if peek_data and peek_data[:4] != b"RFB " and can_upgrade_to("rfb"):
                self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                return
            self.handle_rfb_connection(conn)
            return

        if socktype == "rdp":
            if peek_data and peek_data[:2] != b"\x03\x00":
                self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                return
            self.handle_rdp_connection(conn)
            return

        if socktype == "ssh":
            conn = self.handle_ssh_connection(conn, socket_options)
            if not conn:
                return
            peek_data, line1, packet_type = b"", b"", ""

        if socktype in ("tcp", "socket", "named-pipe") and peek_data:
            # see if the packet data is actually xpra or something else
            # that we need to handle via a SSL wrapper or the websocket adapter:
            try:
                cont, conn, peek_data = self.may_wrap_socket(conn, socktype, socket_info, socket_options, peek_data)
                netlog("may_wrap_socket(..)=(%s, %s, %r)", cont, conn, Ellipsizer(peek_data))
                if not cont:
                    return
                packet_type = guess_packet_type(peek_data)
            except OSError as e:
                netlog("socket wrapping failed", exc_info=True)
                self.new_conn_err(conn, sock, socktype, socket_info, packet_type, str(e))
                return

        if packet_type not in ("xpra", ""):
            self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
            return

        # get the new socket object as we may have wrapped it with ssl:
        sock = getattr(conn, "_socket", sock)
        pre_read = []
        if socktype == "socket" and not peek_data:
            # try to read from this socket,
            # so short-lived probes don't go through the whole protocol instantiation
            try:
                sock.settimeout(0.001)
                data = conn.read(1)
                if not data:
                    netlog("%s connection already closed", socktype)
                    force_close_connection(conn)
                    return
                netlog("pre_read data=%r", data)
                pre_read.append(data)
            except OSError:
                netlog.error("Error reading from %s", conn, exc_info=True)
                return
        sock.settimeout(self._socket_timeout)
        log_new_connection(conn, socket_info)
        proto = self.make_protocol(socktype, conn, socket_options, pre_read=pre_read)
        if socktype == "tcp" and not peek_data and self._rfb_upgrade > 0:
            t = GLib.timeout_add(self._rfb_upgrade * 1000, self.try_upgrade_to_rfb, proto)
            self.socket_rfb_upgrade_timer[proto] = t

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
            from xpra.net.ssl_util import ssl_wrap_socket
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

    def handle_ssh_connection(self, conn, socket_options):
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
            display_name=self.display_name,
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

    def do_make_protocol(self, socktype: str, conn, socket_options, protocol_class,
                         pre_read: Iterable[bytes] = ()) -> SocketProtocol:
        """ create a new Protocol instance and start it """
        netlog("make_protocol%s", (socktype, conn, socket_options, protocol_class, pre_read))
        socktype = socktype.lower()
        protocol = protocol_class(conn)
        protocol._pre_read = list(pre_read)
        protocol.socket_type = socktype
        self._potential_protocols.append(protocol)
        protocol.authenticators = ()
        protocol.encryption = socket_options.get("encryption", "")
        protocol.keyfile = socket_options.get("encryption-keyfile", "") or socket_options.get("keyfile", "")
        raw_keydata = socket_options.get("encryption-keydata", "") or socket_options.get("keydata", "")
        protocol.keydata = parse_encoded_bin_data(raw_keydata)
        if socktype in ENCRYPTED_SOCKET_TYPES:
            # special case for legacy encryption code:
            protocol.encryption = protocol.encryption or self.tcp_encryption
            protocol.keyfile = protocol.keyfile or self.tcp_encryption_keyfile
        enc = (protocol.encryption or "").lower()
        if enc and not enc.startswith("aes") and not str_to_bool(enc, False):
            protocol.encryption = None
        netlog("%s: encryption=%s, keyfile=%s", socktype, protocol.encryption, protocol.keyfile)
        if protocol.encryption:
            from xpra.net.crypto import crypto_backend_init
            crypto_backend_init()
            from xpra.net.crypto import (
                ENCRYPT_FIRST_PACKET,
                DEFAULT_IV,
                DEFAULT_SALT,
                DEFAULT_KEY_HASH,
                DEFAULT_KEYSIZE,
                DEFAULT_ITERATIONS,
                DEFAULT_ALWAYS_PAD,
                DEFAULT_STREAM,
                INITIAL_PADDING,
            )
            if ENCRYPT_FIRST_PACKET:
                authlog(f"encryption={protocol.encryption}, keyfile={protocol.keyfile!r}")
                password = protocol.keydata or self.get_encryption_key((), protocol.keyfile)
                iv = strtobytes(DEFAULT_IV)
                protocol.set_cipher_in(protocol.encryption, iv,
                                       password, DEFAULT_SALT, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
                                       DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_ALWAYS_PAD, DEFAULT_STREAM)
        protocol.invalid_header = self.invalid_header
        authlog(f"socktype={socktype}, encryption={protocol.encryption}, keyfile={protocol.keyfile!r}")
        protocol.start()
        self.schedule_verify_connection_accepted(protocol, self._accept_timeout)
        return protocol

    def may_wrap_socket(self, conn, socktype: str, socket_info, socket_options: dict, peek_data=b"") \
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
        packet_type = guess_packet_type(peek_data)
        if packet_type == "xpra":
            netlog("may_wrap_socket: xpra protocol header '%s', not wrapping", peek_data[0])
            # xpra packet header, no need to wrap this connection
            return True, conn, peek_data
        frominfo = pretty_socket(conn.remote)
        netlog("may_wrap_socket(..) peek_data=%s from %s", Ellipsizer(peek_data), frominfo)
        netlog("may_wrap_socket(..) packet_type=%s", packet_type)

        def can_upgrade_to(to_socktype: str) -> bool:
            return self.can_upgrade(socktype, to_socktype, socket_options)

        def conn_err(msg) -> tuple[bool, Any, bytes]:
            self.new_conn_err(conn, conn._socket, socktype, socket_info, packet_type, msg)
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
        packet_type = guess_packet_type(data)
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
    def start_http_socket(self, socktype: str, conn, socket_options: dict, is_ssl: bool = False,
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

    def start_http(self, socktype: str, conn, socket_options: dict, is_ssl: bool, req_info: str,
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
        # loose coupling with xpra.server.mixins.http:
        return getattr(self, "_http_scripts", {})

    def is_timedout(self, protocol: SocketProtocol) -> bool:
        # subclasses may override this method (ServerBase does)
        v = not protocol.is_closed() and protocol in self._potential_protocols
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def schedule_verify_connection_accepted(self, protocol: SocketProtocol, timeout: int = 60) -> None:
        t = GLib.timeout_add(timeout * 1000, self.verify_connection_accepted, protocol)
        self.socket_verify_timer[protocol] = t

    def verify_connection_accepted(self, protocol: SocketProtocol):
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
                    except OSError:
                        data = b""
                    if data:
                        messages.append(f" read buffer={data!r}")
                        packet_type = guess_packet_type(data)
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

    def disconnect_client(self, protocol: SocketProtocol, reason: str | ConnectionMessage, *extra):
        netlog("disconnect_client(%s, %s, %s)", protocol, reason, extra)
        if protocol and not protocol.is_closed():
            self.disconnect_protocol(protocol, reason, *extra)

    def disconnect_protocol(self, protocol: SocketProtocol, *reasons):
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

    def _process_disconnect(self, proto: SocketProtocol, packet: PacketType) -> None:
        info = str(packet[1])
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

    def _process_connection_lost(self, proto: SocketProtocol, packet: PacketType) -> None:
        netlog("process_connection_lost(%s, %s)", proto, packet)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto in self._potential_protocols:
            if not proto.is_closed():
                self._log_disconnect(proto, "Connection lost")
            self._potential_protocols.remove(proto)
        self.cleanup_protocol(proto)

    def _process_gibberish(self, proto: SocketProtocol, packet: PacketType) -> None:
        message, data = packet[1:3]
        netlog("Received uninterpretable nonsense from %s: %s", proto, message)
        netlog(" data: %s", Ellipsizer(data))
        self.disconnect_client(proto, message)

    def _process_invalid(self, protocol: SocketProtocol, packet: PacketType) -> None:
        message, data = packet[1:3]
        netlog(f"Received invalid packet: {message}")
        netlog(" data: %s", Ellipsizer(data))
        self.disconnect_client(protocol, message)

    # #####################################################################
    # hello / authentication:
    def send_version_info(self, proto: SocketProtocol, full: bool = False) -> None:
        version = version_str() if (full and FULL_INFO) else XPRA_VERSION.split(".", 1)[0]
        proto.send_now(("hello", {"version": version}))
        # client is meant to close the connection itself, but just in case:
        GLib.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.DONE, "version sent")

    def _process_hello(self, proto: SocketProtocol, packet: PacketType) -> None:
        capabilities = packet[1]
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
        if c.strget("request") == "version":
            self.send_version_info(proto, c.boolget("full-version-request"))
            return
        # verify version:
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, ConnectionMessage.VERSION_ERROR, f"incompatible version: {verr!r}")
            proto.close()
            return
        # this will call auth_verified if successful
        # it may also just send challenge packets,
        # in which case we'll end up here parsing the hello again
        start_thread(self.verify_auth, "authenticate connection", daemon=True, args=(proto, packet, c))

    def make_authenticators(self, socktype: str, remote: dict[str, Any], conn) -> Sequence[Any]:
        authlog("make_authenticators%s socket options=%s", (socktype, remote, conn), conn.options)
        sock_options = conn.options
        sock_auth = sock_options.get("auth", "")
        if sock_auth:
            # per socket authentication option:
            # ie: --bind-tcp=0.0.0.0:10000,auth=hosts,auth=file:filename=pass.txt:foo=bar
            # -> sock_auth = ["hosts", "file:filename=pass.txt:foo=bar"]
            if not isinstance(sock_auth, (list, dict)):
                sock_auth = sock_auth.split(",")
            auth_classes = self.get_auth_modules(conn.socktype, sock_auth)
        else:
            # use authentication configuration defined for all sockets of this type:
            if socktype not in self.auth_classes:
                raise RuntimeError(f"invalid socket type {socktype!r}")
            auth_classes = self.auth_classes[socktype]
        i = 0
        authenticators = []
        if auth_classes:
            authlog(f"creating authenticators {csv(auth_classes)} for {socktype}")
            for auth_name, _, aclass, options in auth_classes:
                opts = dict(options)
                opts["remote"] = remote
                opts.update(sock_options)
                opts["connection"] = conn

                def parse_socket_dirs(v) -> Sequence[str]:
                    if isinstance(v, (tuple, list)):
                        return v
                    # FIXME: this can never actually match ","
                    # because we already split connection options with it.
                    # We need to change the connection options parser to be smarter
                    return str(v).split(",")

                opts["socket-dirs"] = parse_socket_dirs(opts.get("socket-dirs", self._socket_dirs))
                try:
                    for o in ("self",):
                        if o in opts:
                            raise ValueError(f"illegal authentication module options {o!r}")
                    authlog(f"{auth_name} : {aclass}({opts})")
                    authenticator = aclass(**opts)
                except Exception:
                    authlog(f"{aclass}({opts})", exc_info=True)
                    raise
                authlog(f"authenticator {i}={authenticator}")
                authenticators.append(authenticator)
                i += 1
        return tuple(authenticators)

    def send_challenge(self, proto: SocketProtocol, salt: bytes, auth_caps: dict, digest: str, salt_digest: str,
                       prompt: str = "password") -> None:
        proto.send_now(("challenge", salt, auth_caps, digest, salt_digest, prompt))
        self.schedule_verify_connection_accepted(proto, CHALLENGE_TIMEOUT)

    def auth_failed(self, proto: SocketProtocol, msg: str | ConnectionMessage, authenticator=None) -> None:
        authlog.warn("Warning: authentication failed")
        wmsg = nicestr(msg)
        if authenticator:
            wmsg = f"{authenticator!r}: "+wmsg
        authlog.warn(f" {wmsg}")
        GLib.timeout_add(1000, self.disconnect_client, proto, msg)

    def verify_auth(self, proto: SocketProtocol, packet, c: typedict) -> None:
        remote = {}
        for key in ("hostname", "uuid", "session-id", "username", "name"):
            v = c.strget(key)
            if v:
                remote[key] = v
        conn = proto._conn
        if not conn or proto.is_closed():
            authlog(f"connection {proto} is already closed")
            return
        if not proto.authenticators:
            socktype = conn.socktype_wrapped
            try:
                proto.authenticators = self.make_authenticators(socktype, remote, conn)
            except ValueError as e:
                authlog(f"instantiating authenticator for {socktype}", exc_info=True)
                self.auth_failed(proto, str(e))
                return
            except Exception as e:
                authlog(f"instantiating authenticator for {socktype}", exc_info=True)
                authlog.error(f"Error instantiating authenticators for {proto.socket_type} connection:")
                authlog.estr(e)
                self.auth_failed(proto, str(e))
                return

        digest_modes = c.strtupleget("digest", ("hmac",))
        salt_digest_modes = c.strtupleget("salt-digest", ("xor",))
        # client may have requested encryption:
        auth_caps = self.setup_encryption(proto, c)
        if auth_caps is None:
            return

        # try to auto upgrade to ssl:
        packet_types = c.strtupleget("packet-types", ())
        if SSL_UPGRADE and not auth_caps and "ssl-upgrade" in packet_types and conn.socktype in ("tcp",):
            options = conn.options
            if options.get("ssl-upgrade", "yes").lower() in TRUE_OPTIONS:
                ssl_options = self.get_ssl_socket_options(options)
                cert = ssl_options.get("cert", "")
                if cert:
                    log.info(f"sending ssl upgrade for {conn}")
                    cert_data = load_binary_file(cert)
                    ssl_attrs = {"cert-data": cert_data}
                    proto.send_now(("ssl-upgrade", ssl_attrs))
                    return

        def send_fake_challenge() -> None:
            # fake challenge so the client will send the real hello:
            salt: bytes = get_salt()
            digest: str = choose_digest(digest_modes)
            salt_digest: str = choose_digest(salt_digest_modes)
            self.send_challenge(proto, salt, auth_caps, digest, salt_digest)

        # skip the authentication module we have "passed" already:
        remaining_authenticators = tuple(x for x in proto.authenticators if not x.passed)
        authlog("processing authentication with %s, remaining=%s, digest_modes=%s, salt_digest_modes=%s",
                proto.authenticators, remaining_authenticators, digest_modes, salt_digest_modes)
        # verify each remaining authenticator:
        for index, authenticator in enumerate(proto.authenticators):
            if authenticator not in remaining_authenticators:
                authlog(f"authenticator[{index}]={authenticator} (already passed)")
                continue

            def fail(msg: str | ConnectionMessage) -> None:
                self.auth_failed(proto, msg, authenticator)

            req = authenticator.requires_challenge()
            csent = authenticator.challenge_sent
            authlog(f"authenticator[{index}]={authenticator}, requires-challenge={req}, challenge-sent={csent}")
            if not req:
                # this authentication module does not need a challenge
                # (ie: "peercred", "exec" or "none")
                if not authenticator.authenticate(c):
                    fail("authentication failed")
                    return
                authenticator.passed = True
                authlog(f"authentication passed for {authenticator} (no challenge provided)")
                continue
            if not csent:
                # we'll re-schedule this when we call send_challenge()
                # as the authentication module is free to take its time
                self.cancel_verify_connection_accepted(proto)
                # note: we may have received a challenge_response from a previous auth module's challenge
                try:
                    salt, digest = authenticator.get_challenge(digest_modes)
                except ValueError as e:
                    authlog.warn("Warning: unable to generate an authentication challenge")
                    authlog.warn(" %s", e)
                    fail("authentication challenge processing error")
                    return
                if not (salt or digest):
                    if authenticator.requires_challenge():
                        fail("invalid state, unexpected challenge response")
                        return
                    authlog.warn(f"Warning: authentication module {authenticator!r} does not require any credentials")
                    authlog.warn(f" but the client {proto} supplied them")
                    # fake challenge so the client will send the real hello:
                    send_fake_challenge()
                    return
                actual_digest = digest.split(":", 1)[0]
                authlog(f"get_challenge({digest_modes})={hexstr(salt)}, {digest}")
                countinfo = ""
                if len(proto.authenticators) > 1:
                    countinfo += f" ({index + 1} of {len(proto.authenticators)})"
                authlog.info(f"Authentication required by {authenticator!r} authenticator module{countinfo}")
                authlog.info(
                    f" sending challenge using {actual_digest!r} digest over {conn.socktype_wrapped} connection")
                if actual_digest not in digest_modes:
                    fail(f"cannot proceed without {actual_digest!r} digest support")
                    return
                salt_digest: str = authenticator.choose_salt_digest(salt_digest_modes)
                authlog(f"{authenticator}.choose_salt_digest({salt_digest_modes})={salt_digest!r}")
                if salt_digest in ("xor", "des"):
                    fail(f"insecure salt digest {salt_digest!r} rejected")
                    return
                authlog(f"{authenticator!r} sending challenge {authenticator.prompt!r}")
                self.send_challenge(proto, salt, auth_caps, digest, salt_digest, authenticator.prompt)
                return
            if not authenticator.authenticate(c):
                fail(ConnectionMessage.AUTHENTICATION_FAILED)
                return
        client_expects_challenge = c.strget("challenge")
        if client_expects_challenge:
            authlog.warn("Warning: client expects an authentication challenge,")
            authlog.warn(" sending a fake one")
            send_fake_challenge()
            return
        authlog(f"all {len(proto.authenticators)} authentication modules passed")
        capabilities = packet[1]
        c = typedict(capabilities)
        self.auth_verified(proto, c, auth_caps)

    def auth_verified(self, proto: SocketProtocol, caps: typedict, auth_caps: dict) -> None:
        command_req = tuple(str(x) for x in caps.tupleget("command_request"))
        if command_req:
            # call from UI thread:
            authlog(f"auth_verified(..) command request={command_req}")
            GLib.idle_add(self.handle_command_request, proto, *command_req)
            return
        # continue processing hello packet in UI thread:
        GLib.idle_add(self.call_hello_oked, proto, caps, auth_caps)

    def _process_ssl_upgrade(self, proto: SocketProtocol, packet: PacketType) -> None:
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

    def setup_encryption(self, proto: SocketProtocol, c: typedict) -> dict[str, Any] | None:
        def auth_failed(msg: str) -> None:
            self.auth_failed(proto, msg)
            return None

        c = typedict(c.dictget("encryption") or {})
        cipher = c.strget("cipher").upper()
        cryptolog(f"setup_encryption(..) for cipher={cipher!r} : {c}")
        if not cipher:
            if proto.encryption:
                cryptolog(f"client does not provide encryption tokens: encryption={c}")
                return auth_failed("missing encryption tokens from client")
            # no encryption requested
            return {}

        # check that the server supports encryption:
        if not proto.encryption:
            return auth_failed("the server does not support encryption on this connection")
        server_cipher = proto.encryption.split("-")[0].upper()
        if server_cipher != cipher:
            return auth_failed(
                f"the server is configured for {server_cipher!r} not {cipher!r} as requested by the client")
        from xpra.net.crypto import (
            DEFAULT_PADDING, ALL_PADDING_OPTIONS,
            DEFAULT_MODE, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
            DEFAULT_KEY_STRETCH, DEFAULT_ALWAYS_PAD, DEFAULT_STREAM,
            new_cipher_caps, get_ciphers, get_key_hashes,
        )
        cipher_mode = c.strget("mode", "").upper()
        if not cipher_mode:
            cipher_mode = DEFAULT_MODE
        if proto.encryption.find("-") > 0:
            # server specifies the mode to use
            server_cipher_mode = proto.encryption.split("-")[1].upper()
            if server_cipher_mode != cipher_mode:
                return auth_failed(f"the server is configured for {server_cipher}-{server_cipher_mode}"
                                   f"not {cipher}-{cipher_mode} as requested by the client")
        cipher_iv = c.strget("iv")
        iterations = c.intget("key_stretch_iterations")
        key_salt = c.bytesget("key_salt")
        key_hash = c.strget("key_hash", DEFAULT_KEY_HASH)
        key_stretch = c.strget("key_stretch", DEFAULT_KEY_STRETCH)
        padding = c.strget("padding", DEFAULT_PADDING)
        always_pad = c.boolget("always-pad", DEFAULT_ALWAYS_PAD)
        stream = c.boolget("stream", DEFAULT_STREAM)
        padding_options = c.strtupleget("padding.options", (DEFAULT_PADDING,))
        ciphers = get_ciphers()
        if cipher not in ciphers:
            authlog.warn(f"Warning: unsupported cipher: {cipher!r}")
            if ciphers:
                authlog.warn(" should be: " + csv(ciphers))
            return auth_failed("unsupported cipher")
        if key_stretch != "PBKDF2":
            return auth_failed(f"unsupported key stretching {key_stretch!r}")
        encryption_key = proto.keydata or self.get_encryption_key(proto.authenticators, proto.keyfile)
        if not encryption_key:
            return auth_failed("encryption key is missing")
        if padding not in ALL_PADDING_OPTIONS:
            return auth_failed(f"unsupported padding {padding!r}")
        key_hashes = get_key_hashes()
        if key_hash not in key_hashes:
            return auth_failed(f"unsupported key hash algorithm {key_hash!r}")
        cryptolog("setting output cipher using %s-%s encryption key '%s'",
                  cipher, cipher_mode, repr_ellipsized(encryption_key))
        key_size = c.intget("key_size", DEFAULT_KEYSIZE)
        try:
            proto.set_cipher_out(cipher + "-" + cipher_mode, strtobytes(cipher_iv),
                                 encryption_key, key_salt, key_hash, key_size,
                                 iterations, padding, always_pad, stream)
        except ValueError as e:
            return auth_failed(f"{e}")
        # use the same cipher as used by the client:
        encryption_caps = new_cipher_caps(proto, cipher, cipher_mode or DEFAULT_MODE, encryption_key,
                                          padding_options, always_pad, stream)
        cryptolog("server encryption=%s", encryption_caps)
        return {"encryption": encryption_caps}

    def get_encryption_key(self, authenticators: tuple = (), keyfile: str = "") -> bytes:
        # if we have a keyfile specified, use that:
        authlog(f"get_encryption_key({authenticators}, {keyfile})")
        if keyfile:
            authlog(f"loading encryption key from keyfile {keyfile!r}")
            v = filedata_nocrlf(keyfile)
            if v:
                return v
        KVAR = "XPRA_ENCRYPTION_KEY"
        v = os.environ.get(KVAR, "")
        if v:
            authlog(f"using encryption key from {KVAR!r} environment variable")
            return strtobytes(v)
        if authenticators:
            for authenticator in authenticators:
                v = authenticator.get_password()
                if v:
                    authlog(f"using password from authenticator {authenticator}")
                    return v
        return b""

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
            msg = f"`{request}` requests are not enabled for this connection"
            self.send_disconnect(proto, ConnectionMessage.PERMISSION_ERROR, msg)
            return True
        return self.do_handle_hello_request(request, proto, caps)

    def do_handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        if request == "connect_test":
            ctr = caps.strget("connect_test_request")
            response = {"connect_test_response": ctr}
            proto.send_now(("hello", response))
            return True
        if request == "id":
            self.send_id_info(proto)
            return True
        if request == "info":
            self.send_hello_info(proto)
            return True
        if request == "screenshot" and hasattr(self, "make_screenshot_packet"):
            packet = self.make_screenshot_packet()
            proto.send_now(packet)
            return True
        return False

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
        self.reset_server_timeout(False)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)

    def reset_server_timeout(self, reschedule: bool = True) -> None:
        timeoutlog("reset_server_timeout(%s) server_idle_timeout=%s, server_idle_timer=%s",
                   reschedule, self.server_idle_timeout, self.server_idle_timer)
        if self.server_idle_timeout <= 0:
            return
        if self.server_idle_timer:
            GLib.source_remove(self.server_idle_timer)
            self.server_idle_timer = 0
        if reschedule:
            self.server_idle_timer = GLib.timeout_add(self.server_idle_timeout * 1000, self.server_idle_timedout)

    def server_idle_timedout(self) -> None:
        timeoutlog.info("No valid client connections for %s seconds, exiting the server", self.server_idle_timeout)
        self.clean_quit(ServerExitMode.NORMAL)

    def make_hello(self, source) -> dict[str, Any]:
        now = time()
        capabilities = get_network_caps(FULL_INFO) | proto_crypto_caps(None if source is None else source.protocol)
        if source is None or "versions" in source.wants:
            capabilities |= self.get_minimal_server_info()
        capabilities |= {
            "version": vparts(XPRA_VERSION, FULL_INFO + 1),
            "start_time": int(self.start_time),
            "current_time": int(now),
            "elapsed_time": int(now - self.start_time),
            "server_type": "core",
            "server.mode": self.get_server_mode(),
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
        if source is None or "versions" in source.wants:
            capabilities["uuid"] = get_user_uuid()
            mid = get_machine_id()
            if mid:
                capabilities["machine_id"] = mid
        if self.session_name:
            capabilities["session_name"] = self.session_name
        return capabilities

    ######################################################################
    # info:
    def send_id_info(self, proto: SocketProtocol) -> None:
        log("id info request from %s", proto._conn)
        proto._log_stats = False
        proto.send_now(("hello", self.get_session_id_info()))

    def get_session_id_info(self) -> dict[str, Any]:
        # minimal information for identifying the session
        id_info = {
            "session-type": self.session_type,
            "session-name": self.session_name,
            "uuid": self.uuid,
            "platform": sys.platform,
            "pid": os.getpid(),
            "machine-id": get_machine_id(),
            "version": XPRA_NUMERIC_VERSION[:FULL_INFO+1],
        }
        display = os.environ.get("DISPLAY")
        if display:
            id_info["display"] = display
        return id_info

    def send_hello_info(self, proto: SocketProtocol) -> None:
        # Note: this can be overridden in subclasses to pass arguments to get_ui_info()
        # (ie: see server_base)
        if not is_request_allowed(proto, "info"):
            self.do_send_info(proto, {"error": "`info` requests are not enabled for this connection"})
            return

        def cb(proto, info) -> None:
            self.do_send_info(proto, info)

        self.get_all_info(cb, proto)

    def do_send_info(self, proto: SocketProtocol, info: dict[str, Any]) -> None:
        proto.send_now(("hello", notypedict(info)))

    def get_all_info(self, callback: Callable, proto: SocketProtocol | None = None, *args):
        start = monotonic()
        ui_info: dict[str, Any] = self.get_ui_info(proto, *args)
        end = monotonic()
        log("get_all_info: ui info collected in %ims", (end - start) * 1000)
        start_thread(self._get_info_in_thread, "Info", daemon=True, args=(callback, ui_info, proto, args))

    def _get_info_in_thread(self, callback: Callable, ui_info: dict[str, Any], proto: SocketProtocol, args):
        log("get_info_in_thread%s", (callback, {}, proto, args))
        start = monotonic()
        # this runs in a non-UI thread
        with log.trap_error("Error during info collection"):
            info = self.get_info(proto, *args)
            merge_dicts(ui_info, info)
        end = monotonic()
        log("get_all_info: non ui info collected in %ims", (end - start) * 1000)
        callback(proto, ui_info)

    def get_ui_info(self, _proto: SocketProtocol, *_args) -> dict[str, Any]:
        # this function is for info which MUST be collected from the UI thread
        return {}

    def get_thread_info(self, proto: SocketProtocol) -> dict[str, Any]:
        return get_thread_info(proto)

    def get_minimal_server_info(self) -> dict[str, Any]:
        return {
            "mode": self.get_server_mode(),
            "session-type": self.session_type,
            "uuid": self.uuid,
            "machine-id": get_machine_id(),
        }

    def get_server_info(self) -> dict[str, Any]:
        # this function is for non UI thread info
        info = get_server_info()
        now = time()
        info |= {
            "type": "Python",
            "python": {"version": parse_version(platform.python_version())[:FULL_INFO + 1]},
            "start_time": int(self.start_time),
            "current_time": int(now),
            "elapsed_time": int(now - self.start_time),
        }
        return info

    def get_server_load_info(self) -> dict[str, Any]:
        if POSIX:
            try:
                return {"load": tuple(int(x * 1000) for x in os.getloadavg())}
            except OSError:
                log("cannot get load average", exc_info=True)
        return {}

    def get_server_exec_info(self) -> dict[str, Any]:
        info = {
            "argv": sys.argv,
            "path": sys.path,
            "exec_prefix": sys.exec_prefix,
            "executable": sys.executable,
            "idle-timeout": int(self.server_idle_timeout),
            "pid": os.getpid(),
        }
        if self.pidfile:
            info["pidfile"] = {
                "path": self.pidfile,
                "inode": self.pidinode,
            }
        logfile = os.environ.get("XPRA_SERVER_LOG")
        if logfile:
            info["log-file"] = logfile
        return info

    def get_info(self, proto, *_args) -> dict[str, Any]:
        start = monotonic()
        # this function is for non UI thread info
        info = {}

        def up(prefix, d) -> None:
            info[prefix] = d

        authenticated = proto and proto.authenticators
        full = FULL_INFO > 0 or authenticated
        if full:
            si = self.get_server_info()
            si.update(self.get_server_load_info())
            si.update(self.get_server_exec_info())
            if SYSCONFIG:
                si["sysconfig"] = get_sysconfig_info()
        else:
            si = self.get_minimal_server_info()
        si.update(get_host_info(FULL_INFO or authenticated))
        up("server", si)
        if self.session_name:
            info["session"] = {"name": self.session_name}

        if full:
            ni = get_net_info()
            ni |= {
                "sockets": self.get_socket_info(),
                "encryption": self.encryption or "",
                "tcp-encryption": self.tcp_encryption or "",
                "packet-handlers": GLibPacketHandler.get_info(self),
                "www": {
                    "": self._html,
                    "websocket-upgrade": self.websocket_upgrade,
                    "dir": self._www_dir or "",
                    "http-headers-dirs": self._http_headers_dirs or "",
                },
                "mdns": self.mdns,
            }
            up("network", ni)
            up("threads", self.get_thread_info(proto))
            up("logging", get_log_info())
            from xpra.platform.info import get_sys_info
            up("sys", get_sys_info())
            up("env", get_env_info())
            if self.child_reaper:
                info.update(self.child_reaper.get_info())
        end = monotonic()
        log("ServerCore.get_info took %ims", (end - start) * 1000)
        return info

    def get_packet_handlers_info(self) -> dict[str, Any]:
        return {
            "default": sorted(self._default_packet_handlers.keys()),
        }

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
        for sock_details, options in self._socket_info.items():
            socktype, _, info, _ = sock_details
            if not info:
                continue
            add_listener(socktype, info)
            if not SHOW_NETWORK_ADDRESSES:
                continue
            if socktype not in ("tcp", "ssl", "ws", "wss", "ssh"):
                # we expose addresses only for TCP sockets
                continue
            upnp_address = options.get("upnp-address")
            if upnp_address:
                add_address(socktype, *upnp_address)
            if len(info) != 2 or not isinstance(info[0], str) or not isinstance(info[1], int):
                # unsupported listener info format
                continue
            address, port = info
            if address not in ("0.0.0.0", "::/0", "::"):
                # not a wildcard address, use it as-is:
                add_address(socktype, address, port)
                continue
            if not netifaces:
                if first_time("netifaces-socket-address"):
                    netlog.warn("Warning: netifaces is missing")
                    netlog.warn(" socket addresses cannot be queried")
                continue
            ips = []
            for inet in get_interfaces_addresses().values():
                # ie: inet = {
                #    18: [{'addr': ''}],
                #    2: [{'peer': '127.0.0.1', 'netmask': '255.0.0.0', 'addr': '127.0.0.1'}],
                #    30: [{'peer': '::1', 'netmask': 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', 'addr': '::1'},
                #         {'peer': '', 'netmask': 'ffff:ffff:ffff:ffff::', 'addr': 'fe80::1%lo0'}]
                #    }
                for v in (socket.AF_INET, socket.AF_INET6):
                    addresses = inet.get(v, ())
                    for addr in addresses:
                        # ie: addr = {'peer': '127.0.0.1', 'netmask': '255.0.0.0', 'addr': '127.0.0.1'}]
                        ip = addr.get("addr")
                        if ip and ip not in ips:
                            ips.append(ip)
            for ip in ips:
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
        log.error("Error: RDP protocol is not supported by this server")
        log("handle_rdp_connection%s", (conn, data))
        force_close_connection(conn)
