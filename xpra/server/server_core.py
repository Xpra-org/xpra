# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
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
from urllib.parse import urlparse, parse_qsl, unquote
from weakref import WeakKeyDictionary
from time import sleep, time
from threading import Thread, Lock

from xpra.version_util import (
    XPRA_VERSION, full_version_str, version_compat_check, get_version_info_full,
    get_platform_info, get_host_info,
    )
from xpra.scripts.server import deadly_signal
from xpra.server.server_util import write_pidfile, rm_pidfile
from xpra.scripts.config import parse_bool, parse_with_unit, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.net.common import may_log_packet, SOCKET_TYPES, MAX_PACKET_SIZE
from xpra.net.socket_util import (
    hosts, mdns_publish, peek_connection,
    PEEK_TIMEOUT_MS, UNIXDOMAIN_PEEK_TIMEOUT_MS,
    add_listen_socket, accept_connection, guess_packet_type,
    )
from xpra.net.bytestreams import (
    SocketConnection, SSLSocketConnection,
    log_new_connection, pretty_socket, SOCKET_TIMEOUT,
    )
from xpra.net.net_util import (
    get_network_caps, get_info as get_net_info,
    import_netifaces, get_interfaces_addresses,
    )
from xpra.net.protocol import Protocol, sanity_checks
from xpra.net.digest import get_salt, gendigest, choose_digest
from xpra.platform import set_name, threaded_server_init
from xpra.platform.paths import (
    get_app_dir, get_system_conf_dirs, get_user_conf_dirs,
    get_icon_filename,
    )
from xpra.platform.dotxpra import DotXpra
from xpra.os_util import (
    register_SIGUSR_signals,
    get_frame_info, get_info_env, get_sysconfig_info,
    filedata_nocrlf, get_machine_id, get_user_uuid, platform_name, get_ssh_port,
    strtobytes, bytestostr, get_hex_uuid,
    getuid, monotonic_time, hexstr,
    WIN32, POSIX, BITS,
    parse_encoded_bin_data, load_binary_file,
    )
from xpra.server.background_worker import stop_worker, get_worker, add_work_item
from xpra.server.menu_provider import get_menu_provider
from xpra.server.auth.auth_helper import get_auth_module
from xpra.make_thread import start_thread
from xpra.util import (
    first_time, noerr,
    csv, merge_dicts, typedict, notypedict, flatten_dict,
    ellipsizer, dump_all_frames, envint, envbool, envfloat,
    SERVER_SHUTDOWN, SERVER_UPGRADE, LOGIN_TIMEOUT, DONE, PROTOCOL_ERROR,
    SERVER_ERROR, VERSION_ERROR, CLIENT_REQUEST, SERVER_EXIT,
    )
from xpra.log import Logger

log = Logger("server")
netlog = Logger("network")
ssllog = Logger("ssl")
httplog = Logger("http")
wslog = Logger("websocket")
proxylog = Logger("proxy")
commandlog = Logger("command")
authlog = Logger("auth")
timeoutlog = Logger("timeout")
dbuslog = Logger("dbus")
mdnslog = Logger("mdns")

main_thread = threading.current_thread()

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_MAX_CONCURRENT_CONNECTIONS", 100)
SIMULATE_SERVER_HELLO_ERROR = envbool("XPRA_SIMULATE_SERVER_HELLO_ERROR", False)
SERVER_SOCKET_TIMEOUT = envfloat("XPRA_SERVER_SOCKET_TIMEOUT", "0.1")
LEGACY_SALT_DIGEST = envbool("XPRA_LEGACY_SALT_DIGEST", False)
CHALLENGE_TIMEOUT = envint("XPRA_CHALLENGE_TIMEOUT", 120)
SYSCONFIG = envbool("XPRA_SYSCONFIG", True)
SHOW_NETWORK_ADDRESSES = envbool("XPRA_SHOW_NETWORK_ADDRESSES", True)
INIT_THREAD_TIMEOUT = envint("XPRA_INIT_THREAD_TIMEOUT", 10)
HTTP_HTTPS_REDIRECT = envbool("XPRA_HTTP_HTTPS_REDIRECT", True)

ENCRYPTED_SOCKET_TYPES = os.environ.get("XPRA_ENCRYPTED_SOCKET_TYPES", "tcp,ws")

HTTP_UNSUPORTED = b"""HTTP/1.1 400 Bad request syntax or unsupported method

<head>
<title>Server Error</title>
</head>
<body>
<h1>Server Error</h1>
<p>Error code 400.
<p>Message: this port does not support HTTP requests.
<p>Error code explanation: 400 = Bad request syntax or unsupported method.
</body>
"""


#class used to distinguish internal errors
#which should not be shown to the client,
#from useful messages we do want to pass on
class ClientException(Exception):
    pass


def get_server_info():
    #this function is for non UI thread info
    info = {
            "platform"  : get_platform_info(),
            "build"     : get_version_info_full(),
            }
    info.update(get_host_info())
    return info

def get_thread_info(proto=None):
    #threads:
    if proto:
        info_threads = proto.get_threads()
    else:
        info_threads = ()
    return get_frame_info(info_threads)


