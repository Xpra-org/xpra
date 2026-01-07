# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
from time import monotonic
from multiprocessing import Queue as MQueue, freeze_support
from typing import Any
from collections.abc import Callable

from xpra.util.objects import typedict
from xpra.util.signal_emitter import SignalEmitter
from xpra.util.str_fn import csv, repr_ellipsized, print_nested_dict, bytestostr
from xpra.util.env import envint, envbool, envfloat
from xpra.common import ConnectionMessage
from xpra.os_util import (
    get_username_for_uid, get_groups, get_home_for_uid, getuid, getgid, get_group_id, gi_import,
    WIN32, POSIX, OSX,
)
from xpra.util.io import umask_context
from xpra.net.common import Packet, is_request_allowed
from xpra.net.socket_util import SOCKET_DIR_MODE, SOCKET_DIR_GROUP
from xpra.server import features
from xpra.server.core import ServerCore
from xpra.net.control.common import ArgsControlCommand, ControlError
from xpra.auth.common import SessionData
from xpra.util.child_reaper import get_child_reaper
from xpra.scripts.parsing import MODE_ALIAS
from xpra.util.parsing import str_to_bool
from xpra.scripts.config import make_defaults_struct, PROXY_START_OVERRIDABLE_OPTIONS, OPTION_TYPES
from xpra.scripts.main import parse_display_name, start_server_subprocess
from xpra.net.connect import connect_to
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("proxy")
authlog = Logger("auth")

GLib = gi_import("GLib")

freeze_support()

PROXY_SOCKET_TIMEOUT = envfloat("XPRA_PROXY_SOCKET_TIMEOUT", 0.1)
PROXY_WS_TIMEOUT = envfloat("XPRA_PROXY_WS_TIMEOUT", 1.0)
assert PROXY_SOCKET_TIMEOUT > 0, "invalid proxy socket timeout"
CAN_STOP_PROXY = envbool("XPRA_CAN_STOP_PROXY", getuid() != 0 or WIN32)
STOP_PROXY_SOCKET_TYPES = os.environ.get("XPRA_STOP_PROXY_SOCKET_TYPES", "named-pipe").split(",")
STOP_PROXY_AUTH_SOCKET_TYPES = os.environ.get("XPRA_STOP_PROXY_AUTH_SOCKET_TYPES", "socket").split(",")
# something (a thread lock?) doesn't allow us to use multiprocessing on MS Windows:
PROXY_INSTANCE_THREADED = envbool("XPRA_PROXY_INSTANCE_THREADED", WIN32)
PROXY_SSL_THREADED = envbool("XPRA_PROXY_SSL_THREADED", False)
PROXY_CLEANUP_GRACE_PERIOD = envfloat("XPRA_PROXY_CLEANUP_GRACE_PERIOD", 0.5)

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_PROXY_MAX_CONCURRENT_CONNECTIONS", 200)
DEFAULT_ENV_WHITELIST: str = "LANG,HOSTNAME,PWD,TERM,SHELL,SHLVL,PATH,USER,HOME"
if WIN32:
    # DEFAULT_ENV_WHITELIST = "ALLUSERSPROFILE,APPDATA,COMMONPROGRAMFILES,COMMONPROGRAMFILES(X86),"+
    #                        "COMMONPROGRAMW6432,COMPUTERNAME,COMSPEC,FP_NO_HOST_CHECK,LOCALAPPDATA,"+
    #                        "NUMBER_OF_PROCESSORS,OS,PATH,PATHEXT,PROCESSOR_ARCHITECTURE,"+
    #                        "PROCESSOR_ARCHITECTURE,PROCESSOR_IDENTIFIER,PROCESSOR_LEVEL,"+
    #                        "PROCESSOR_REVISION,PROGRAMDATA,PROGRAMFILES,PROGRAMFILES(X86),"+
    #                        "PROGRAMW6432,PSMODULEPATH,PUBLIC,SYSTEMDRIVE,SYSTEMROOT,TEMP,TMP,"+
    #                        "USERDOMAIN,WORKGROUP,USERNAME,USERPROFILE,WINDIR,"+
    #                        "XPRA_REDIRECT_OUTPUT,XPRA_LOG_FILENAME,XPRA_ALL_DEBUG"
    DEFAULT_ENV_WHITELIST = "*"
