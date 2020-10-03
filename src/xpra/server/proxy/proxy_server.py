# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
from multiprocessing import Queue as MQueue, freeze_support #@UnresolvedImport
from gi.repository import GLib

from xpra.util import (
    LOGIN_TIMEOUT, AUTHENTICATION_ERROR, SESSION_NOT_FOUND, SERVER_ERROR,
    repr_ellipsized, print_nested_dict, csv, envfloat, envbool, envint, typedict,
    )
from xpra.os_util import (
    get_username_for_uid, get_groups, get_home_for_uid, bytestostr,
    getuid, getgid, WIN32, POSIX,
    monotonic_time,
    )
from xpra.server.server_core import ServerCore
from xpra.server.control_command import ArgsControlCommand, ControlError
from xpra.child_reaper import getChildReaper
from xpra.scripts.parsing import parse_bool
from xpra.scripts.config import make_defaults_struct, PROXY_START_OVERRIDABLE_OPTIONS, OPTION_TYPES
from xpra.scripts.main import parse_display_name, connect_to, start_server_subprocess
from xpra.make_thread import start_thread
from xpra.log import Logger

log = Logger("proxy")
authlog = Logger("proxy", "auth")

freeze_support()


PROXY_SOCKET_TIMEOUT = envfloat("XPRA_PROXY_SOCKET_TIMEOUT", "0.1")
PROXY_WS_TIMEOUT = envfloat("XPRA_PROXY_WS_TIMEOUT", "1.0")
assert PROXY_SOCKET_TIMEOUT>0, "invalid proxy socket timeout"
CAN_STOP_PROXY = envbool("XPRA_CAN_STOP_PROXY", getuid()!=0 or WIN32)
STOP_PROXY_SOCKET_TYPES = os.environ.get("XPRA_STOP_PROXY_SOCKET_TYPES", "unix-domain,named-pipe").split(",")
STOP_PROXY_AUTH_SOCKET_TYPES = os.environ.get("XPRA_STOP_PROXY_AUTH_SOCKET_TYPES", "unix-domain").split(",")
#something (a thread lock?) doesn't allow us to use multiprocessing on MS Windows:
PROXY_INSTANCE_THREADED = envbool("XPRA_PROXY_INSTANCE_THREADED", WIN32)
PROXY_CLEANUP_GRACE_PERIOD = envfloat("XPRA_PROXY_CLEANUP_GRACE_PERIOD", "0.5")

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_PROXY_MAX_CONCURRENT_CONNECTIONS", 200)
if WIN32:
    #DEFAULT_ENV_WHITELIST = "ALLUSERSPROFILE,APPDATA,COMMONPROGRAMFILES,COMMONPROGRAMFILES(X86),COMMONPROGRAMW6432,COMPUTERNAME,COMSPEC,FP_NO_HOST_CHECK,LOCALAPPDATA,NUMBER_OF_PROCESSORS,OS,PATH,PATHEXT,PROCESSOR_ARCHITECTURE,PROCESSOR_ARCHITECTURE,PROCESSOR_IDENTIFIER,PROCESSOR_LEVEL,PROCESSOR_REVISION,PROGRAMDATA,PROGRAMFILES,PROGRAMFILES(X86),PROGRAMW6432,PSMODULEPATH,PUBLIC,SYSTEMDRIVE,SYSTEMROOT,TEMP,TMP,USERDOMAIN,WORKGROUP,USERNAME,USERPROFILE,WINDIR,XPRA_REDIRECT_OUTPUT,XPRA_LOG_FILENAME,XPRA_ALL_DEBUG"
    DEFAULT_ENV_WHITELIST = "*"
else:
    DEFAULT_ENV_WHITELIST = "LANG,HOSTNAME,PWD,TERM,SHELL,SHLVL,PATH"
ENV_WHITELIST = os.environ.get("XPRA_PROXY_ENV_WHITELIST", DEFAULT_ENV_WHITELIST).split(",")