class ServerCore:
    """
        This is the simplest base class for servers.
        It only handles the connection layer:
        authentication and the initial handshake.
    """

    def __init__(self):
        log("ServerCore.__init__()")
        self.start_time = time()
        self.auth_classes = {}
        self._when_ready = []
        self.child_reaper = None
        self.original_desktop_display = None
        self.session_type = "unknown"
        self.display_name = ""
        self.dotxpra = None

        self._closing = False
        self._upgrading = False
        #networking bits:
        self._socket_info = {}
        self._potential_protocols = []
        self._tcp_proxy_clients = []
        self._tcp_proxy = ""
        self._rfb_upgrade = 0
        self._ssl_attributes = {}
        self._accept_timeout = SOCKET_TIMEOUT + 1
        self.ssl_mode = None
        self._html = False
        self._http_scripts = {}
        self._www_dir = None
        self._http_headers_dirs = ()
        self._aliases = {}
        self.socket_info = {}
        self.socket_options = {}
        self.socket_cleanup = []
        self.socket_verify_timer = WeakKeyDictionary()
        self.socket_rfb_upgrade_timer = WeakKeyDictionary()
        self._max_connections = MAX_CONCURRENT_CONNECTIONS
        self._socket_timeout = SERVER_SOCKET_TIMEOUT
        self._ws_timeout = 5
        self._socket_dir = None
        self.dbus_pid = 0
        self.dbus_env = {}
        self.dbus_control = False
        self.dbus_server = None
        self.unix_socket_paths = []
        self.touch_timer = None
        self.exec_cwd = os.getcwd()
        self.pidfile = None
        self.pidinode = 0

        self.session_name = ""

        #Features:
        self.mdns = False
        self.mdns_publishers = {}
        self.encryption = None
        self.encryption_keyfile = None
        self.tcp_encryption = None
        self.tcp_encryption_keyfile = None
        self.password_file = None
        self.compression_level = 1
        self.exit_with_client = False
        self.server_idle_timeout = 0
        self.server_idle_timer = None
        self.bandwidth_limit = 0

        self.init_thread = None
        self.init_thread_callbacks = []
        self.init_thread_lock = Lock()
        self.menu_provider = None

        self.init_uuid()
        sanity_checks()

    def get_server_mode(self):
        return "core"


    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()

    def init_when_ready(self, callbacks):
        log("init_when_ready(%s)", callbacks)
        self._when_ready = callbacks


    def init(self, opts):
        log("ServerCore.init(%s)", opts)
        self.session_name = bytestostr(opts.session_name)
        set_name("Xpra", self.session_name or "Xpra")

        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit)
        self.unix_socket_paths = []
        self._socket_dir = opts.socket_dir or ""
        if not self._socket_dir and opts.socket_dirs:
            self._socket_dir = opts.socket_dirs[0]
        self.encryption = opts.encryption
        self.encryption_keyfile = opts.encryption_keyfile
        self.tcp_encryption = opts.tcp_encryption
        self.tcp_encryption_keyfile = opts.tcp_encryption_keyfile
        if self.encryption or self.tcp_encryption:
            from xpra.net.crypto import crypto_backend_init  #pylint: disable=import-outside-toplevel
            crypto_backend_init()
        self.password_file = opts.password_file
        self.compression_level = opts.compression_level
        self.exit_with_client = opts.exit_with_client
        self.server_idle_timeout = opts.server_idle_timeout
        self.readonly = opts.readonly
        self.ssh_upgrade = opts.ssh_upgrade
        self.dbus_control = opts.dbus_control
        self.pidfile = opts.pidfile
        self.mdns = opts.mdns
        if opts.start_new_commands:
            #must be initialized before calling init_html_proxy
            self.menu_provider = get_menu_provider()
        self.init_html_proxy(opts)
        self.init_auth(opts)
        self.init_ssl(opts)
        if self.pidfile:
            self.pidinode = write_pidfile(self.pidfile)
        self.dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs+opts.client_socket_dirs)


    def init_ssl(self, opts):
        self.ssl_mode = opts.ssl
        from xpra.net.socket_util import get_ssl_attributes
        self._ssl_attributes = get_ssl_attributes(opts, True)
        netlog("init_ssl(..) ssl attributes=%s", self._ssl_attributes)

    def validate(self):
        return True

    def server_ready(self):
        return True

    def server_init(self):
        if self.mdns:
            add_work_item(self.mdns_publish)
        self.start_listen_sockets()

    def setup(self):
        self.init_packet_handlers()
        self.init_aliases()
        self.init_dbus_server()
        self.init_control_commands()
        #for things that can take longer:
        self.init_thread = Thread(target=self.threaded_init)
        self.init_thread.start()


    ######################################################################
    # run / stop:
    def signal_quit(self, signum, _frame=None):
        self.closing()
        self.install_signal_handlers(deadly_signal)
        self.idle_add(self.clean_quit)
        self.idle_add(sys.exit, 128+signum)

    def clean_quit(self, upgrading=False):
        log("clean_quit(%s)", upgrading)
        self._upgrading = upgrading
        self.closing()
        self.cleanup()
        w = get_worker()
        log("clean_quit: worker=%s", w)
        if w:
            stop_worker()
            try:
                w.join(0.05)
            except Exception:
                pass
            if w.is_alive():
                def quit_timer():
                    log("quit_timer() worker=%s", w)
                    if w and w.is_alive():
                        #wait up to 1 second for the worker thread to exit
                        try:
                            w.wait(1)
                        except Exception:
                            pass
                        if w.is_alive():
                            #still alive, force stop:
                            stop_worker(True)
                            try:
                                w.wait(1)
                            except Exception:
                                pass
                    self.quit(upgrading)
                self.timeout_add(250, quit_timer)
                log("clean_quit(..) quit timers scheduled, worker=%s", w)
            else:
                log("clean_quit(..) worker ended")
                w = None
        def force_quit():
            log("force_quit()")
            from xpra import os_util
            os_util.force_quit()
        self.timeout_add(5000, force_quit)
        log("clean_quit(..) quit timers scheduled")
        if not w:
            self.quit(upgrading)

    def quit(self, upgrading=False):
        log("quit(%s)", upgrading)
        self._upgrading = upgrading
        self.closing()
        noerr(sys.stdout.flush)
        self.do_quit()
        log("quit(%s) do_quit done!", upgrading)
        dump_all_frames()

    def closing(self):
        if not self._closing:
            self._closing = True
            self.log_closing_message()

    def log_closing_message(self):
        log.info("xpra %s server is %s", self.get_server_mode(), ["terminating", "exiting"][bool(self._upgrading)])

    def do_quit(self):
        raise NotImplementedError()

    def install_signal_handlers(self, callback):
        def os_signal(signum, _frame=None):
            callback(signum)
        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        register_SIGUSR_signals(self.idle_add)


    def threaded_init(self):
        log("threaded_init() servercore start")
        #platform specific init:
        threaded_server_init()
        #populate the platform info cache:
        get_platform_info()
        #run the init callbacks:
        with self.init_thread_lock:
            for cb in self.init_thread_callbacks:
                try:
                    cb()
                except Exception as e:
                    log("threaded_init()", exc_info=True)
                    log.error("Error in initialization thread callback %s", cb)
                    log.error(" %s", e)
        if self.menu_provider:
            self.menu_provider.setup()
        log("threaded_init() servercore end")

    def after_threaded_init(self, callback):
        with self.init_thread_lock:
            if self.init_thread is None or self.init_thread.is_alive():
                self.init_thread_callbacks.append(callback)
            else:
                callback()

    def wait_for_threaded_init(self):
        if not self.init_thread:
            #looks like we didn't make it as far as calling setup()
            log("wait_for_threaded_init() no init thread")
            return
        log("wait_for_threaded_init() %s.is_alive()=%s", self.init_thread, self.init_thread.is_alive())
        if self.init_thread.is_alive():
            log.info("waiting for initialization thread to complete")
            self.init_thread.join(INIT_THREAD_TIMEOUT)
            if self.init_thread.is_alive():
                log.warn("Warning: initialization thread is still active")


    def run(self):
        self.install_signal_handlers(self.signal_quit)
        def start_ready_callbacks():
            for x in self._when_ready:
                try:
                    x()
                except Exception as e:
                    log("start_ready_callbacks()", exc_info=True)
                    log.error("Error on server start ready callback '%s':", x)
                    log.error(" %s", e)
                    del e
        self.idle_add(start_ready_callbacks)
        self.idle_add(self.reset_server_timeout)
        self.idle_add(self.server_is_ready)
        self.idle_add(self.print_run_info)
        self.do_run()
        log("run()")
        return 0

    def server_is_ready(self):
        log.info("xpra is ready.")
        noerr(sys.stdout.flush)

    def do_run(self):
        raise NotImplementedError()

    def cleanup(self):
        netlog("cleanup() stopping %s tcp proxy clients: %s", len(self._tcp_proxy_clients), self._tcp_proxy_clients)
        for p in tuple(self._tcp_proxy_clients):
            p.quit()
        netlog("cleanup will disconnect: %s", self._potential_protocols)
        self.cancel_touch_timer()
        if self.mdns_publishers:
            add_work_item(self.mdns_cleanup)
        if self._upgrading:
            reason = SERVER_UPGRADE
        else:
            reason = SERVER_SHUTDOWN
        protocols = self.get_all_protocols()
        self.cleanup_protocols(protocols, reason)
        self.do_cleanup()
        self.cleanup_protocols(protocols, reason, True)
        self._potential_protocols = []
        self.cleanup_sockets()
        self.cleanup_dbus_server()
        if not self._upgrading:
            self.stop_dbus_server()
        if self.pidfile:
            self.pidinode = rm_pidfile(self.pidfile, self.pidinode)
        if self.menu_provider:
            self.menu_provider.cleanup()

    def do_cleanup(self):
        #allow just a bit of time for the protocol packet flush
        sleep(0.1)


    def cleanup_sockets(self):
        #stop listening for IO events:
        for sc in self.socket_cleanup:
            sc()
        #actually close the socket:
        si = self._socket_info
        self._socket_info = {}
        for socktype, _, info, cleanup in si:
            log("cleanup_sockets() calling %s for %s %s", cleanup, socktype, info)
            try:
                cleanup()
            except Exception:
                log("cleanup error on %s", cleanup, exc_info=True)


    ######################################################################
    # dbus:
    def init_dbus(self, dbus_pid, dbus_env):
        if not POSIX:
            return
        self.dbus_pid = dbus_pid
        self.dbus_env = dbus_env

    def stop_dbus_server(self):
        dbuslog("stop_dbus_server() dbus_pid=%s", self.dbus_pid)
        if not self.dbus_pid:
            return
        try:
            os.kill(self.dbus_pid, signal.SIGINT)
        except ProcessLookupError as e:
            dbuslog("os.kill(%i, SIGINT)", self.dbus_pid, exc_info=True)
            dbuslog.warn("Warning: dbus process not found (pid=%i)", self.dbus_pid)
        except Exception as e:
            dbuslog("os.kill(%i, SIGINT)", self.dbus_pid, exc_info=True)
            dbuslog.warn("Warning: error trying to stop dbus with pid %i:", self.dbus_pid)
            dbuslog.warn(" %s", e)

    def init_dbus_server(self):
        if not POSIX:
            return
        dbuslog("init_dbus_server() dbus_control=%s", self.dbus_control)
        dbuslog("init_dbus_server() env: %s", dict((k,v) for k,v in os.environ.items()
                                               if bytestostr(k).startswith("DBUS_")))
        if not self.dbus_control:
            return
        try:
            from xpra.server.dbus.dbus_common import dbus_exception_wrap
            self.dbus_server = dbus_exception_wrap(self.make_dbus_server, "setting up server dbus instance")
        except Exception as e:
            log("init_dbus_server()", exc_info=True)
            log.error("Error: cannot load dbus server:")
            log.error(" %s", e)
            self.dbus_server = None

    def cleanup_dbus_server(self):
        ds = self.dbus_server
        if ds:
            ds.cleanup()
            self.dbus_server = None

    def make_dbus_server(self):     #pylint: disable=useless-return
        dbuslog("make_dbus_server() no dbus server for %s", self)
        return None


    def init_uuid(self):
        # Define a server UUID if needed:
        self.uuid = os.environ.get("XPRA_PROXY_START_UUID") or self.get_uuid()
        if not self.uuid:
            self.uuid = bytestostr(get_hex_uuid())
            self.save_uuid()
        log("server uuid is %s", self.uuid)

    def get_uuid(self):
        return  None

    def save_uuid(self):
        pass


    def init_html_proxy(self, opts):
        httplog("init_html_proxy(..) options: tcp_proxy=%s, html='%s'", opts.tcp_proxy, opts.html)
        self._tcp_proxy = opts.tcp_proxy
        #opts.html can contain a boolean, "auto" or the path to the webroot
        www_dir = None
        if opts.html and os.path.isabs(opts.html):
            www_dir = opts.html
            self._html = True
        else:
            self._html = parse_bool("html", opts.html)
        if self._html is not False:     #True or None (for "auto")
            if not (opts.bind_tcp or opts.bind_ws or opts.bind_wss or opts.bind or opts.bind_ssl):
                #we need a socket!
                if self._html:
                    #html was enabled, so log an error:
                    httplog.error("Error: cannot use the html server without a socket")
                self._html = False
        httplog("init_html_proxy(..) html=%s", self._html)
        if self._html is not False:
            try:
                from xpra.net.websockets.handler import WebSocketRequestHandler
                assert WebSocketRequestHandler
                self._html = True
            except ImportError as e:
                httplog("importing WebSocketRequestHandler", exc_info=True)
                if self._html is None:  #auto mode
                    httplog.info("html server unavailable, cannot find websocket module")
                else:
                    httplog.error("Error: cannot import websocket connection handler:")
                    httplog.error(" %s", e)
                    httplog.error(" the html server will not be available")
                self._html = False
        #make sure we have the web root:
        from xpra.platform.paths import get_resources_dir
        if www_dir:
            self._www_dir = www_dir
        else:
            for ad,d in (
                (get_resources_dir(), "html5"),
                (get_resources_dir(), "www"),
                (get_app_dir(), "www"),
                ):
                self._www_dir = os.path.abspath(os.path.join(ad, d))
                if os.path.exists(self._www_dir):
                    httplog("found html5 client in '%s'", self._www_dir)
                    break
        if not os.path.exists(self._www_dir) and self._html:
            httplog.error("Error: cannot find the html web root")
            httplog.error(" '%s' does not exist", self._www_dir)
            httplog.error(" install the html-xpra package")
            self._html = False
        if self._html:
            httplog.info("serving html content from '%s'", self._www_dir)
            self._http_headers_dirs = []
            for d in get_system_conf_dirs():
                self._http_headers_dirs.append(os.path.join(d, "http-headers"))
            if not POSIX or getuid()>0:
                for d in get_user_conf_dirs():
                    self._http_headers_dirs.append(os.path.join(d, "http-headers"))
            self._http_headers_dirs.append(os.path.abspath(os.path.join(self._www_dir, "../http-headers")))
        if self._html and self._tcp_proxy:
            httplog.warn("Warning: the built in html server is enabled,")
            httplog.warn(" disabling the tcp-proxy option")
            self._tcp_proxy = False
        if opts.http_scripts.lower() not in FALSE_OPTIONS:
            script_options = {
                "/Status"           : self.http_status_request,
                "/Info"             : self.http_info_request,
                "/Sessions"         : self.http_sessions_request,
                "/Displays"         : self.http_displays_request,
                }
            if self.menu_provider:
                #we have menu data we can expose:
                script_options.update({
                "/Menu"             : self.http_menu_request,
                "/MenuIcon"         : self.http_menu_icon_request,
                "/DesktopMenu"      : self.http_desktop_menu_request,
                "/DesktopMenuIcon"  : self.http_desktop_menu_icon_request,
                })
            if opts.http_scripts.lower() in ("all", "*"):
                self._http_scripts = script_options
            else:
                for script in opts.http_scripts.split(","):
                    if not script.startswith("/"):
                        script = "/"+script
                    handler = script_options.get(script)
                    if not handler:
                        httplog.warn("Warning: unknown script '%s'", script)
                    else:
                        self._http_scripts[script] = handler
        httplog("http_scripts(%s)=%s", opts.http_scripts, self._http_scripts)


    ######################################################################
    # authentication:
    def init_auth(self, opts):
        auth = self.get_auth_modules("local-auth", opts.auth or [])
        if WIN32:
            self.auth_classes["named-pipe"] = auth
        else:
            self.auth_classes["unix-domain"] = auth
        for x in SOCKET_TYPES:
            opts_value = getattr(opts, "%s_auth" % x)
            self.auth_classes[x] = self.get_auth_modules(x, opts_value)
        authlog("init_auth(..) auth=%s", self.auth_classes)

    def get_auth_modules(self, socket_type, auth_strs):
        authlog("get_auth_modules(%s, %s, {..})", socket_type, auth_strs)
        if not auth_strs:
            return None
        return tuple(get_auth_module(auth_str) for auth_str in auth_strs)


    ######################################################################
    # control commands:
    def init_control_commands(self):
        from xpra.server.control_command import HelloCommand, HelpCommand, DebugControl
        self.control_commands = {"hello"    : HelloCommand(),
                                 "debug"    : DebugControl()}
        help_command = HelpCommand(self.control_commands)
        self.control_commands["help"] = help_command

    def handle_command_request(self, proto, *args):
        """ client sent a command request as part of the hello packet """
        assert args
        code, response = self.process_control_command(*args)
        hello = {"command_response"  : (code, response)}
        proto.send_now(("hello", hello))

    def process_control_command(self, *args):
        from xpra.server.control_command import ControlError
        assert args, "control command must have arguments"
        name = args[0]
        try:
            command = self.control_commands.get(name)
            commandlog("process_control_command control_commands[%s]=%s", name, command)
            if not command:
                commandlog.warn("invalid command: '%s' (must be one of: %s)", name, csv(self.control_commands))
                return 6, "invalid command"
            commandlog("process_control_command calling %s%s", command.run, args[1:])
            v = command.run(*args[1:])
            return 0, v
        except ControlError as e:
            commandlog.error("error %s processing control command '%s'", e.code, name)
            msgs = [" %s" % e]
            if e.help:
                msgs.append(" '%s': %s" % (name, e.help))
            for msg in msgs:
                commandlog.error(msg)
            return e.code, "\n".join(msgs)
        except Exception as e:
            commandlog.error("error processing control command '%s'", name, exc_info=True)
            return 127, "error processing control command: %s" % e


    def print_run_info(self):
        add_work_item(self.do_print_run_info)

    def do_print_run_info(self):
        log.info("xpra %s version %s %i-bit", self.get_server_mode(), full_version_str(), BITS)
        try:
            pinfo = get_platform_info()
            osinfo = " on %s" % platform_name(sys.platform, pinfo.get("linux_distribution") or pinfo.get("sysrelease", ""))
        except Exception:
            log("platform name error:", exc_info=True)
            osinfo = ""
        if POSIX:
            uid = os.getuid()
            gid = os.getgid()
            try:
                import pwd
                import grp #@UnresolvedImport
                user = pwd.getpwuid(uid)[0]
                group = grp.getgrgid(gid)[0]
                log.info(" uid=%i (%s), gid=%i (%s)", uid, user, gid, group)
            except:
                log.info(" uid=%i, gid=%i", uid, gid)
        log.info(" running with pid %s%s", os.getpid(), osinfo)
        self.idle_add(self.print_screen_info)

    def notify_new_user(self, ss):
        pass


    ######################################################################
    # screen / display:
    def get_display_bit_depth(self):
        return 0

    def print_screen_info(self):
        display = os.environ.get("DISPLAY")
        if display and display.startswith(":"):
            extra = ""
            bit_depth = self.get_display_bit_depth()
            if bit_depth:
                extra = " with %i bit colors" % bit_depth
            log.info(" connected to X11 display %s%s", display, extra)


    ######################################################################
    # sockets / connections / packets:
    def init_sockets(self, sockets):
        self._socket_info = sockets


    def mdns_publish(self):
        if not self.mdns:
            return
        #find all the records we want to publish:
        mdns_recs = {}
        for sock_def, options in self._socket_info.items():
            socktype, _, info, _ = sock_def
            socktypes = self.get_mdns_socktypes(socktype)
            mdns_option = options.get("mdns")
            if mdns_option:
                v = parse_bool("mdns", mdns_option, False)
                if not v:
                    mdnslog("mdns_publish() mdns(%s)=%s, skipped", info, mdns_option)
                    continue
            mdnslog("mdns_publish() info=%s, socktypes(%s)=%s", info, socktype, socktypes)
            for st in socktypes:
                recs = mdns_recs.setdefault(st, [])
                if socktype=="unix-domain":
                    assert st=="ssh"
                    host = "*"
                    iport = get_ssh_port()
                    if not iport:
                        continue
                else:
                    host, iport = info
                for h in hosts(host):
                    rec = (h, iport)
                    if rec not in recs:
                        recs.append(rec)
                mdnslog("mdns_publish() recs[%s]=%s", st, recs)
        mdns_info = self.get_mdns_info()
        self.mdns_publishers = {}
        for mdns_mode, listen_on in mdns_recs.items():
            info = dict(mdns_info)
            info["mode"] = mdns_mode
            aps = mdns_publish(self.display_name, listen_on, info)
            for ap in aps:
                ap.start()
                self.mdns_publishers[ap] = mdns_mode

    def get_mdns_socktypes(self, socktype):
        #for a given socket type,
        #what socket types we should expose via mdns
        if socktype in ("vsock", "named-pipe"):
            #cannot be accessed remotely
            return ()
        ssh_access = get_ssh_port()>0   #and opts.ssh.lower().strip() not in FALSE_OPTIONS
        ssl = bool(self._ssl_attributes)
        #only available with the RFBServer
        rfb_upgrades = getattr(self, "_rfb_upgrade", False)
        socktypes = [socktype]
        if socktype=="tcp":
            if ssl:
                socktypes.append("ssl")
            if self._html:
                socktypes.append("ws")
            if self._html and ssl:
                socktypes.append("wss")
            if self.ssh_upgrade:
                socktypes.append("ssh")
            if rfb_upgrades:
                socktypes.append("rfb")
        elif socktype=="ws":
            if ssl:
                socktypes.append("wss")
        elif socktype=="unix-domain":
            if ssh_access:
                socktypes = ["ssh"]
        return socktypes

    def get_mdns_info(self) -> dict:
        from xpra.platform.info import get_username
        mdns_info = {
            "display"  : self.display_name,
            "username" : get_username(),
            "uuid"     : self.uuid,
            "platform" : sys.platform,
            "type"     : self.session_type,
            }
        MDNS_EXPOSE_NAME = envbool("XPRA_MDNS_EXPOSE_NAME", True)
        if MDNS_EXPOSE_NAME and self.session_name:
            mdns_info["name"] = self.session_name
        return mdns_info

    def mdns_cleanup(self):
        mp = self.mdns_publishers
        self.mdns_publishers = {}
        for ap in tuple(mp.keys()):
            ap.stop()

    def mdns_update(self):
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


    def start_listen_sockets(self):
        ### All right, we're ready to accept customers:
        for sock_def, options in self._socket_info.items():
            socktype, sock, info, _ = sock_def
            netlog("init_sockets(%s) will add %s socket %s (%s)", self._socket_info, socktype, sock, info)
            self.socket_info[sock] = info
            self.socket_options[sock] = options
            self.idle_add(self.add_listen_socket, socktype, sock, options)
            if socktype=="unix-domain" and info:
                try:
                    p = os.path.abspath(info)
                    self.unix_socket_paths.append(p)
                    netlog("added unix socket path: %s", p)
                except Exception as e:
                    log.error("failed to set socket path to %s: %s", info, e)
                    del e
        if self.unix_socket_paths:
            self.touch_timer = self.timeout_add(60*1000, self.touch_sockets)


    def cancel_touch_timer(self):
        tt = self.touch_timer
        if tt:
            self.touch_timer = None
            self.source_remove(tt)

    def touch_sockets(self):
        netlog("touch_sockets() unix socket paths=%s", self.unix_socket_paths)
        for sockpath in self.unix_socket_paths:
            if not os.path.exists(sockpath):
                if first_time("missing-socket-%s" % sockpath):
                    log.warn("Warning: the unix domain socket cannot be found:")
                    log.warn(" '%s'", sockpath)
                    log.warn(" was it deleted by mistake?")
                continue
            try:
                os.utime(sockpath, None)
            except Exception:
                netlog("touch_sockets() error on %s", sockpath, exc_info=True)
        return True

    def init_packet_handlers(self):
        netlog("initializing packet handlers")
        self._default_packet_handlers = {
            "hello":                                self._process_hello,
            "disconnect":                           self._process_disconnect,
            Protocol.CONNECTION_LOST:               self._process_connection_lost,
            Protocol.GIBBERISH:                     self._process_gibberish,
            Protocol.INVALID:                       self._process_invalid,
            }

    def init_aliases(self):
        self.do_init_aliases(self._default_packet_handlers.keys())

    def do_init_aliases(self, packet_types):
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            i += 1

    def cleanup_all_protocols(self, reason):
        protocols = self.get_all_protocols()
        self.cleanup_protocols(protocols, reason)

    def get_all_protocols(self):
        return tuple(self._potential_protocols)

    def cleanup_protocols(self, protocols, reason, force=False):
        netlog("cleanup_protocols(%s, %s, %s)", protocols, reason, force)
        for protocol in protocols:
            if force:
                self.force_disconnect(protocol)
            else:
                self.disconnect_protocol(protocol, reason)

    def add_listen_socket(self, socktype, sock, options):
        info = self.socket_info.get(sock)
        netlog("add_listen_socket(%s, %s, %s) info=%s", socktype, sock, options, info)
        cleanup = add_listen_socket(socktype, sock, info, self._new_connection, options)
        if cleanup:
            self.socket_cleanup.append(cleanup)

    def _new_connection(self, socktype, listener, handle=0):
        """
            Accept the new connection,
            verify that there aren't too many,
            start a thread to dispatch it to the correct handler.
        """
        log("_new_connection%s", (listener, socktype, handle))
        if self._closing:
            netlog("ignoring new connection during shutdown")
            return False
        socket_info = self.socket_info.get(listener)
        assert socktype, "cannot find socket type for %s" % listener
        #TODO: just like add_listen_socket above, this needs refactoring
        socket_options = self.socket_options.get(listener, {})
        if socktype=="named-pipe":
            from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
            conn = NamedPipeConnection(listener.pipe_name, handle, socket_options)
            netlog.info("New %s connection received on %s", socktype, conn.target)
            return self.make_protocol(socktype, conn, socket_options)

        conn = accept_connection(socktype, listener, self._socket_timeout, socket_options)
        if conn is None:
            return True
        #limit number of concurrent network connections:
        if socktype not in ("unix-domain", ) and len(self._potential_protocols)>=self._max_connections:
            netlog.error("Error: too many connections (%i)", len(self._potential_protocols))
            netlog.error(" ignoring new one: %s", conn.endpoint)
            conn.close()
            return True
        #from here on, we run in a thread, so we can poll (peek does)
        start_thread(self.handle_new_connection, "new-%s-connection" % socktype, True,
                     args=(conn, socket_info, socket_options))
        return True

    def new_conn_err(self, conn, sock, socktype, socket_info, packet_type, msg=None):
        #not an xpra client
        netlog.error("Error: %s connection failed:", socktype)
        if conn.remote:
            netlog.error(" packet from %s", pretty_socket(conn.remote))
        if socket_info:
            netlog.error(" received on %s", pretty_socket(socket_info))
        if packet_type:
            netlog.error(" this packet looks like a '%s' packet", packet_type)
        else:
            netlog.error(" invalid packet format, not an xpra client?")
        packet_data = b"disconnect: connection setup failed"
        if msg:
            netlog.error(" %s", msg)
            packet_data += b", %s?" % strtobytes(msg)
        packet_data += b"\n"
        try:
            #default to plain text:
            sock.settimeout(1)
            if packet_type=="xpra":
                #try xpra packet format:
                from xpra.net.packet_encoding import pack_one_packet
                packet_data = pack_one_packet(["disconnect", "invalid protocol for this port"]) or packet_data
            elif packet_type=="http":
                #HTTP 400 error:
                packet_data = HTTP_UNSUPORTED
            conn.write(packet_data)
            self.timeout_add(500, self.force_close_connection, conn)
        except Exception as e:
            netlog("error sending %r: %s", packet_data, e)

    def force_close_connection(self, conn):
        try:
            conn.close()
        except OSError:
            log("close_connection()", exc_info=True)

    def handle_new_connection(self, conn, socket_info, socket_options):
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
        #peek so we can detect invalid clients early,
        #or handle non-xpra / wrapped traffic:
        timeout = PEEK_TIMEOUT_MS
        if socktype=="rfb":
            #rfb does not send any data, waits for a server packet
            #so don't bother waiting for something that should never come:
            timeout = 0
        elif socktype=="unix-domain":
            timeout = UNIXDOMAIN_PEEK_TIMEOUT_MS
        peek_data = peek_connection(conn, timeout)
        line1 = peek_data.split(b"\n")[0]
        netlog("socket peek=%s", ellipsizer(peek_data, limit=512))
        netlog("socket peek hex=%s", hexstr(peek_data[:128]))
        netlog("socket peek line1=%s", ellipsizer(line1))
        packet_type = guess_packet_type(peek_data)
        netlog("guess_packet_type(..)=%s", packet_type)

        def ssl_wrap():
            ssl_sock = self._ssl_wrap_socket(socktype, sock, socket_options)
            ssllog("ssl wrapped socket(%s)=%s", sock, ssl_sock)
            if ssl_sock is None:
                return None
            ssl_conn = SSLSocketConnection(ssl_sock, sockname, address, target, socktype)
            ssllog("ssl_wrap()=%s", ssl_conn)
            return ssl_conn

        if socktype in ("ssl", "wss"):
            #verify that this isn't plain HTTP / xpra:
            if packet_type not in ("ssl", None):
                self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                return
            #always start by wrapping with SSL:
            ssl_conn = ssl_wrap()
            if not ssl_conn:
                return
            if socktype=="wss":
                http = True
            else:
                assert socktype=="ssl"
                wss = socket_options.get("wss", None)
                if wss is not None:
                    if wss=="auto":
                        http = None
                    else:
                        http = wss.lower() in TRUE_OPTIONS
                    netlog("socket option wss=%s, http=%s", wss, http)
                else:
                    #no "wss" option, fallback to "ssl_mode" option:
                    if self.ssl_mode.lower()=="auto":
                        http = None
                    else:
                        http = self.ssl_mode.lower()=="wss"
                    netlog("ssl-mode=%s, http=%s", self.ssl_mode, http)
            if http is None:
                #look for HTTPS request to handle:
                if line1.find(b"HTTP/")>0 or peek_data.find(b"\x08http/")>0:
                    http = True
                else:
                    ssl_conn.enable_peek()
                    peek_data = peek_connection(ssl_conn)
                    line1 = peek_data.split(b"\n")[0]
                    http = line1.find(b"HTTP/")>0
                    netlog("looking for 'HTTP' in %r: %s", line1, http)
            if http:
                if not self._html:
                    self.new_conn_err(conn, sock, socktype, socket_info, packet_type,
                                      "the builtin http server is not enabled")
                    return
                self.start_http_socket(socktype, ssl_conn, socket_options, True, peek_data)
            else:
                ssl_conn._socket.settimeout(self._socket_timeout)
                log_new_connection(ssl_conn, socket_info)
                self.make_protocol(socktype, ssl_conn, socket_options)
            return

        if socktype=="ws":
            if peek_data:
                #honour socket option, fallback to "ssl_mode" attribute:
                wss = socket_options.get("wss", "").lower()
                if wss:
                    wss_upgrade = wss in TRUE_OPTIONS
                else:
                    wss_upgrade = self.ssl_mode.lower() in TRUE_OPTIONS or self.ssl_mode.lower() in ("auto", "wss")
                if wss_upgrade and packet_type=="ssl":
                    ssllog("ws socket receiving ssl, upgrading to wss")
                    conn = ssl_wrap()
                    if conn is None:
                        return
                elif packet_type not in (None, "http"):
                    self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                    return
            self.start_http_socket(socktype, conn, socket_options, False, peek_data)
            return

        if socktype=="rfb":
            if peek_data:
                self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
                return
            self.handle_rfb_connection(conn)
            return

        if socktype=="ssh":
            conn = self.handle_ssh_connection(conn, socket_options)
            if not conn:
                return
            peek_data, line1, packet_type = b"", b"", None

        if socktype in ("tcp", "unix-domain", "named-pipe") and peek_data:
            #see if the packet data is actually xpra or something else
            #that we need to handle via a tcp proxy, ssl wrapper or the websocket adapter:
            try:
                cont, conn, peek_data = self.may_wrap_socket(conn, socktype, socket_info, socket_options, peek_data)
                netlog("may_wrap_socket(..)=(%s, %s, %r)", cont, conn, peek_data)
                if not cont:
                    return
                packet_type = guess_packet_type(peek_data)
            except IOError as e:
                netlog("socket wrapping failed", exc_info=True)
                self.new_conn_err(conn, sock, socktype, socket_info, None, str(e))
                return

        if packet_type not in ("xpra", None):
            self.new_conn_err(conn, sock, socktype, socket_info, packet_type)
            return

        #get the new socket object as we may have wrapped it with ssl:
        sock = getattr(conn, "_socket", sock)
        pre_read = None
        if socktype=="unix-domain" and not peek_data:
            #try to read from this socket,
            #so short lived probes don't go through the whole protocol instantation
            try:
                sock.settimeout(0.001)
                data = conn.read(1)
                if not data:
                    netlog("%s connection already closed", socktype)
                    return
                pre_read = [data, ]
                netlog("pre_read data=%r", data)
            except Exception:
                netlog.error("Error reading from %s", conn, exc_info=True)
                return
        sock.settimeout(self._socket_timeout)
        log_new_connection(conn, socket_info)
        proto = self.make_protocol(socktype, conn, socket_options, pre_read=pre_read)
        if socktype=="tcp" and not peek_data and self._rfb_upgrade>0:
            t = self.timeout_add(self._rfb_upgrade*1000, self.try_upgrade_to_rfb, proto)
            self.socket_rfb_upgrade_timer[proto] = t

    def _ssl_wrap_socket(self, socktype, sock, socket_options):
        ssllog("ssl_wrap_socket(%s, %s, %s)", socktype, sock, socket_options)
        try:
            from xpra.net.socket_util import ssl_wrap_socket
            kwargs = self._ssl_attributes.copy()
            for k,v in socket_options.items():
                #options use '-' but attributes and parameters use '_':
                k = k.replace("-", "_")
                if k.startswith("ssl_"):
                    k = k[4:]
                    kwargs[k] = v
            ssl_sock = ssl_wrap_socket(sock, **kwargs)
            ssllog("_ssl_wrap_socket(%s, %s)=%s", sock, kwargs, ssl_sock)
            if ssl_sock is None:
                #None means EOF! (we don't want to import ssl bits here)
                ssllog("ignoring SSL EOF error")
            return ssl_sock
        except Exception as e:
            ssllog("SSL error", exc_info=True)
            ssl_paths = [socket_options.get(x, kwargs.get(x)) for x in ("ssl-cert", "ssl-key")]
            cpaths = csv("'%s'" % x for x in ssl_paths if x)
            log.error("Error: failed to create SSL socket")
            log.error(" from %s socket: %s", socktype, sock)
            if not cpaths:
                log.error(" no certificate paths specified")
            else:
                log.error(" check your certificate paths: %s", cpaths)
            log.error(" %s", e)
            return None


    def handle_ssh_connection(self, conn, socket_options):
        from xpra.server.ssh import make_ssh_server_connection, log as sshlog
        socktype = conn.socktype_wrapped
        none_auth = not self.auth_classes[socktype]
        sshlog("handle_ssh_connection(%s, %s) socktype wrapped=%s", conn, socket_options, socktype)
        def ssh_password_authenticate(username, password):
            if not POSIX or getuid()!=0:
                import getpass
                sysusername = getpass.getuser()
                if sysusername!=username:
                    sshlog.warn("Warning: ssh password authentication failed,")
                    sshlog.warn(" username does not match:")
                    sshlog.warn(" expected '%s', got '%s'", sysusername, username)
                    return False
            auth_modules = self.make_authenticators(socktype, username, conn)
            sshlog("ssh_password_authenticate auth_modules(%s, %s)=%s", username, "*"*len(password), auth_modules)
            for auth in auth_modules:
                #mimic a client challenge:
                digests = ["xor"]
                try:
                    salt, digest = auth.get_challenge(digests)
                    salt_digest = auth.choose_salt_digest(digests)
                    assert digest=="xor" and salt_digest=="xor"
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
        return make_ssh_server_connection(conn, socket_options, none_auth=none_auth, password_auth=ssh_password_authenticate)

    def try_upgrade_to_rfb(self, proto):
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto.is_closed():
            return False
        conn = proto._conn
        netlog("may_upgrade_to_rfb() input_bytecount=%i", conn.input_bytecount)
        if conn.input_bytecount==0:
            proto.steal_connection()
            self._potential_protocols.remove(proto)
            proto.wait_for_io_threads_exit(1)
            conn.set_active(True)
            self.handle_rfb_connection(conn)
        return False

    def cancel_upgrade_to_rfb_timer(self, protocol):
        t = self.socket_rfb_upgrade_timer.pop(protocol, None)
        if t:
            self.source_remove(t)


    def make_protocol(self, socktype, conn, socket_options, protocol_class=Protocol, pre_read=None):
        """ create a new xpra Protocol instance and start it """
        def xpra_protocol_class(conn):
            """ adds xpra protocol tweaks after creating the instance """
            protocol = protocol_class(self, conn, self.process_packet)
            protocol.large_packets.append(b"info-response")
            protocol.receive_aliases.update(self._aliases)
            return protocol
        return self.do_make_protocol(socktype, conn, socket_options, xpra_protocol_class, pre_read)

    def do_make_protocol(self, socktype, conn, socket_options, protocol_class, pre_read):
        """ create a new Protocol instance and start it """
        netlog("make_protocol(%s, %s, %s, %s)", socktype, conn, socket_options, protocol_class)
        socktype = socktype.lower()
        protocol = protocol_class(conn)
        protocol.pre_read = pre_read
        protocol.socket_type = socktype
        self._potential_protocols.append(protocol)
        protocol.authenticators = ()
        protocol.encryption = None
        protocol.keyfile = None
        protocol.keydata = None
        if socktype in ENCRYPTED_SOCKET_TYPES:
            #special case for legacy encryption code:
            protocol.encryption = socket_options.get("encryption", self.tcp_encryption)
            protocol.keyfile = socket_options.get("encryption-keyfile") or socket_options.get("keyfile") or self.tcp_encryption_keyfile
            protocol.keydata = parse_encoded_bin_data(socket_options.get("encryption-keydata") or socket_options.get("keydata"))
            netlog("%s: encryption=%s, keyfile=%s", socktype, protocol.encryption, protocol.keyfile)
            if protocol.encryption:
                from xpra.net.crypto import crypto_backend_init
                crypto_backend_init()
                from xpra.net.crypto import (
                    ENCRYPT_FIRST_PACKET,
                    DEFAULT_IV,
                    DEFAULT_SALT,
                    DEFAULT_ITERATIONS,
                    INITIAL_PADDING,
                    )
                if ENCRYPT_FIRST_PACKET:
                    authlog("encryption=%s, keyfile=%s", protocol.encryption, protocol.keyfile)
                    password = protocol.keydata or self.get_encryption_key(None, protocol.keyfile)
                    protocol.set_cipher_in(protocol.encryption,
                                           DEFAULT_IV, password,
                                           DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING)
        else:
            netlog("no encryption for %s", socktype)
        protocol.invalid_header = self.invalid_header
        authlog("socktype=%s, encryption=%s, keyfile=%s", socktype, protocol.encryption, protocol.keyfile)
        protocol.start()
        self.schedule_verify_connection_accepted(protocol, self._accept_timeout)
        return protocol

    def may_wrap_socket(self, conn, socktype, socket_info, socket_options, peek_data=b""):
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
        if packet_type=="xpra":
            netlog("may_wrap_socket: xpra protocol header '%s', not wrapping", peek_data[0])
            #xpra packet header, no need to wrap this connection
            return True, conn, peek_data
        frominfo = pretty_socket(conn.remote)
        netlog("may_wrap_socket(..) peek_data=%s from %s", ellipsizer(peek_data), frominfo)
        netlog("may_wrap_socket(..) packet_type=%s", packet_type)
        def conn_err(msg):
            self.new_conn_err(conn, conn._socket, socktype, socket_info, packet_type, msg)
            return False, None, None
        if packet_type=="ssh":
            ssh_upgrade = socket_options.get("ssh", self.ssh_upgrade) in TRUE_OPTIONS
            if not ssh_upgrade:
                conn_err("ssh upgrades are not enabled")
                return False, None, None
            conn = self.handle_ssh_connection(conn, socket_options)
            return conn is not None, conn, None
        if packet_type=="ssl":
            ssl_mode = socket_options.get("ssl", self.ssl_mode)
            if ssl_mode in FALSE_OPTIONS:
                conn_err("ssl upgrades are not enabled")
                return False, None, None
            sock, sockname, address, endpoint = conn._socket, conn.local, conn.remote, conn.endpoint
            sock = self._ssl_wrap_socket(socktype, sock, socket_options)
            if sock is None:
                return False, None, None
            conn = SSLSocketConnection(sock, sockname, address, endpoint, "ssl")
            conn.socktype_wrapped = socktype
            #we cannot peek on SSL sockets, just clear the unencrypted data:
            http = False
            if ssl_mode=="tcp":
                http = False
            elif ssl_mode=="www":
                http = True
            elif ssl_mode=="auto" or ssl_mode in TRUE_OPTIONS:
                http = False
                #use the header to guess:
                if line1.find(b"HTTP/")>0 or peek_data.find(b"\x08http/1.1")>0:
                    http = True
                else:
                    conn.enable_peek()
                    peek_data = peek_connection(conn)
                    line1 = peek_data.split(b"\n")[0]
                    http = line1.find(b"HTTP/")>0
            ssllog("may_wrap_socket SSL: %s, ssl mode=%s, http=%s", conn, ssl_mode, http)
            is_ssl = True
        else:
            http = line1.find(b"HTTP/")>0
            is_ssl = False
        if http:
            http_protocol = "https" if is_ssl else "http"
            http_upgrade = socket_options.get(http_protocol, self._html) not in FALSE_OPTIONS
            if not http_upgrade:
                conn_err("%s upgrades are not enabled" % http_protocol)
                return False, None, None
            self.start_http_socket(socktype, conn, socket_options, is_ssl, peek_data)
            return False, conn, None
        if self._tcp_proxy and not is_ssl:
            netlog.info("New tcp proxy connection received from %s", frominfo)
            t = start_thread(self.start_tcp_proxy, "tcp-proxy-for-%s" % frominfo, daemon=True, args=(conn, conn.remote))
            netlog("may_wrap_socket handling via tcp proxy thread %s", t)
            return False, conn, None
        return True, conn, peek_data

    def invalid_header(self, proto, data, msg=""):
        netlog("invalid header: input_packetcount=%s, tcp_proxy=%s, html=%s, ssl=%s",
               proto.input_packetcount, self._tcp_proxy, self._html, bool(self._ssl_attributes))
        proto._invalid_header(proto, data, msg)


    ######################################################################
    # http / websockets:
    def start_http_socket(self, socktype, conn, socket_options, is_ssl=False, peek_data=""):
        frominfo = pretty_socket(conn.remote)
        line1 = peek_data.split(b"\n")[0]
        http_proto = "http"+["","s"][int(is_ssl)]
        netlog("start_http_socket(%s, %s, %s, %s, ..) http proto=%s, line1=%r",
               socktype, conn, socket_options, is_ssl, http_proto, bytestostr(line1))
        if line1.startswith(b"GET ") or line1.startswith(b"POST "):
            parts = bytestostr(line1).split(" ")
            httplog("New %s %s request received from %s for '%s'", http_proto, parts[0], frominfo, parts[1])
            tname = "%s-request" % parts[0]
            req_info = "%s %s" % (http_proto, parts[0])
        else:
            httplog("New %s connection received from %s", http_proto, frominfo)
            req_info = "ws"+["","s"][int(is_ssl)]
            tname = "%s-proxy" % req_info
        #we start a new thread,
        #only so that the websocket handler thread is named correctly:
        start_thread(self.start_http, "%s-for-%s" % (tname, frominfo),
                     daemon=True, args=(socktype, conn, socket_options, is_ssl, req_info, line1, conn.remote))

    def start_http(self, socktype, conn, socket_options, is_ssl, req_info, line1, frominfo):
        httplog("start_http(%s, %s, %s, %s, %s, %r, %s) www dir=%s, headers dir=%s",
                socktype, conn, socket_options, is_ssl, req_info, line1, frominfo,
                self._www_dir, self._http_headers_dirs)
        try:
            from xpra.net.websockets.handler import WebSocketRequestHandler
            sock = conn._socket
            sock.settimeout(self._ws_timeout)
            def new_websocket_client(wsh):
                from xpra.net.websockets.protocol import WebSocketProtocol
                wslog("new_websocket_client(%s) socket=%s", wsh, sock)
                newsocktype = "ws%s" % ["","s"][int(is_ssl)]
                self.make_protocol(newsocktype, conn, socket_options, WebSocketProtocol)
            scripts = self.get_http_scripts()
            conn.socktype = "wss" if is_ssl else "ws"
            redirect_https = False
            if HTTP_HTTPS_REDIRECT and not req_info in ("ws", "wss"):
                redirect_https = not is_ssl and self.ssl_mode.lower() in TRUE_OPTIONS
            WebSocketRequestHandler(sock, frominfo, new_websocket_client,
                                    self._www_dir, self._http_headers_dirs, scripts,
                                    redirect_https)
            return
        except (IOError, ValueError) as e:
            httplog("start_http%s", (socktype, conn, is_ssl, req_info, frominfo), exc_info=True)
            err = e.args[0]
            if err==1 and line1 and line1[0]==0x16:
                l = httplog
            elif err in (errno.EPIPE, errno.ECONNRESET):
                l = httplog
            else:
                l = httplog.error
                l("Error: %s request failure", req_info)
                l(" errno=%s", err)
            l(" for client %s:", pretty_socket(frominfo))
            if line1 and line1[0]>=128 or line1[0]==0x16:
                l(" request as hex: '%s'", hexstr(line1))
            else:
                l(" request: %r", bytestostr(line1))
            l(" %s", e)
        except Exception as e:
            wslog.error("Error: %s request failure for client %s:", req_info, pretty_socket(frominfo), exc_info=True)
        try:
            conn.close()
        except Exception as ce:
            wslog("error closing connection following error: %s", ce)


    def get_http_scripts(self):
        return self._http_scripts

    def http_err(self, handler, code=500):  #pylint: disable=useless-return
        handler.send_response(code)
        return None

    def http_query_dict(self, path):
        return dict(parse_qsl(urlparse(path).query))

    def send_json_response(self, handler, data):
        import json  #pylint: disable=import-outside-toplevel
        return self.send_http_response(handler, json.dumps(data), "application/json")

    def send_icon(self, handler, icon_type, icon_data):
        httplog("send_icon%s", (handler, icon_type, ellipsizer(icon_data)))
        if not icon_data:
            icon_filename = get_icon_filename("noicon.png")
            icon_data = load_binary_file(icon_filename)
            icon_type = "png"
            httplog("using fallback transparent icon")
        mime_type = "application/octet-stream"
        if icon_type=="svg" and icon_data:
            from xpra.codecs.icon_util import svg_to_png  #pylint: disable=import-outside-toplevel
            icon_data = svg_to_png(None, icon_data, 48, 48)
        if icon_type in ("png", "jpeg", "svg", "webp"):
            mime_type = "image/%s" % icon_type
        return self.send_http_response(handler, icon_data, mime_type)

    def http_menu_request(self, handler):
        xdg_menu = self.menu_provider.get_menu_data(remove_icons=True)
        return self.send_json_response(handler, xdg_menu or "not available")

    def http_desktop_menu_request(self, handler):
        xsessions = self.menu_provider.get_desktop_sessions(remove_icons=True)
        return self.send_json_response(handler, xsessions or "not available")

    def http_menu_icon_request(self, handler):
        def invalid_path():
            httplog("invalid menu-icon request path '%s'", handler.path)
            return self.http_err(404)
        parts = unquote(handler.path).split("/MenuIcon/", 1)
        #ie: "/menu-icon/a/b" -> ['', 'a/b']
        if len(parts)<2:
            return invalid_path()
        path = parts[1].split("/")
        #ie: "a/b" -> ['a', 'b']
        category_name = path[0]
        if len(path)<2:
            #only the category is present
            app_name = None
        else:
            app_name = path[1]
        httplog("http_menu_icon_request: category_name=%s, app_name=%s", category_name, app_name)
        icon_type, icon_data = self.menu_provider.get_menu_icon(category_name, app_name)
        return self.send_icon(handler, icon_type, icon_data)

    def http_desktop_menu_icon_request(self, handler):
        def invalid_path():
            httplog("invalid menu-icon request path '%s'", handler.path)
            return self.http_err(handler, 404)
        parts = unquote(handler.path).split("/DesktopMenuIcon/", 1)
        #ie: "/menu-icon/wmname" -> ['', 'sessionname']
        if len(parts)<2:
            return invalid_path()
        #in case the sessionname is followed by a slash:
        sessionname = parts[1].split("/")[0]
        httplog("http_desktop_menu_icon_request: sessionname=%s", sessionname)
        icon_type, icon_data = self.menu_provider.get_desktop_menu_icon(sessionname)
        return self.send_icon(handler, icon_type, icon_data)

    def _filter_display_dict(self, display_dict, *whitelist):
        displays_info = {}
        for display, info in display_dict.items():
            displays_info[display] = dict((k,v) for k,v in info.items() if k in whitelist)
        httplog("_filter_display_dict(%s)=%s", display_dict, displays_info)
        return displays_info

    def http_displays_request(self, handler):
        displays = self.get_displays()
        displays_info = self._filter_display_dict(displays, "state", "wmname", "xpra-server-mode")
        return self.send_json_response(handler, displays_info)

    def get_displays(self):
        from xpra.scripts.main import get_displays_info #pylint: disable=import-outside-toplevel
        return get_displays_info(self.dotxpra)

    def http_sessions_request(self, handler):
        sessions = self.get_xpra_sessions()
        sessions_info = self._filter_display_dict(sessions, "state", "username", "session-type", "session-name", "uuid")
        return self.send_json_response(handler, sessions_info)

    def get_xpra_sessions(self):
        from xpra.scripts.main import get_xpra_sessions #pylint: disable=import-outside-toplevel
        return get_xpra_sessions(self.dotxpra)

    def http_info_request(self, handler):
        return self.send_json_response(handler, self.get_http_info())

    def get_http_info(self) -> dict:
        return {
            "mode"              : self.get_server_mode(),
            "type"              : "Python",
            "uuid"              : self.uuid,
            }

    def http_status_request(self, handler):
        return self.send_http_response(handler, "ready")

    def send_http_response(self, handler, content, content_type="text/plain"):
        handler.send_response(200)
        headers = {
            "Content-type"      : content_type,
            "Content-Length"    : len(content),
            }
        for k,v in headers.items():
            handler.send_header(k, v)
        handler.end_headers()
        if isinstance(content, str):
            content = content.encode("latin1")
        return content


    def start_tcp_proxy(self, conn, frominfo):
        proxylog("start_tcp_proxy(%s, %s)", conn, frominfo)
        #connect to web server:
        try:
            host, port = self._tcp_proxy.split(":", 1)
            port = int(port)
        except ValueError as e:
            proxylog.error("Error: invalid tcp proxy value '%s'", self._tcp_proxy)
            proxylog.error(" %s", e)
            conn.close()
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((host, int(port)))
            sock.settimeout(None)
            tcp_server_connection = SocketConnection(sock, sock.getsockname(), sock.getpeername(),
                                                     "tcp-proxy-for-%s" % frominfo, "tcp")
        except Exception as e:
            proxylog("start_tcp_proxy(%s, %s)", conn, frominfo, exc_info=True)
            proxylog.error("Error: failed to connect to TCP proxy endpoint: %s:%s", host, port)
            proxylog.error(" %s", e)
            conn.close()
            return
        proxylog("proxy connected to tcp server at %s:%s : %s", host, port, tcp_server_connection)
        sock.settimeout(self._socket_timeout)

        #we can use blocking sockets for the client:
        conn.settimeout(None)
        #but not for the server, which could deadlock on exit:
        sock.settimeout(1)

        #now start forwarding:
        from xpra.scripts.fdproxy import XpraProxy  #pylint: disable=import-outside-toplevel
        p = XpraProxy(frominfo, conn, tcp_server_connection, self.tcp_proxy_quit)
        self._tcp_proxy_clients.append(p)
        proxylog.info("client connection from %s forwarded to proxy server on %s:%s", frominfo, host, port)
        p.start_threads()


    def tcp_proxy_quit(self, proxy):
        proxylog("tcp_proxy_quit(%s)", proxy)
        if proxy in self._tcp_proxy_clients:
            self._tcp_proxy_clients.remove(proxy)

    def is_timedout(self, protocol):
        #subclasses may override this method (ServerBase does)
        v = not protocol.is_closed() and protocol in self._potential_protocols and \
            protocol not in self._tcp_proxy_clients
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def schedule_verify_connection_accepted(self, protocol, timeout=60):
        t = self.timeout_add(timeout*1000, self.verify_connection_accepted, protocol)
        self.socket_verify_timer[protocol] = t

    def verify_connection_accepted(self, protocol):
        self.cancel_verify_connection_accepted(protocol)
        if self.is_timedout(protocol):
            conn = getattr(protocol, "_conn", None)
            log.error("Error: connection timed out: %s", conn or protocol)
            elapsed = monotonic_time()-protocol.start_time
            log.error(" after %i seconds", elapsed)
            if conn:
                log.error(" received %i bytes", conn.input_bytecount)
                if conn.input_bytecount==0:
                    try:
                        data = conn.peek(200)
                    except Exception:
                        data = b""
                    if data:
                        log.error(" read buffer=%r", data)
                        packet_type = guess_packet_type(data)
                        if packet_type:
                            log.error(" looks like '%s' ", packet_type)
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def cancel_verify_connection_accepted(self, protocol):
        t = self.socket_verify_timer.pop(protocol, None)
        if t:
            self.source_remove(t)

    def send_disconnect(self, proto, *reasons):
        netlog("send_disconnect(%s, %s)", proto, reasons)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto.is_closed():
            return
        proto.send_disconnect(reasons)
        self.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto):
        netlog("force_disconnect(%s)", proto)
        self.cleanup_protocol(proto)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        proto.close()

    def disconnect_client(self, protocol, reason, *extra):
        netlog("disconnect_client(%s, %s, %s)", protocol, reason, extra)
        if protocol and not protocol.is_closed():
            self.disconnect_protocol(protocol, reason, *extra)

    def disconnect_protocol(self, protocol, *reasons):
        netlog("disconnect_protocol(%s, %s)", protocol, reasons)
        i = str(reasons[0])
        if len(reasons)>1:
            i += " (%s)" % csv(reasons[1:])
        proto_info = " %s" % protocol
        try:
            conn = protocol._conn
            info = conn.get_info()
            endpoint = info.get("endpoint")
            if endpoint:
                proto_info = " %s" % pretty_socket(endpoint)
            else:
                proto_info = " %s" % pretty_socket(conn.local)
        except (KeyError, AttributeError):
            pass
        self._log_disconnect(protocol, "Disconnecting client%s:", proto_info)
        self._log_disconnect(protocol, " %s", i)
        self.cancel_verify_connection_accepted(protocol)
        self.cancel_upgrade_to_rfb_timer(protocol)
        protocol.send_disconnect(reasons)
        self.cleanup_protocol(protocol)

    def cleanup_protocol(self, proto):
        pass

    def _process_disconnect(self, proto, packet):
        info = bytestostr(packet[1])
        if len(packet)>2:
            info += " (%s)" % csv(bytestostr(x) for x in packet[2:])
        #only log protocol info if there is more than one client:
        proto_info = self._disconnect_proto_info(proto)
        self._log_disconnect(proto, "client%s has requested disconnection: %s", proto_info, info)
        self.disconnect_protocol(proto, CLIENT_REQUEST)

    def _log_disconnect(self, _proto, *args):
        netlog.info(*args)

    def _disconnect_proto_info(self, _proto):
        #overriden in server_base in case there is more than one protocol
        return ""

    def _process_connection_lost(self, proto, packet):
        netlog("process_connection_lost(%s, %s)", proto, packet)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto in self._potential_protocols:
            if not proto.is_closed():
                self._log_disconnect(proto, "Connection lost")
            self._potential_protocols.remove(proto)
        self.cleanup_protocol(proto)

    def _process_gibberish(self, proto, packet):
        message, data = packet[1:3]
        netlog("Received uninterpretable nonsense from %s: %s", proto, message)
        netlog(" data: %s", ellipsizer(data))
        self.disconnect_client(proto, message)

    def _process_invalid(self, protocol, packet):
        message, data = packet[1:3]
        netlog("Received invalid packet: %s", message)
        netlog(" data: %s", ellipsizer(data))
        self.disconnect_client(protocol, message)


    ######################################################################
    # hello / authentication:
    def send_version_info(self, proto, full=False):
        version = XPRA_VERSION
        if full:
            version = full_version_str()
        proto.send_now(("hello", {"version" : version}))
        #client is meant to close the connection itself, but just in case:
        self.timeout_add(5*1000, self.send_disconnect, proto, DONE, "version sent")

    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        c = typedict(capabilities)
        proto.set_compression_level(c.intget("compression_level", self.compression_level))
        proto.enable_compressor_from_caps(c)
        if not proto.enable_encoder_from_caps(c):
            #this should never happen:
            #if we got here, we parsed a packet from the client!
            #(maybe the client used an encoding it claims not to support?)
            self.disconnect_client(proto, PROTOCOL_ERROR, "failed to negotiate a packet encoder")
            return

        log("process_hello: capabilities=%s", capabilities)
        if c.boolget("version_request"):
            self.send_version_info(proto, c.boolget("full-version-request"))
            return
        #verify version:
        remote_version = c.strget("version")
        verr = version_compat_check(remote_version)
        if verr is not None:
            self.disconnect_client(proto, VERSION_ERROR, "incompatible version: %s" % verr)
            proto.close()
            return
        #this will call auth_verified if successful
        #it may also just send challenge packets,
        #in which case we'll end up here parsing the hello again
        start_thread(self.verify_auth, "authenticate connection", daemon=True, args=(proto, packet, c))

    def make_authenticators(self, socktype, username, conn):
        authlog("make_authenticators%s socket options=%s", (socktype, username, conn), conn.options)
        sock_auth = conn.options.get("auth", "")
        if sock_auth:
            #per socket authentication option:
            #ie: --bind-tcp=0.0.0.0:10000,auth=hosts,auth=file:filename=pass.txt:foo=bar
            # -> sock_auth = ["hosts", "file:filename=pass.txt:foo=bar"]
            if not isinstance(sock_auth, list):
                sock_auth = sock_auth.split(",")
            auth_classes = self.get_auth_modules(conn.socktype, sock_auth)
        else:
            #use authentication configuration defined for all sockets of this type:
            auth_classes = self.auth_classes[socktype]
        i = 0
        authenticators = []
        if auth_classes:
            authlog("creating authenticators %s for %s, with username=%s, connection=%s",
                    csv(auth_classes), socktype, username, conn)
            for auth, _, aclass, options in auth_classes:
                opts = dict(options)
                opts["connection"] = conn
                try:
                    for o in ("self", "username"):
                        if o in opts:
                            raise Exception("illegal authentication module options '%s'" % o)
                    authenticator = aclass(username, **opts)
                except Exception:
                    authlog("%s%s", aclass, (username, opts), exc_info=True)
                    raise
                authlog("authenticator %i: %s(%s, %s)=%s", i, auth, username, opts, authenticator)
                authenticators.append(authenticator)
                i += 1
        return tuple(authenticators)

    def send_challenge(self, proto, salt, auth_caps, digest, salt_digest, prompt="password"):
        proto.send_now(("challenge", salt, auth_caps or "", digest, salt_digest, prompt))
        self.schedule_verify_connection_accepted(proto, CHALLENGE_TIMEOUT)

    def verify_auth(self, proto, packet, c):
        def auth_failed(msg):
            authlog.warn("Warning: authentication failed")
            authlog.warn(" %s", msg)
            self.timeout_add(1000, self.disconnect_client, proto, msg)

        username = c.strget("username")
        if not username:
            import getpass
            username = getpass.getuser()
        conn = proto._conn
        #authenticator:
        if not proto.authenticators:
            socktype = conn.socktype_wrapped
            try:
                proto.authenticators = self.make_authenticators(socktype, username, conn)
            except Exception as e:
                authlog("instantiating authenticator for %s", socktype, exc_info=True)
                authlog.error("Error instantiating authenticator for %s:", proto.socket_type)
                authlog.error(" %s", e)
                auth_failed(str(e))
                return

        digest_modes = c.strtupleget("digest", ("hmac", ))
        salt_digest_modes = c.strtupleget("salt-digest", ("xor",))
        #client may have requested encryption:
        cipher = c.strget("cipher")
        cipher_iv = c.strget("cipher.iv")
        key_salt = c.strget("cipher.key_salt")
        auth_caps = {}
        if cipher and cipher_iv:
            from xpra.net.crypto import DEFAULT_PADDING, ALL_PADDING_OPTIONS, ENCRYPTION_CIPHERS, new_cipher_caps
            iterations = c.intget("cipher.key_stretch_iterations")
            padding = c.strget("cipher.padding", DEFAULT_PADDING)
            padding_options = c.strtupleget("cipher.padding.options", (DEFAULT_PADDING,))
            if cipher not in ENCRYPTION_CIPHERS:
                authlog.warn("Warning: unsupported cipher: %s", cipher)
                if ENCRYPTION_CIPHERS:
                    authlog.warn(" should be: %s", csv(ENCRYPTION_CIPHERS))
                auth_failed("unsupported cipher")
                return
            encryption_key = proto.keydata or self.get_encryption_key(proto.authenticators, proto.keyfile)
            if encryption_key is None:
                auth_failed("encryption key is missing")
                return
            if padding not in ALL_PADDING_OPTIONS:
                auth_failed("unsupported padding: %s" % padding)
                return
            authlog("set output cipher using encryption key '%s'", ellipsizer(encryption_key))
            proto.set_cipher_out(cipher, cipher_iv, encryption_key, key_salt, iterations, padding)
            #use the same cipher as used by the client:
            auth_caps = new_cipher_caps(proto, cipher, encryption_key, padding_options)
            authlog("server cipher=%s", auth_caps)
        else:
            if proto.encryption and conn.socktype in ENCRYPTED_SOCKET_TYPES:
                authlog("client does not provide encryption tokens")
                auth_failed("missing encryption tokens")
                return
            auth_caps = None

        def send_fake_challenge():
            #fake challenge so the client will send the real hello:
            salt = get_salt()
            digest = choose_digest(digest_modes)
            salt_digest = choose_digest(salt_digest_modes)
            self.send_challenge(proto, salt, auth_caps, digest, salt_digest)

        #skip the authentication module we have "passed" already:
        remaining_authenticators = tuple(x for x in proto.authenticators if not x.passed)

        client_expects_challenge = c.strget("challenge") is not None
        if client_expects_challenge and not remaining_authenticators:
            authlog.warn("Warning: client expects an authentication challenge,")
            authlog.warn(" sending a fake one")
            send_fake_challenge()
            return

        authlog("processing authentication with %s, remaining=%s, digest_modes=%s, salt_digest_modes=%s",
                proto.authenticators, remaining_authenticators, digest_modes, salt_digest_modes)
        #verify each remaining authenticator:
        for index, authenticator in enumerate(proto.authenticators):
            if authenticator not in remaining_authenticators:
                authlog("authenticator[%i]=%s (already passed)", index, authenticator)
                continue
            req = authenticator.requires_challenge()
            authlog("authenticator[%i]=%s, requires-challenge=%s, challenge-sent=%s",
                    index, authenticator, req, authenticator.challenge_sent)
            if not req:
                #this authentication module does not need a challenge
                #(ie: "peercred" or "none")
                if not authenticator.authenticate(c):
                    auth_failed("%s authentication failed" % authenticator)
                    return
                authenticator.passed = True
                authlog("authentication passed for %s (no challenge provided)", authenticator)
                continue
            if not authenticator.challenge_sent:
                #we'll re-schedule this when we call send_challenge()
                #as the authentication module is free to take its time
                self.cancel_verify_connection_accepted(proto)
                #note: we may have received a challenge_response from a previous auth module's challenge
                challenge = authenticator.get_challenge(digest_modes)
                if challenge is None:
                    if authenticator.requires_challenge():
                        auth_failed("invalid state, unexpected challenge response")
                        return
                    authlog.warn("Warning: authentication module '%s' does not require any credentials", authenticator)
                    authlog.warn(" but the client %s supplied them", proto)
                    #fake challenge so the client will send the real hello:
                    send_fake_challenge()
                    return
                salt, digest = challenge
                actual_digest = digest.split(":", 1)[0]
                authlog("get_challenge(%s)= %s, %s", digest_modes, hexstr(salt), digest)
                authlog.info("Authentication required by %s authenticator module %i", authenticator, (index+1))
                authlog.info(" sending challenge for username '%s' using %s digest", username, actual_digest)
                if actual_digest not in digest_modes:
                    auth_failed("cannot proceed without %s digest support" % actual_digest)
                    return
                salt_digest = authenticator.choose_salt_digest(salt_digest_modes)
                if salt_digest in ("xor", "des"):
                    if not LEGACY_SALT_DIGEST:
                        auth_failed("insecure salt digest '%s' rejected" % salt_digest)
                        return
                    log.warn("Warning: using legacy support for '%s' salt digest", salt_digest)
                self.send_challenge(proto, salt, auth_caps, digest, salt_digest, authenticator.prompt)
                return
            if not authenticator.authenticate(c):
                auth_failed("authentication failed")
                return
        authlog("all authentication modules passed")
        self.auth_verified(proto, packet, auth_caps)

    def auth_verified(self, proto, packet, auth_caps):
        capabilities = packet[1]
        c = typedict(capabilities)
        command_req = c.strtupleget("command_request")
        if command_req:
            #call from UI thread:
            authlog("auth_verified(..) command request=%s", command_req)
            self.idle_add(self.handle_command_request, proto, *command_req)
            return
        #continue processing hello packet in UI thread:
        self.idle_add(self.call_hello_oked, proto, packet, c, auth_caps)


    def get_encryption_key(self, authenticators=None, keyfile=None):
        #if we have a keyfile specified, use that:
        authlog("get_encryption_key(%s, %s)", authenticators, keyfile)
        if keyfile:
            authlog("loading encryption key from keyfile: %s", keyfile)
            v = filedata_nocrlf(keyfile)
            if v:
                return v
        v = os.environ.get('XPRA_ENCRYPTION_KEY')
        if v:
            authlog("using encryption key from %s environment variable", 'XPRA_ENCRYPTION_KEY')
            return v
        if authenticators:
            for authenticator in authenticators:
                v = authenticator.get_password()
                if v:
                    authlog("using password from authenticator %s", authenticator)
                    return v
        return None

    def call_hello_oked(self, proto, packet, c, auth_caps):
        try:
            if SIMULATE_SERVER_HELLO_ERROR:
                raise Exception("Simulating a server error")
            self.hello_oked(proto, packet, c, auth_caps)
        except ClientException as e:
            log("call_hello_oked(%s, %s, %s, %s)", proto, packet, ellipsizer(c), auth_caps, exc_info=True)
            log.error("Error setting up new connection for")
            log.error(" %s:", proto)
            log.error(" %s", e)
            self.disconnect_client(proto, SERVER_ERROR, str(e))
        except Exception as e:
            #log exception but don't disclose internal details to the client
            log.error("server error processing new connection from %s: %s", proto, e, exc_info=True)
            self.disconnect_client(proto, SERVER_ERROR, "error accepting new connection")

    def hello_oked(self, proto, _packet, c, _auth_caps):
        proto.accept()
        generic_request = c.strget("request")
        def is_req(mode):
            return generic_request==mode or c.boolget("%s_request" % mode)
        if is_req("connect_test"):
            ctr = c.strget("connect_test_request")
            response = {"connect_test_response" : ctr}
            proto.send_now(("hello", response))
            return True
        if is_req("id"):
            self.send_id_info(proto)
            return True
        if is_req("info"):
            self.send_hello_info(proto)
            return True
        if self._closing:
            self.disconnect_client(proto, SERVER_EXIT, "server is shutting down")
            return True
        return False


    def accept_client(self, proto, c):
        #max packet size from client (the biggest we can get are clipboard packets)
        netlog("accept_client(%s, %s)", proto, c)
        #note: when uploading files, we send them in chunks smaller than this size
        proto.max_packet_size = MAX_PACKET_SIZE
        proto.parse_remote_caps(c)
        self.accept_protocol(proto)

    def accept_protocol(self, proto):
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        self.reset_server_timeout(False)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)

    def reset_server_timeout(self, reschedule=True):
        timeoutlog("reset_server_timeout(%s) server_idle_timeout=%s, server_idle_timer=%s",
                   reschedule, self.server_idle_timeout, self.server_idle_timer)
        if self.server_idle_timeout<=0:
            return
        if self.server_idle_timer:
            self.source_remove(self.server_idle_timer)
            self.server_idle_timer = None
        if reschedule:
            self.server_idle_timer = self.timeout_add(self.server_idle_timeout*1000, self.server_idle_timedout)

    def server_idle_timedout(self):
        timeoutlog.info("No valid client connections for %s seconds, exiting the server", self.server_idle_timeout)
        self.clean_quit(False)


    def make_hello(self, source=None):
        now = time()
        capabilities = flatten_dict(get_network_caps())
        if source is None or source.wants_versions:
            capabilities.update(flatten_dict(get_server_info()))
        capabilities.update({
                        "version"               : XPRA_VERSION,
                        "start_time"            : int(self.start_time),
                        "current_time"          : int(now),
                        "elapsed_time"          : int(now - self.start_time),
                        "server_type"           : "core",
                        "server.mode"           : self.get_server_mode(),
                        "hostname"              : socket.gethostname(),
                        })
        if source is None or source.wants_features:
            capabilities.update({
                "readonly-server"   : True,
                "readonly"          : self.readonly,
                "server-log"        : os.environ.get("XPRA_SERVER_LOG", ""),
                })
        if source is None or source.wants_versions:
            capabilities["uuid"] = get_user_uuid()
            mid = get_machine_id()
            if mid:
                capabilities["machine_id"] = mid
        if self.session_name:
            capabilities["session_name"] = self.session_name.encode("utf-8")
        return capabilities


    ######################################################################
    # info:
    def send_id_info(self, proto):
        log("id info request from %s", proto._conn)
        proto.send_now(("hello", self.get_session_id_info()))

    def get_session_id_info(self) -> dict:
        #minimal information for identifying the session
        id_info = {
            "session-type"  : self.session_type,
            "session-name"  : self.session_name,
            "uuid"          : self.uuid,
            "platform"      : sys.platform,
            "pid"           : os.getpid(),
            "machine-id"    : get_machine_id(),
            }
        display = os.environ.get("DISPLAY")
        if display:
            id_info["display"] = display
        return id_info

    def send_hello_info(self, proto):
        #Note: this can be overriden in subclasses to pass arguments to get_ui_info()
        #(ie: see server_base)
        log.info("processing info request from %s", proto._conn)
        def cb(proto, info):
            self.do_send_info(proto, info)
        self.get_all_info(cb, proto)

    def do_send_info(self, proto, info):
        proto.send_now(("hello", notypedict(info)))

    def get_all_info(self, callback, proto=None, *args):
        start = monotonic_time()
        ui_info = self.get_ui_info(proto, *args)
        end = monotonic_time()
        log("get_all_info: ui info collected in %ims", (end-start)*1000)
        start_thread(self._get_info_in_thread, "Info", daemon=True, args=(callback, ui_info, proto, args))

    def _get_info_in_thread(self, callback, ui_info, proto, args):
        log("get_info_in_thread%s", (callback, {}, proto, args))
        start = monotonic_time()
        #this runs in a non-UI thread
        try:
            info = self.get_info(proto, *args)
            merge_dicts(ui_info, info)
        except Exception:
            log.error("Error during info collection using %s", self.get_info, exc_info=True)
        end = monotonic_time()
        log("get_all_info: non ui info collected in %ims", (end-start)*1000)
        callback(proto, ui_info)

    def get_ui_info(self, _proto, *_args) -> dict:
        #this function is for info which MUST be collected from the UI thread
        return {}

    def get_thread_info(self, proto) -> dict:
        return get_thread_info(proto)

    def get_minimal_server_info(self) -> dict:
        now = time()
        info = {
            "mode"              : self.get_server_mode(),
            "session-type"      : self.session_type,
            "type"              : "Python",
            "python"            : {"version" : platform.python_version()},
            "start_time"        : int(self.start_time),
            "current_time"      : int(now),
            "elapsed_time"      : int(now - self.start_time),
            "uuid"              : self.uuid,
            "machine-id"        : get_machine_id(),
            }
        return info

    def get_server_info(self) -> dict:
        #this function is for non UI thread info
        si = {}
        si.update(self.get_minimal_server_info())
        si.update(get_server_info())
        si.update({
            "argv"              : sys.argv,
            "path"              : sys.path,
            "exec_prefix"       : sys.exec_prefix,
            "executable"        : sys.executable,
            "idle-timeout"      : int(self.server_idle_timeout),
            })
        if self.pidfile:
            si["pidfile"] = {
                "path"  : self.pidfile,
                "inode" : self.pidinode,
                }
        logfile = os.environ.get("XPRA_SERVER_LOG")
        if logfile:
            si["log-file"] = logfile
        if POSIX:
            try:
                si["load"] = tuple(int(x*1000) for x in os.getloadavg())
            except OSError:
                log("cannot get load average", exc_info=True)
        if self.original_desktop_display:
            si["original-desktop-display"] = self.original_desktop_display
        return si

    def get_info(self, proto, *_args):
        start = monotonic_time()
        #this function is for non UI thread info
        info = {}
        def up(prefix, d):
            info[prefix] = d

        si = self.get_server_info()
        if SYSCONFIG:
            si["sysconfig"] = get_sysconfig_info()
        up("server", si)

        ni = get_net_info()
        ni.update({
                   "sockets"        : self.get_socket_info(),
                   "encryption"     : self.encryption or "",
                   "tcp-encryption" : self.tcp_encryption or "",
                   "bandwidth-limit": self.bandwidth_limit or 0,
                   "packet-handlers" : self.get_packet_handlers_info(),
                   "www"    : {
                       ""                   : self._html,
                       "dir"                : self._www_dir or "",
                       "http-headers-dirs"   : self._http_headers_dirs or "",
                       },
                   "mdns"           : self.mdns,
                   })
        up("network", ni)
        up("threads",   self.get_thread_info(proto))
        from xpra.platform.info import get_sys_info
        up("sys", get_sys_info())
        up("env", get_info_env())
        if self.session_name:
            info["session"] = {"name" : self.session_name}
        if self.child_reaper:
            info.update(self.child_reaper.get_info())
        if self.dbus_pid:
            up("dbus", {
                "pid"   : self.dbus_pid,
                "env"   : self.dbus_env,
                })
        end = monotonic_time()
        log("ServerCore.get_info took %ims", (end-start)*1000)
        return info

    def get_packet_handlers_info(self) -> dict:
        return {
            "default"   : sorted(self._default_packet_handlers.keys()),
            }

    def get_socket_info(self) -> dict:
        si = {}
        def add_listener(socktype, info):
            si.setdefault(socktype, {}).setdefault("listeners", []).append(info)
        def add_address(socktype, address, port):
            addresses = si.setdefault(socktype, {}).setdefault("addresses", [])
            if (address, port) not in addresses:
                addresses.append((address, port))
            if socktype=="tcp":
                if self._html:
                    add_address("ws", address, port)
                if self._ssl_attributes:
                    add_address("ssl", address, port)
                if self.ssh_upgrade:
                    add_address("ssh", address, port)
            if socktype=="ws":
                if self._ssl_attributes:
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
                #we expose addresses only for TCP sockets
                continue
            upnp_address = options.get("upnp-address")
            if upnp_address:
                add_address(socktype, *upnp_address)
            if len(info)!=2 or not isinstance(info[0], str) or not isinstance(info[1], int):
                #unsupported listener info format
                continue
            address, port = info
            if address not in ("0.0.0.0", "::/0", "::"):
                #not a wildcard address, use it as-is:
                add_address(socktype, address, port)
                continue
            if not netifaces:
                if first_time("netifaces-socket-address"):
                    netlog.warn("Warning: netifaces is missing")
                    netlog.warn(" socket addresses cannot be queried")
                continue
            ips = []
            for inet in get_interfaces_addresses().values():
                #ie: inet = {
                #    18: [{'addr': ''}],
                #    2: [{'peer': '127.0.0.1', 'netmask': '255.0.0.0', 'addr': '127.0.0.1'}],
                #    30: [{'peer': '::1', 'netmask': 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', 'addr': '::1'},
                #         {'peer': '', 'netmask': 'ffff:ffff:ffff:ffff::', 'addr': 'fe80::1%lo0'}]
                #    }
                for v in (socket.AF_INET, socket.AF_INET6):
                    addresses = inet.get(v, ())
                    for addr in addresses:
                        #ie: addr = {'peer': '127.0.0.1', 'netmask': '255.0.0.0', 'addr': '127.0.0.1'}]
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
    def process_packet(self, proto, packet):
        packet_type = None
        handler = None
        try:
            packet_type = bytestostr(packet[0])
            may_log_packet(False, packet_type, packet)
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                netlog("process packet %s", packet_type)
                handler(proto, packet)
                return
            if not self._closing:
                netlog("invalid packet: %s", packet)
                netlog.error("unknown or invalid packet type: '%s' from %s", packet_type, proto)
            proto.close()
        except KeyboardInterrupt:
            raise
        except Exception:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s",
                         packet_type, handler, exc_info=True)


    def handle_rfb_connection(self, conn):
        log.error("Error: RFB protocol is not supported by this server")
        conn.close()