ENV_WHITELIST: list[str] = os.environ.get("XPRA_PROXY_ENV_WHITELIST", DEFAULT_ENV_WHITELIST).split(",")


def get_socktype(proto) -> str:
    try:
        return proto._conn.socktype
    except AttributeError:
        return "unknown"


def create_system_dir(sps: str) -> None:
    if not POSIX or OSX or not sps:
        return
    xpra_group_id = get_group_id(SOCKET_DIR_GROUP)
    if sps.startswith("/run/xpra") or sps.startswith("/var/run/xpra"):
        # create the directory and verify its permissions
        # which should have been set correctly by tmpfiles.d,
        # but may have been set wrong if created by systemd's socket activation instead
        d = sps.split("/xpra")[0] + "/xpra"
        try:
            if os.path.exists(d):
                stat = os.stat(d)
                mode = stat.st_mode
                if (mode & SOCKET_DIR_MODE) != SOCKET_DIR_MODE:
                    log.warn("Warning: invalid permissions on '%s' : %s", d, oct(mode))
                    mode = mode | SOCKET_DIR_MODE
                    log.warn(" changing to %s", oct(mode))
                    os.chmod(d, mode)
                # noinspection PyChainedComparisons
                if xpra_group_id >= 0 and stat.st_gid != xpra_group_id:
                    import grp
                    group = grp.getgrgid(stat.st_gid)[0]
                    log.warn("Warning: invalid group on '%s': %s", d, group)
                    log.warn(" changing to '%s'", SOCKET_DIR_GROUP)
                    os.lchown(d, stat.st_uid, xpra_group_id)
            else:
                log.info("creating '%s' with permissions %s and group '%s'",
                         d, oct(SOCKET_DIR_MODE), SOCKET_DIR_GROUP)
                with umask_context(0):
                    os.mkdir(d, SOCKET_DIR_MODE)
                stat = os.stat(d)
                # noinspection PyChainedComparisons
                if xpra_group_id >= 0 and stat.st_gid != xpra_group_id:
                    os.lchown(d, stat.st_uid, xpra_group_id)
            mode = os.stat(d).st_mode
            log("%s permissions: %s", d, oct(mode))
        except OSError as e:
            log("create_system_dir()", exc_info=True)
            log.error("Error: failed to create or change the permissions on '%s':", d)
            log.estr(e)


def get_proxy_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ENV_WHITELIST or "*" in ENV_WHITELIST}
    # env var to add to environment of subprocess:
    extra_env_str = os.environ.get("XPRA_PROXY_START_ENV", "")
    if extra_env_str:
        extra_env = {}
        for e in extra_env_str.split(os.path.pathsep):  # ie: "A=1:B=2"
            parts = e.split("=", 1)
            if len(parts) == 2:
                extra_env[parts[0]] = parts[1]
        log("extra_env(%s)=%s", extra_env_str, extra_env)
        env.update(extra_env)
    return env


def get_proxy_server_base_classes() -> tuple[type, ...]:
    classes: list[type] = [ServerCore]
    if features.dbus:
        from xpra.server.subsystem.dbus import DbusServer
        classes.append(DbusServer)
    if features.http:
        from xpra.server.subsystem.http import HttpServer
        classes.append(HttpServer)
    return tuple(classes)


SERVER_BASES = get_proxy_server_base_classes()
ProxyServerBaseClass = type("ProxyServerBaseClass", SERVER_BASES, {})