def get_socktype(proto):
    try:
        return proto._conn.socktype
    except AttributeError:
        return "unknown"


class ProxyServer(ServerCore):
    """
        This is the proxy server you can launch with "xpra proxy",
        once authenticated, it will dispatch the connection
        to the session found using the authenticator's
        get_sessions() function.
    """

    def __init__(self):
        log("ProxyServer.__init__()")
        ServerCore.__init__(self)
        self._max_connections = MAX_CONCURRENT_CONNECTIONS
        self._start_sessions = False
        self.session_type = "proxy"
        self.main_loop = None
        #proxy servers may have to connect to remote servers,
        #or even start them, so allow more time before timing out:
        self._accept_timeout += 10
        self.pings = 0
        self.video_encoders = ()
        self._start_sessions = False
        #keep track of the proxy process instances
        #the display they're on and the message queue we can
        # use to communicate with them
        self.instances = {}
        #connections used exclusively for requests:
        self._requests = set()
        self.idle_add = GLib.idle_add
        self.timeout_add = GLib.timeout_add
        self.source_remove = GLib.source_remove
        self._socket_timeout = PROXY_SOCKET_TIMEOUT
        self._ws_timeout = PROXY_WS_TIMEOUT

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        self.pings = int(opts.pings)
        self.video_encoders = opts.proxy_video_encoders
        self._start_sessions = opts.proxy_start_sessions
        super().init(opts)
        #ensure we cache the platform info before intercepting SIGCHLD
        #as this will cause a fork and SIGCHLD to be emitted:
        from xpra.version_util import get_platform_info
        get_platform_info()
        self.child_reaper = getChildReaper()

    def init_control_commands(self):
        ServerCore.init_control_commands(self)
        self.control_commands["stop"] = ArgsControlCommand("stop", "stops the proxy instance on the given display",
                                                           self.handle_stop_command, min_args=1, max_args=1)


    def install_signal_handlers(self, callback):
        from xpra.gtk_common.gobject_compat import register_os_signals, register_SIGUSR_signals
        register_os_signals(callback, "Proxy Server")
        register_SIGUSR_signals("Proxy Server")


    def make_dbus_server(self):
        from xpra.server.proxy.proxy_dbus_server import Proxy_DBUS_Server
        return Proxy_DBUS_Server(self)


    def init_packet_handlers(self):
        ServerCore.init_packet_handlers(self)
        #add shutdown handler
        self._default_packet_handlers["shutdown-server"] = self._process_proxy_shutdown_server

    def _process_proxy_shutdown_server(self, proto, _packet):
        assert proto in self._requests
        self.clean_quit(False)


    def print_screen_info(self):
        #no screen, we just use a virtual display number
        pass

    def get_server_mode(self):
        return "proxy"

    def init_aliases(self):
        pass

    def do_run(self):
        self.main_loop = GLib.MainLoop()
        self.main_loop.run()

    def handle_stop_command(self, *args):
        display = args[0]
        log("stop command: will try to find proxy process for display %s", display)
        for instance, v in dict(self.instances).items():
            _, disp, _ = v
            if disp==display:
                log.info("stop command: found matching process %s with pid %i for display %s",
                         instance, instance.pid, display)
                self.stop_proxy(instance)
                return "stopped proxy instance for display %s" % display
        raise ControlError("no proxy found for display %s" % display)

    def stop_all_proxies(self, force=False):
        instances = self.instances
        log("stop_all_proxies() will stop proxy instances: %s", instances)
        for instance in tuple(instances.keys()):
            self.stop_proxy(instance, force)
        log("stop_all_proxies() done")

    def stop_proxy(self, instance, force=False):
        v = self.instances.get(instance)
        if not v:
            log.error("Error: proxy instance not found for %s", instance)
            return
        log("stop_proxy(%s) is_alive=%s", instance, instance.is_alive())
        if not instance.is_alive() and not force:
            return
        isprocess, _, mq = v
        log("stop_proxy(%s) %s", instance, v)
        #different ways of stopping for process vs threaded implementations:
        if isprocess:
            #send message:
            if force:
                instance.terminate()
            else:
                mq.put_nowait("stop")
                try:
                    mq.close()
                except Exception as e:
                    log("%s() %s", mq.close, e)
        else:
            #direct method call:
            instance.stop(None, "proxy server request")


    def cleanup(self):
        self.stop_all_proxies()
        ServerCore.cleanup(self)
        start = monotonic_time()
        live = True
        log("cleanup() proxy instances: %s", self.instances)
        while monotonic_time()-start<PROXY_CLEANUP_GRACE_PERIOD and live:
            live = tuple(x for x in tuple(self.instances.keys()) if x.is_alive())
            if live:
                log("cleanup() still %i proxies alive: %s", len(live), live)
                time.sleep(0.1)
        if live:
            self.stop_all_proxies(True)
        log("cleanup() frames remaining:")
        from xpra.util import dump_all_frames
        dump_all_frames(log)


    def do_quit(self):
        self.main_loop.quit()
        log.info("Proxy Server process ended")
        #from now on, we can't rely on the main loop:
        from xpra.os_util import register_SIGUSR_signals
        register_SIGUSR_signals()


    def verify_connection_accepted(self, protocol):
        #if we start a proxy, the protocol will be closed
        #(a new one is created in the proxy process)
        if not protocol.is_closed():
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def hello_oked(self, proto, packet, c, auth_caps):
        if super().hello_oked(proto, packet, c, auth_caps):
            #already handled in superclass
            return
        self.accept_client(proto, c)
        generic_request = c.strget("request")
        def is_req(mode):
            return generic_request==mode or c.boolget("%s_request" % mode)
        if any(is_req(x) for x in ("screenshot", "event", "print", "exit")):
            self.send_disconnect(proto, "invalid request")
            return
        if is_req("stop"):
            #global kill switch:
            if not CAN_STOP_PROXY:
                msg = "cannot stop proxy server"
                log.warn("Warning: %s", msg)
                self.send_disconnect(proto, msg)
                return
            #verify socket type (only local connections by default):
            socktype = get_socktype(proto)
            if socktype not in STOP_PROXY_SOCKET_TYPES:
                msg = "cannot stop proxy server from a '%s' connection" % socktype
                log.warn("Warning: %s", msg)
                log.warn(" only from: %s", csv(STOP_PROXY_SOCKET_TYPES))
                self.send_disconnect(proto, msg)
                return
            #connection must be authenticated:
            if socktype in STOP_PROXY_AUTH_SOCKET_TYPES and not proto.authenticators:
                msg = "cannot stop proxy server from unauthenticated connections"
                log.warn("Warning: %s", msg)
                self.send_disconnect(proto, msg)
                return
            self._requests.add(proto)
            #send a hello back and the client should then send its "shutdown-server" packet
            capabilities = self.make_hello()
            proto.send_now(("hello", capabilities))
            def force_exit_request_client():
                try:
                    self._requests.remove(proto)
                except KeyError:
                    pass
                if not proto.is_closed():
                    self.send_disconnect(proto, "timeout")
            self.timeout_add(10*1000, force_exit_request_client)
            return
        self.proxy_auth(proto, c, auth_caps)

    def proxy_auth(self, client_proto, c, auth_caps):
        def disconnect(reason, *extras):
            log("disconnect(%s, %s)", reason, extras)
            self.send_disconnect(client_proto, reason, *extras)

        #find the target server session:
        if not client_proto.authenticators:
            log.error("Error: the proxy server requires an authentication mode,")
            try:
                log.error(" client connection '%s' does not specify one", get_socktype(client_proto))
            except AttributeError:
                pass
            log.error(" use 'none' to disable authentication")
            disconnect(SESSION_NOT_FOUND, "no sessions found")
            return
        sessions = None
        authenticator = None
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
                authlog.error(" %s", e)
                disconnect(AUTHENTICATION_ERROR, "cannot access sessions")
                return
        authlog("proxy_auth(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        if sessions is None:
            disconnect(SESSION_NOT_FOUND, "no sessions found")
            return
        self.proxy_session(client_proto, c, auth_caps, sessions)

    def proxy_session(self, client_proto, c, auth_caps, sessions):
        def disconnect(reason, *extras):
            log("disconnect(%s, %s)", reason, extras)
            self.send_disconnect(client_proto, reason, *extras)
        uid, gid, displays, env_options, session_options = sessions
        if POSIX:
            if getuid()==0:
                if uid==0 or gid==0:
                    log.error("Error: proxy instances cannot run as root")
                    log.error(" use a different uid and gid (ie: nobody)")
                    disconnect(AUTHENTICATION_ERROR, "cannot run proxy instances as root")
                    return
            else:
                uid = getuid()
                gid = getgid()
            username = get_username_for_uid(uid)
            password = None
            groups = get_groups(username)
            log("username(%i)=%s, groups=%s", uid, username, groups)
        else:
            #the auth module recorded the username we authenticate against
            assert client_proto.authenticators
            for authenticator in client_proto.authenticators:
                username = getattr(authenticator, "username", "")
                password = authenticator.get_password()
                if username:
                    break
        #ensure we don't loop back to the proxy:
        proxy_virtual_display = os.environ.get("DISPLAY")
        if proxy_virtual_display in displays:
            displays.remove(proxy_virtual_display)
        #remove proxy instance virtual displays:
        displays = [x for x in displays if not x.startswith(":proxy-")]
        #log("unused options: %s, %s", env_options, session_options)
        proc = None
        socket_path = None
        display = None
        sns = typedict(c.dictget("start-new-session", {}))
        authlog("proxy_session: displays=%s, start_sessions=%s, start-new-session=%s",
                displays, self._start_sessions, sns)
        if not displays or sns:
            if not self._start_sessions:
                disconnect(SESSION_NOT_FOUND, "no displays found")
                return
            try:
                proc, socket_path, display = self.start_new_session(username, password, uid, gid, sns, displays)
                log("start_new_session%s=%s", (username, "..", uid, gid, sns, displays), (proc, socket_path, display))
            except Exception as e:
                log("start_server_subprocess failed", exc_info=True)
                log.error("Error: failed to start server subprocess:")
                log.error(" %s", e)
                disconnect(SERVER_ERROR, "failed to start a new session")
                return
        if display is None:
            display = c.strget("display")
            authlog("proxy_session: proxy-virtual-display=%s (ignored), user specified display=%s, found displays=%s",
                    proxy_virtual_display, display, displays)
            if display==proxy_virtual_display:
                disconnect(SESSION_NOT_FOUND, "invalid display")
                return
            if display:
                if display not in displays:
                    disconnect(SESSION_NOT_FOUND, "display '%s' not found" % display)
                    return
            else:
                if len(displays)!=1:
                    disconnect(SESSION_NOT_FOUND,
                               "please specify a display, more than one is available: %s" % csv(displays))
                    return
                display = displays[0]

        connect = c.boolget("connect", True)
        #ConnectTestXpraClient doesn't want to connect to the real session either:
        ctr = c.strget("connect_test_request")
        log("connect=%s, connect_test_request=%s", connect, ctr)
        if not connect or ctr:
            log("proxy_session: not connecting to the session")
            hello = {"display" : display}
            if socket_path:
                hello["socket-path"] = socket_path
            #echo mode if present:
            mode = sns.strget("mode")
            if mode:
                hello["mode"] = mode
            client_proto.send_now(("hello", hello))
            return

        def stop_server_subprocess():
            log("stop_server_subprocess() proc=%s", proc)
            if proc and proc.poll() is None:
                proc.terminate()

        log("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)
        def parse_error(*args):
            stop_server_subprocess()
            disconnect(SESSION_NOT_FOUND, "invalid display string")
            log.warn("Error: parsing failed for display string '%s':", display)
            for arg in args:
                log.warn(" %s", arg)
            raise Exception("parse error on %s: %s" % (display, args))
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
            disconnect(SESSION_NOT_FOUND, "failed to connect to display")
            stop_server_subprocess()
            return
        log("server connection=%s", server_conn)

        cipher = None
        encryption_key = None
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                encryption_key = self.get_encryption_key(client_proto.authenticators, client_proto.keyfile)

        use_thread = PROXY_INSTANCE_THREADED
        if not use_thread:
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
            from xpra.server.proxy.proxy_instance_thread import ProxyInstanceThread
            pit = ProxyInstanceThread(session_options, self.video_encoders, self.pings,
                                      client_proto, server_conn,
                                      disp_desc, cipher, encryption_key, c)
            pit.stopped = self.reap
            pit.run()
            self.instances[pit] = (False, display, None)
            return

        #this may block, so run it in a thread:
        def start_proxy_process():
            log("start_proxy_process()")
            message_queue = MQueue()
            client_conn = None
            try:
                #no other packets should be arriving until the proxy instance responds to the initial hello packet
                def unexpected_packet(packet):
                    if packet:
                        log.warn("Warning: received an unexpected packet")
                        log.warn(" from the proxy connection %s:", client_proto)
                        log.warn(" %s", repr_ellipsized(packet))
                        client_proto.close()
                client_conn = client_proto.steal_connection(unexpected_packet)
                client_state = client_proto.save_state()
                log("start_proxy_process(..) client connection=%s", client_conn)
                log("start_proxy_process(..) client state=%s", client_state)

                ioe = client_proto.wait_for_io_threads_exit(5+self._socket_timeout)
                if not ioe:
                    log.error("Error: some network IO threads have failed to terminate")
                    client_proto.close()
                    return
                client_conn.set_active(True)
                from xpra.server.proxy.proxy_instance_process import ProxyInstanceProcess
                process = ProxyInstanceProcess(uid, gid, env_options, session_options, self._socket_dir,
                                               self.video_encoders, self.pings,
                                               client_conn, disp_desc, client_state,
                                               cipher, encryption_key, server_conn, c, message_queue)
                log("starting %s from pid=%s", process, os.getpid())
                self.instances[process] = (True, display, message_queue)
                process.start()
                log("ProxyInstanceProcess started")
                popen = process._popen
                assert popen
                #when this process dies, run reap to update our list of proxy instances:
                self.child_reaper.add_process(popen, "xpra-proxy-%s" % display,
                                              "xpra-proxy-instance", True, True, self.reap)
            except Exception as e:
                log("start_proxy_process() failed", exc_info=True)
                log.error("Error starting proxy instance process:")
                log.error(" %s", e)
                message_queue.put("error: %s" % e)
                message_queue.put("stop")
            finally:
                #now we can close our handle on the connection:
                log("handover complete: closing connection from proxy server")
                if client_conn:
                    client_conn.close()
                server_conn.close()
                log("sending socket-handover-complete")
                message_queue.put("socket-handover-complete")
        start_thread(start_proxy_process, "start_proxy(%s)" % client_proto)

    def start_new_session(self, username, _password, uid, gid, new_session_dict=None, displays=()):
        log("start_new_session%s", (username, "..", uid, gid, new_session_dict, displays))
        sns = typedict(new_session_dict or {})
        mode = sns.get("mode", "start")
        assert mode in ("start", "start-desktop", "shadow"), "invalid start-new-session mode '%s'" % mode
        display = sns.get("display")
        if display in displays:
            raise Exception("display %s is already active!" % display)
        log("starting new server subprocess: mode=%s, display=%s", mode, display)
        args = []
        if display:
            args = [display]
        #allow the client to override some options:
        opts = make_defaults_struct(username=username, uid=uid, gid=gid)
        for k,v in sns.items():
            k = bytestostr(k)
            if k in ("mode", "display"):
                continue    #those special attributes have been consumed already
            if k not in PROXY_START_OVERRIDABLE_OPTIONS:
                log.warn("Warning: ignoring invalid start override")
                log.warn(" %s=%s", k, v)
                continue
            try:
                vt = OPTION_TYPES[k]
                if vt==str:
                    v = bytestostr(v)
                elif vt==bool:
                    v = parse_bool(k, v)
                elif vt==int:
                    v = int(v)
                elif vt==list:
                    v = list(bytestostr(x) for x in v)
            except ValueError:
                log("start_new_session: override option %s", k, exc_info=True)
                log.warn("Warning: ignoring invalid value %s for %s (%s)", v, k, vt)
                continue
            if v is not None:
                fn = k.replace("-", "_")
                curr = getattr(opts, fn, None)
                if curr!=v:
                    log("start override: %24s=%-24s (default=%s)", k, v, curr)
                    setattr(opts, fn, v)
                else:
                    log("start override: %24s=%-24s (unchanged)", k, v)
            else:
                log("start override: %24s=%-24s (invalid, unchanged)", k, v)
        opts.attach = False
        opts.start_via_proxy = False
        env = self.get_proxy_env()
        cwd = None
        if uid>0:
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
            self.child_reaper.add_process(proc, "server-%s" % (display or socket_path), "xpra %s" % mode, True, True)
        log("start_new_session(..) pid=%s, socket_path=%s, display=%s, ", proc.pid, socket_path, display)
        return proc, socket_path, display

    def get_proxy_env(self):
        env = dict((k,v) for k,v in os.environ.items() if k in ENV_WHITELIST or "*" in ENV_WHITELIST)
        #env var to add to environment of subprocess:
        extra_env_str = os.environ.get("XPRA_PROXY_START_ENV", "")
        if extra_env_str:
            extra_env = {}
            for e in extra_env_str.split(os.path.pathsep):  #ie: "A=1:B=2"
                parts = e.split("=", 1)
                if len(parts)==2:
                    extra_env[parts[0]]= parts[1]
            log("extra_env(%s)=%s", extra_env_str, extra_env)
            env.update(extra_env)
        return env


    def reap(self, *args):
        log("reap%s", args)
        dead = []
        for instance in tuple(self.instances.keys()):
            #instance is a process
            if not instance.is_alive():
                dead.append(instance)
        log("reap%s dead processes: %s", args, dead or None)
        for p in dead:
            del self.instances[p]


    def get_info(self, proto, *_args):
        info = ServerCore.get_server_info(self)
        info.setdefault("server", {})["type"] = "Python/GLib/proxy"
        #only show more info if we have authenticated
        #as the user running the proxy server process:
        if proto and proto.authenticators:
            sessions = []
            for authenticator in proto.authenticators:
                auth_sessions = authenticator.get_sessions()
                if auth_sessions:
                    sessions = auth_sessions
                    break
            if sessions:
                uid, gid = sessions[:2]
                if not POSIX or (uid==getuid() and gid==getgid()):
                    self.reap()
                    i = 0
                    instances = dict(self.instances)
                    instances_info = {}
                    for proxy_instance, v in instances.items():
                        isprocess, d, _ = v
                        iinfo = {
                            "display"    : d,
                            "live"       : proxy_instance.is_alive(),
                            }
                        if isprocess:
                            iinfo.update({
                                "pid"        : proxy_instance.pid,
                                })
                        else:
                            iinfo.update(proxy_instance.get_info())
                        instances_info[i] = iinfo
                        i += 1
                    info["instances"] = instances_info
                    info["proxies"] = len(instances)
        return info