class ProxyServer(ProxyServerBaseClass, SignalEmitter):
    """
        This is the proxy server you can launch with "xpra proxy",
        once authenticated, it will dispatch the connection
        to the session found using the authenticator's
        get_sessions() function.
    """

    def __init__(self):
        log("ProxyServer.__init__()")
        SignalEmitter.__init__(self)
        for bc in SERVER_BASES:
            bc.__init__(self)
        self.hello_request_handlers["stop"] = self._handle_hello_request_stop
        self._max_connections = MAX_CONCURRENT_CONNECTIONS
        self._start_sessions = False
        self.session_type = "proxy"
        # proxy servers may have to connect to remote servers,
        # or even start them, so allow more time before timing out:
        self._accept_timeout += 10
        self.pings = 0
        self._start_sessions = False
        # keep track of the proxy process instances
        # the display they're on and the message queue we can
        # use to communicate with them
        self.instances = {}
        # connections used exclusively for requests:
        self._requests = set()
        self._socket_timeout = PROXY_SOCKET_TIMEOUT
        self._ws_timeout = PROXY_WS_TIMEOUT

    def init(self, opts) -> None:
        log("ProxyServer.init(%s)", opts)
        self.pings = int(opts.pings)
        self._start_sessions = opts.proxy_start_sessions
        for bc in SERVER_BASES:
            bc.init(self, opts)
        # ensure we cache the platform info before intercepting SIGCHLD
        # as this will cause a fork and SIGCHLD to be emitted:
        from xpra.util.version import get_platform_info
        get_platform_info()
        create_system_dir(opts.system_proxy_socket)

    def init_control_commands(self) -> None:
        super().init_control_commands()
        if features.control:
            self.add_control_command("stop", ArgsControlCommand("stop",
                                                                "stops the proxy instance on the given display",
                                                                self.handle_stop_command, min_args=1, max_args=1))

    def install_signal_handlers(self, callback: Callable[[int], None]) -> None:
        from xpra.util.glib import register_SIGUSR_signals
        from xpra.util.glib import register_os_signals
        register_os_signals(callback, "Proxy Server")
        register_SIGUSR_signals("Proxy Server")

    def make_dbus_server(self):
        from xpra.server.proxy.proxy_dbus_server import Proxy_DBUS_Server  # pylint: disable=import-outside-toplevel
        return Proxy_DBUS_Server(self)

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        # add shutdown handler
        self._default_packet_handlers["shutdown-server"] = self._process_proxy_shutdown_server

    def _process_proxy_shutdown_server(self, proto, _packet: Packet) -> None:
        assert proto in self._requests
        self.clean_quit(False)

    def handle_stop_command(self, *args) -> str:
        display = args[0]
        log("stop command: will try to find proxy process for display %s", display)
        for instance, v in dict(self.instances).items():
            _, disp, _ = v
            if disp == display:
                log.info("stop command: found matching process %s with pid %i for display %s",
                         instance, instance.pid, display)
                self.stop_proxy(instance)
                return f"stopped proxy instance for display {display}"
        raise ControlError(f"no proxy found for display {display}")

    def stop_all_proxies(self, force: bool = False) -> None:
        instances = self.instances
        log("stop_all_proxies() will stop proxy instances: %s", instances)
        for instance in tuple(instances.keys()):
            self.stop_proxy(instance, force)
        log("stop_all_proxies() done")

    def stop_proxy(self, instance, force: bool = False) -> None:
        v = self.instances.get(instance)
        if not v:
            log.error("Error: proxy instance not found for %s", instance)
            return
        log("stop_proxy(%s) is_alive=%s", instance, instance.is_alive())
        if not instance.is_alive() and not force:
            return
        isprocess, _, mq = v
        log("stop_proxy(%s) %s", instance, v)
        # different ways of stopping for process vs threaded implementations:
        if isprocess:
            # send message:
            if force:
                instance.terminate()
            else:
                mq.put_nowait("stop")
                try:
                    mq.close()
                except Exception as e:
                    log("%s() %s", mq.close, e)
        else:
            # direct method call:
            instance.stop(None, "proxy server request")

    def cleanup(self) -> None:
        self.stop_all_proxies()
        for bc in SERVER_BASES:
            bc.cleanup(self)
        start = monotonic()
        live = True
        log("cleanup() proxy instances: %s", self.instances)
        while monotonic() - start < PROXY_CLEANUP_GRACE_PERIOD and live:
            live = tuple(x for x in tuple(self.instances.keys()) if x.is_alive())
            if live:
                log("cleanup() still %i proxies alive: %s", len(live), live)
                time.sleep(0.1)
        if live:
            self.stop_all_proxies(True)
        log("cleanup() frames remaining:")
        from xpra.util.pysystem import dump_all_frames
        dump_all_frames(log)

    def log_closing_message(self) -> None:
        log.info("Proxy Server process ended")

    def verify_connection_accepted(self, protocol) -> None:
        # if we start a proxy, the protocol will be closed
        # (a new one is created in the proxy process)
        if not protocol.is_closed():
            self.send_disconnect(protocol, ConnectionMessage.LOGIN_TIMEOUT)

    def hello_oked(self, proto, c: typedict, auth_caps: dict) -> None:
        if super().hello_oked(proto, c, auth_caps):
            # already handled in superclass
            return
        self.accept_client(proto, c)
        request = c.strget("request")

        if request:
            if not self.handle_hello_request(request, proto, c):
                self.send_disconnect(proto, f"error: invalid request, {request!r} is not supported by the proxy server")
            return
        self.proxy_auth(proto, c, auth_caps)

    # override the default hello info request handler:
    def _handle_hello_request_info(self, proto, _caps: typedict) -> bool:
        info = self.get_session_id_info()
        log_file = os.environ.get("XPRA_SERVER_LOG", "")
        info["log-file"] = log_file
        self.do_send_info(proto, info)
        return True

    def _handle_hello_request_stop(self, proto, _caps: typedict) -> bool:
        self.handle_stop_request(proto)
        return True

    def handle_stop_request(self, proto) -> None:
        socktype = get_socktype(proto)
        default_can_stop = CAN_STOP_PROXY
        default_can_stop |= socktype in STOP_PROXY_SOCKET_TYPES
        default_can_stop |= (socktype in STOP_PROXY_AUTH_SOCKET_TYPES) and proto.authenticators
        if not is_request_allowed(proto, "stop", default_can_stop):
            msg = "`stop` requests are not enabled for this proxy server connection"
            log.warn(f"Warning: {msg}")
            self.send_disconnect(proto, msg)
            return

        self._requests.add(proto)
        # send a hello back and the client should then send its "shutdown-server" packet
        capabilities = self.make_hello(None)
        proto.send_now(Packet("hello", capabilities))

        def force_exit_request_client() -> None:
            try:
                self._requests.remove(proto)
            except KeyError:
                pass
            if not proto.is_closed():
                self.send_disconnect(proto, "timeout")

        GLib.timeout_add(10 * 1000, force_exit_request_client)

    def proxy_auth(self, client_proto, c: typedict, auth_caps: dict) -> None:
        def disconnect(reason, *extras) -> None:
            log("disconnect(%s, %s)", reason, extras)
            self.send_disconnect(client_proto, reason, *extras)

        def nosession(*extras) -> None:
            disconnect(ConnectionMessage.SESSION_NOT_FOUND, *extras)

        # find the target server session:
        if not client_proto.authenticators:
            log.error("Error: the proxy server requires an authentication mode,")
            try:
                log.error(" client connection '%s' does not specify one", get_socktype(client_proto))
            except AttributeError:
                pass
            log.error(" use 'none' to disable authentication")
            nosession("no sessions found")
            return
        sessions : SessionData | None = None
        for authenticator in client_proto.authenticators:
            try:
                auth_sessions = authenticator.get_sessions()
                authlog("proxy_auth %s.get_sessions()=%s", authenticator, auth_sessions)
                if auth_sessions:
                    sessions = auth_sessions
                    break
            except Exception as e:
                authlog("failed to get the list of sessions from %s", authenticator, exc_info=True)
                authlog.error("Error: failed to get the list of sessions using '%s' authenticator", authenticator)
                authlog.estr(e)
                disconnect(ConnectionMessage.AUTHENTICATION_ERROR, "cannot access sessions")
                return
        authlog("proxy_auth(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        if sessions is None:
            nosession("no sessions found")
            return
        self.proxy_session(client_proto, c, auth_caps, sessions)

    def proxy_session(self, client_proto, c: typedict, auth_caps: dict, sessions: SessionData) -> None:
        def disconnect(reason, *extras) -> None:
            log("disconnect(%s, %s)", reason, extras)
            self.send_disconnect(client_proto, reason, *extras)

        def nosession(*extras) -> None:
            disconnect(ConnectionMessage.SESSION_NOT_FOUND, *extras)

        uid, gid, displays, env_options, session_options = sessions
        if POSIX:
            if getuid() == 0:
                if uid == 0 or gid == 0:
                    log.error("Error: proxy instances cannot run as root")
                    log.error(" use a different uid and gid (ie: nobody)")
                    disconnect(ConnectionMessage.AUTHENTICATION_ERROR, "cannot run proxy instances as root")
                    return
            else:
                uid = getuid()
                gid = getgid()
            username = get_username_for_uid(uid)
            password = None
            groups = get_groups(username)
            log("username(%i)=%s, groups=%s", uid, username, groups)
        else:
            # the auth module recorded the username we authenticate against
            assert client_proto.authenticators
            username = password = ""
            for authenticator in client_proto.authenticators:
                username = getattr(authenticator, "username", "")
                password = authenticator.get_password()
                if username:
                    break
        # ensure we don't loop back to the proxy:
        proxy_virtual_display = os.environ.get("DISPLAY", "")
        if proxy_virtual_display in displays:
            displays.remove(proxy_virtual_display)
        # remove proxy instance virtual displays:
        displays = [x for x in displays if not x.startswith(":proxy-")]
        # log("unused options: %s, %s", env_options, session_options)
        proc = None
        socket_path = None
        display = None
        sns = c.dictget("start-new-session", {})
        authlog("proxy_session: displays=%s, start_sessions=%s, start-new-session=%s",
                displays, self._start_sessions, sns)
        if not displays or sns:
            if not self._start_sessions:
                nosession("no displays found")
                return
            try:
                proc, socket_path, display = self.start_new_session(username, password, uid, gid, sns, displays)
                log("start_new_session%s=%s", (username, "..", uid, gid, sns, displays), (proc, socket_path, display))
            except Exception as e:
                log("start_server_subprocess failed", exc_info=True)
                log.error("Error: failed to start new session subprocess:")
                log.estr(e)
                nosession("failed to start a new session")
                return
        if display is None:
            display = c.strget("display")
            authlog("proxy_session: proxy-virtual-display=%s (ignored), user specified display=%s, found displays=%s",
                    proxy_virtual_display, display, displays)
            if display == proxy_virtual_display:
                nosession("invalid display: proxy display")
                return
            if display:
                if display not in displays:
                    if f":{display}" in displays:
                        display = f":{display}"
                    else:
                        nosession(f"display {display!r} not found")
                        return
            else:
                if len(displays) != 1:
                    nosession("please specify a display, more than one is available: " + csv(sorted(displays)))
                    return
                display = displays[0]

        connect = c.boolget("connect", True)
        # ConnectTestXpraClient doesn't want to connect to the real session either:
        ctr = c.strget("connect_test_request")
        log("connect=%s, connect_test_request=%s", connect, ctr)
        if not connect or ctr:
            log("proxy_session: not connecting to the session")
            hello = {"display": display}
            if socket_path:
                hello["socket-path"] = socket_path
            # echo mode if present:
            mode = str(sns.get("mode", ""))
            if mode:
                hello["mode"] = mode
            client_proto.send_now(Packet("hello", hello))
            return

        def stop_server_subprocess() -> None:
            log("stop_server_subprocess() proc=%s", proc)
            if proc and proc.poll() is None:
                proc.terminate()

        log("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)

        def parse_error(*args) -> None:
            stop_server_subprocess()
            nosession("invalid display string")
            log.warn("Error: parsing failed for display string '%s':", display)
            for arg in args:
                log.warn(" %s", arg)
            raise ValueError(f"parse error on {display!r} {args}")

        opts = make_defaults_struct(username=username, uid=uid, gid=gid)
        opts.username = username
        disp_desc = parse_display_name(parse_error, opts, display)
        if uid or gid:
            disp_desc["uid"] = uid
            disp_desc["gid"] = gid
        log("display description(%s) = %s", display, disp_desc)
        try:
            server_conn = connect_to(disp_desc, opts)
        except Exception as e:
            log("cannot connect", exc_info=True)
            log.error("Error: cannot start proxy connection:")
            for x in str(e).splitlines():
                log.error(" %s", x)
            log.error(" connection definition:")
            print_nested_dict(disp_desc, prefix=" ", lchar="*", pad=20, print_fn=log.error)
            nosession("failed to connect to display")
            stop_server_subprocess()
            return
        log("server connection=%s", server_conn)

        cipher = cipher_mode = ""
        encryption_key = b""
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                from xpra.net.crypto import DEFAULT_MODE  # pylint: disable=import-outside-toplevel
                cipher_mode = auth_caps.get("cipher.mode", DEFAULT_MODE)
                encryption_key = self.get_encryption_key(client_proto.authenticators, client_proto.keyfile)

        use_thread = PROXY_INSTANCE_THREADED
        if not use_thread and PROXY_SSL_THREADED:
            client_socktype = get_socktype(client_proto)
            server_socktype = disp_desc["type"]
            if client_socktype in ("ssl", "wss", "ssh"):
                log.info("using threaded mode for %s client connection", client_socktype)
                use_thread = True
            elif server_socktype in ("ssl", "wss", "ssh"):
                log.info("using threaded mode for %s server connection", server_socktype)
                use_thread = True
        if use_thread:
            if env_options:
                log.warn("environment options are ignored in threaded mode")
            from xpra.server.proxy.instance_thread import ProxyInstanceThread
            pit = ProxyInstanceThread(session_options, self.pings,
                                      client_proto, server_conn,
                                      disp_desc, cipher, cipher_mode, encryption_key, c)
            pit.stopped = self.reap
            pit.run()
            self.instances[pit] = (False, display, None)
            return

        # this may block, so run it in a thread:
        def start_proxy_process() -> None:
            log("start_proxy_process()")
            message_queue = MQueue()
            client_conn = None
            try:
                # no other packets should be arriving until the proxy instance responds to the initial hello packet
                def unexpected_packet(packet) -> None:
                    if packet:
                        log.warn("Warning: received an unexpected packet")
                        log.warn(" from the proxy connection %s:", client_proto)
                        log.warn(" %s", repr_ellipsized(packet))
                        client_proto.close()

                client_conn = client_proto.steal_connection(unexpected_packet)
                client_state = client_proto.save_state()
                log("start_proxy_process(..) client connection=%s", client_conn)
                log("start_proxy_process(..) client state=%s", client_state)

                ioe = client_proto.wait_for_io_threads_exit(5 + self._socket_timeout)
                if not ioe:
                    log.error("Error: some network IO threads have failed to terminate")
                    client_proto.close()
                    return
                client_conn.set_active(True)
                from xpra.server.proxy.instance_process import ProxyInstanceProcess
                process = ProxyInstanceProcess(uid, gid, env_options, session_options, self._socket_dir,
                                               self.pings,
                                               client_conn, disp_desc, client_state,
                                               cipher, cipher_mode, encryption_key, server_conn, c, message_queue)
                log("starting %s from pid=%s", process, os.getpid())
                self.instances[process] = (True, display, message_queue)
                process.start()
                log("ProxyInstanceProcess started")
                popen = process._popen
                assert popen
                # when this process dies, run reap to update our list of proxy instances:
                get_child_reaper().add_process(popen, f"xpra-proxy-{display}",
                                               "xpra-proxy-instance", True, True, self.reap)
            except Exception as pie:
                log("start_proxy_process() failed", exc_info=True)
                log.error("Error starting proxy instance process:")
                log.estr(pie)
                message_queue.put(f"error: {pie}")
                message_queue.put("stop")
            finally:
                # now we can close our handle on the connection:
                log("handover complete: closing connection from proxy server")
                if client_conn:
                    client_conn.close()
                server_conn.close()
                log("sending socket-handover-complete")
                message_queue.put("socket-handover-complete")

        start_thread(start_proxy_process, f"start_proxy({client_proto})")

    def start_new_session(self, username: str, _password, uid: int, gid: int,
                          sess_options: dict, displays=()) -> tuple[Any, str, str]:
        log("start_new_session%s", (username, "..", uid, gid, sess_options, displays))
        sns = typedict(sess_options or {})
        mode = sns.strget("mode", "start")
        mode = MODE_ALIAS.get(mode, mode)
        if mode not in ("seamless", "desktop", "shadow", "monitor", "expand"):
            raise ValueError(f"invalid start-new-session mode {mode!r}")
        display = sns.strget("display")
        if display in displays:
            raise ValueError(f"display {display} is already active!")
        log("starting new server subprocess: mode=%s, display=%s", mode, display)
        args: list[str] = []
        if display:
            args = [display]
        # allow the client to override some options:
        opts = make_defaults_struct(username=username, uid=uid, gid=gid)
        for k, v in sns.items():
            k = bytestostr(k)
            if k in ("mode", "display"):
                continue  # those special attributes have been consumed already
            if k not in PROXY_START_OVERRIDABLE_OPTIONS:
                log.warn("Warning: ignoring invalid start override")
                log.warn(" %s=%s", k, v)
                continue
            vt = OPTION_TYPES[k]
            try:
                if vt is str:
                    v = bytestostr(v)
                elif vt is bool:
                    v = str_to_bool(v)
                elif vt is int:
                    v = int(v)
                elif vt is list:
                    v = list(bytestostr(x) for x in v)
            except ValueError:
                log("start_new_session: override option %s", k, exc_info=True)
                log.warn("Warning: ignoring invalid value %s for %s (%s)", v, k, vt)
                continue
            if v is not None:
                fn = k.replace("-", "_")
                curr = getattr(opts, fn, None)
                if curr != v:
                    log("start override: %24s=%-24s (default=%s)", k, v, curr)
                    setattr(opts, fn, v)
                else:
                    log("start override: %24s=%-24s (unchanged)", k, v)
            else:
                log("start override: %24s=%-24s (invalid, unchanged)", k, v)
        opts.attach = False
        opts.start_via_proxy = False
        env = get_proxy_env()
        cwd = None
        if uid > 0:
            cwd = get_home_for_uid(uid) or None
            if not cwd or not os.path.exists(cwd):
                import tempfile
                cwd = tempfile.gettempdir()
        log("starting new server subprocess: options=%s", opts)
        log("env=%s", env)
        log("args=%s", args)
        log("cwd=%s", cwd)
        proc, socket_path, display = start_server_subprocess(sys.argv[0], args,
                                                             mode, opts, username, uid, gid, env, cwd)
        if proc:
            get_child_reaper().add_process(proc, "server-%s" % (display or socket_path), f"xpra {mode}", True, True)
        log("start_new_session(..) pid=%s, socket_path=%s, display=%s, ", proc.pid, socket_path, display)
        return proc, socket_path, display

    def reap(self, *args) -> None:
        log("reap%s", args)
        dead = []
        for instance in tuple(self.instances.keys()):
            # instance is a process
            if not instance.is_alive():
                dead.append(instance)
        log("reap%s dead processes: %s", args, dead or None)
        for p in dead:
            del self.instances[p]

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        authenticated = bool(proto and proto.authenticators)
        if not authenticated:
            info = self.get_minimal_server_info()
        else:
            # only show more info if we have authenticated
            # as the user running the proxy server process:
            info = super().get_threaded_info(proto, **kwargs)
            sessions = ()
            for authenticator in proto.authenticators:
                auth_sessions = authenticator.get_sessions()
                if auth_sessions:
                    sessions = auth_sessions
                    break
            if sessions:
                uid, gid = sessions[:2]
                if not POSIX or (uid == getuid() and gid == getgid()):
                    self.reap()
                    i = 0
                    instances = dict(self.instances)
                    instances_info = {}
                    for proxy_instance, v in instances.items():
                        isprocess, d, _ = v
                        iinfo = {
                            "display": d,
                            "live": proxy_instance.is_alive(),
                        }
                        if isprocess:
                            iinfo.update({
                                "pid": proxy_instance.pid,
                            })
                        else:
                            iinfo.update(proxy_instance.get_info())
                        instances_info[i] = iinfo
                        i += 1
                    info["instances"] = instances_info
                    info["proxies"] = len(instances)
        info.setdefault("server", {})["type"] = "Python/GLib/proxy"
        return info
