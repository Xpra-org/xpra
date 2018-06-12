# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.gtk_common.gobject_compat import import_glib, import_gobject
glib = import_glib()
glib.threads_init()
gobject = import_gobject()
gobject.threads_init()
from multiprocessing import Queue as MQueue, freeze_support #@UnresolvedImport
freeze_support()

from xpra.log import Logger
log = Logger("proxy")
authlog = Logger("proxy", "auth")


from xpra.util import LOGIN_TIMEOUT, AUTHENTICATION_ERROR, SESSION_NOT_FOUND, SERVER_ERROR, repr_ellipsized, print_nested_dict, csv, envfloat, envint, typedict
from xpra.os_util import get_username_for_uid, get_groups, get_home_for_uid, bytestostr, getuid, getgid, WIN32, POSIX
from xpra.server.proxy.proxy_instance_process import ProxyInstanceProcess
from xpra.server.server_core import ServerCore
from xpra.server.control_command import ArgsControlCommand, ControlError
from xpra.child_reaper import getChildReaper
from xpra.scripts.config import make_defaults_struct, PROXY_START_OVERRIDABLE_OPTIONS
from xpra.scripts.main import parse_display_name, connect_to, start_server_subprocess
from xpra.make_thread import start_thread


PROXY_SOCKET_TIMEOUT = envfloat("XPRA_PROXY_SOCKET_TIMEOUT", "0.1")
PROXY_WS_TIMEOUT = envfloat("XPRA_PROXY_WS_TIMEOUT", "1.0")
assert PROXY_SOCKET_TIMEOUT>0, "invalid proxy socket timeout"
CAN_STOP_PROXY = envint("XPRA_CAN_STOP_PROXY", False)


MAX_CONCURRENT_CONNECTIONS = 200


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
        #keep track of the proxy process instances
        #the display they're on and the message queue we can
        # use to communicate with them
        self.processes = {}
        #connections used exclusively for requests:
        self._requests = set()
        self.idle_add = glib.idle_add
        self.timeout_add = glib.timeout_add
        self.source_remove = glib.source_remove
        self._socket_timeout = PROXY_SOCKET_TIMEOUT
        self._ws_timeout = PROXY_WS_TIMEOUT

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        self.video_encoders = opts.proxy_video_encoders
        self.csc_modules = opts.csc_modules
        self._start_sessions = opts.proxy_start_sessions
        ServerCore.init(self, opts)
        #ensure we cache the platform info before intercepting SIGCHLD
        #as this will cause a fork and SIGCHLD to be emitted:
        from xpra.version_util import get_platform_info
        get_platform_info()
        self.child_reaper = getChildReaper()

    def init_control_commands(self):
        ServerCore.init_control_commands(self)
        self.control_commands["stop"] = ArgsControlCommand("stop", "stops the proxy instance on the given display", self.handle_stop_command, min_args=1, max_args=1)


    def make_dbus_server(self):
        from xpra.server.proxy.proxy_dbus_server import Proxy_DBUS_Server
        return Proxy_DBUS_Server(self)


    def init_packet_handlers(self):
        ServerCore.init_packet_handlers(self)
        #add shutdown handler
        self._default_packet_handlers["shutdown-server"] = self._process_proxy_shutdown_server

    def _process_proxy_shutdown_server(self, proto, _packet):
        assert proto in self._requests
        self.quit(False)


    def print_screen_info(self):
        #no screen, we just use a virtual display number
        pass

    def get_server_mode(self):
        return "proxy"

    def init_aliases(self):
        pass

    def do_run(self):
        self.main_loop = glib.MainLoop()
        self.main_loop.run()

    def handle_stop_command(self, *args):
        display = args[0]
        log("stop command: will try to find proxy process for display %s", display)
        for process, v in self.processes.items():
            disp,mq = v
            if disp==display:
                pid = process.pid
                log.info("stop command: found process %s with pid %i for display %s", process, pid, display)
                log.info(" forwarding the 'stop' request")
                mq.put("stop")
                return "stopped proxy process with pid %s" % pid
        raise ControlError("no proxy found for display %s" % display)


    def stop_all_proxies(self):
        processes = self.processes
        self.processes = {}
        log("stop_all_proxies() will stop proxy processes: %s", processes)
        for process, v in processes.items():
            if not process.is_alive():
                continue
            disp,mq = v
            log("stop_all_proxies() stopping process %s for display %s", process, disp)
            mq.put("stop")
        log("stop_all_proxies() done")

    def cleanup(self):
        self.stop_all_proxies()
        ServerCore.cleanup(self)

    def do_quit(self):
        self.main_loop.quit()
        log.info("Proxy Server process ended")


    def verify_connection_accepted(self, protocol):
        #if we start a proxy, the protocol will be closed
        #(a new one is created in the proxy process)
        if not protocol._closed:
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def hello_oked(self, proto, packet, c, auth_caps):
        if ServerCore.hello_oked(self, proto, packet, c, auth_caps):
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
            if not CAN_STOP_PROXY:
                self.send_disconnect(proto, "cannot stop proxy server")
                return
            self._requests.add(proto)
            #send a hello back and the client should then send its "shutdown-server" packet
            capabilities = self.make_hello()
            proto.send_now(("hello", capabilities))
            def force_exit_request_client():
                try:
                    self._requests.remove(proto)
                except:
                    pass
                if not proto._closed:
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
                log.error(" client connection '%s' does not specify one", client_proto._conn.socktype)
            except:
                pass
            log.error(" use 'none' to disable authentication")
            disconnect(SESSION_NOT_FOUND, "no sessions found")
            return
        sessions = None
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
            groups = get_groups(username)
            log("username(%i)=%s, groups=%s", uid, username, groups)
        else:
            #the auth module recorded the username we authenticate against
            assert client_proto.authenticators
            for authenticator in client_proto.authenticators:
                username = getattr(authenticator, "username", "")
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
        sns = c.dictget("start-new-session")
        authlog("proxy_session: displays=%s, start_sessions=%s, start-new-session=%s", displays, self._start_sessions, sns)
        if len(displays)==0 or sns:
            if not self._start_sessions:
                disconnect(SESSION_NOT_FOUND, "no displays found")
                return
            try:
                proc, socket_path, display = self.start_new_session(username, uid, gid, sns, displays)
                log("start_new_session%s=%s", (username, uid, gid, sns, displays), (proc, socket_path, display))
            except Exception as e:
                log("start_server_subprocess failed", exc_info=True)
                log.error("Error: failed to start server subprocess:")
                log.error(" %s", e)
                disconnect(SERVER_ERROR, "failed to start a new session")
                return
        if display is None:
            display = c.strget("display")
            authlog("proxy_session: proxy-virtual-display=%s (ignored), user specified display=%s, found displays=%s", proxy_virtual_display, display, displays)
            if display==proxy_virtual_display:
                disconnect(SESSION_NOT_FOUND, "invalid display")
                return
            if display:
                if display not in displays:
                    disconnect(SESSION_NOT_FOUND, "display '%s' not found" % display)
                    return
            else:
                if len(displays)!=1:
                    disconnect(SESSION_NOT_FOUND, "please specify a display, more than one is available: %s" % csv(displays))
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
            mode = sns.get("mode")
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

        #no other packets should be arriving until the proxy instance responds to the initial hello packet
        def unexpected_packet(packet):
            if packet:
                log.warn("Warning: received an unexpected packet on the proxy connection %s:", client_proto)
                log.warn(" %s", repr_ellipsized(packet))
        client_conn = client_proto.steal_connection(unexpected_packet)
        client_state = client_proto.save_state()
        cipher = None
        encryption_key = None
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                encryption_key = self.get_encryption_key(client_proto.authenticators, client_proto.keyfile)
        log("start_proxy(..) client connection=%s", client_conn)
        log("start_proxy(..) client state=%s", client_state)

        #this may block, so run it in a thread:
        def do_start_proxy():
            log("do_start_proxy()")
            message_queue = MQueue()
            try:
                ioe = client_proto.wait_for_io_threads_exit(5+self._socket_timeout)
                if not ioe:
                    log.error("Error: some network IO threads have failed to terminate")
                    return
                client_conn.set_active(True)
                process = ProxyInstanceProcess(uid, gid, env_options, session_options, self._socket_dir,
                                               self.video_encoders, self.csc_modules,
                                               client_conn, client_state, cipher, encryption_key, server_conn, c, message_queue)
                log("starting %s from pid=%s", process, os.getpid())
                self.processes[process] = (display, message_queue)
                process.start()
                log("process started")
                popen = process._popen
                assert popen
                #when this process dies, run reap to update our list of proxy processes:
                self.child_reaper.add_process(popen, "xpra-proxy-%s" % display, "xpra-proxy-instance", True, True, self.reap)
            finally:
                #now we can close our handle on the connection:
                client_conn.close()
                server_conn.close()
                message_queue.put("socket-handover-complete")
        start_thread(do_start_proxy, "start_proxy(%s)" % client_conn)

    def start_new_session(self, username, uid, gid, new_session_dict={}, displays=()):
        log("start_new_session%s", (username, uid, gid, new_session_dict, displays))
        sns = typedict(new_session_dict)
        if WIN32:
            return self.start_win32_shadow(username, new_session_dict)
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
            log("start override: %s=%s", k, v)
            if v is not None:
                fn = k.replace("-", "_")
                setattr(opts, fn, v)
        opts.attach = False
        opts.start_via_proxy = False
        env = self.get_proxy_env()
        cwd = None
        if uid>0:
            cwd = get_home_for_uid(uid) or None
        log("starting new server subprocess: options=%s", opts)
        log("env=%s", env)
        log("args=%s", args)
        log("cwd=%s", cwd)
        proc, socket_path, display = start_server_subprocess(sys.argv[0], args, mode, opts, username, uid, gid, env, cwd)
        if proc:
            self.child_reaper.add_process(proc, "server-%s" % (display or socket_path), "xpra %s" % mode, True, True)
        log("start_new_session(..) pid=%s, socket_path=%s, display=%s, ", proc.pid, socket_path, display)
        return proc, socket_path, display

    def get_proxy_env(self):
        ENV_WHITELIST = ["LANG", "HOSTNAME", "PWD", "TERM", "SHELL", "SHLVL", "PATH"]
        env = dict((k,v) for k,v in os.environ.items() if k in ENV_WHITELIST)
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


    def start_win32_shadow(self, username, new_session_dict):
        log("start_win32_shadow%s", (username, new_session_dict))
        from xpra.platform.paths import get_app_dir
        from xpra.platform.win32.lsa_logon_lib import logon_msv1_s4u
        logon_info = logon_msv1_s4u(username)
        log("logon_msv1_s4u(%s)=%s", username, logon_info)
        #hwinstaold = set_window_station("winsta0")
        def exec_command(command):
            log("exec_command(%s)", command)
            from xpra.platform.win32.create_process_lib import Popen, CREATIONINFO, CREATION_TYPE_TOKEN, LOGON_WITH_PROFILE, CREATE_NEW_PROCESS_GROUP, STARTUPINFO
            creation_info = CREATIONINFO()
            creation_info.dwCreationType = CREATION_TYPE_TOKEN
            creation_info.dwLogonFlags = LOGON_WITH_PROFILE
            creation_info.dwCreationFlags = CREATE_NEW_PROCESS_GROUP
            creation_info.hToken = logon_info.Token
            log("creation_info=%s", creation_info)
            startupinfo = STARTUPINFO()
            startupinfo.lpDesktop = "WinSta0\\Default"
            startupinfo.lpTitle = "Xpra-Shadow"
            cwd = get_app_dir()
            from subprocess import PIPE
            env = self.get_proxy_env()
            log("env=%s", env)
            proc = Popen(command, stdout=PIPE, stderr=PIPE, cwd=cwd, env=env, startupinfo=startupinfo, creationinfo=creation_info)
            log("Popen(%s)=%s", command, proc)
            log("poll()=%s", proc.poll())
            try:
                log("stdout=%s", proc.stdout.read())
                log("stderr=%s", proc.stderr.read())
            except:
                pass
            if proc.poll() is not None:
                return None
            self.child_reaper.add_process(proc, "server-%s" % username, "xpra shadow", True, True)
            return proc
        #whoami = os.path.join(get_app_dir(), "whoami.exe")
        #exec_command([whoami])
        port = 10000
        xpra_command = os.path.join(get_app_dir(), "xpra.exe")
        command = [xpra_command, "shadow", "--bind-tcp=0.0.0.0:%i" % port, "-d", "win32"]
        proc = exec_command(command)
        if not proc:
            return None, None
        #exec_command(["C:\\Windows\notepad.exe"])
        return "tcp/localhost:%i" % port, proc

    def reap(self, *args):
        log("reap%s", args)
        dead = []
        for p in self.processes.keys():
            live = p.is_alive()
            if not live:
                dead.append(p)
        log("reap%s dead processes: %s", args, dead or None)
        for p in dead:
            del self.processes[p]


    def get_info(self, proto, *_args):
        info = ServerCore.get_info(self, proto)
        info.setdefault("server", {})["type"] = "Python/GLib/proxy"
        #only show more info if we have authenticated
        #as the user running the proxy server process:
        if proto and proto.authenticators:
            sessions = []
            for authenticator in proto.authenticators:
                auth_sessions = authenticator.get_sessions()
                #don't add duplicates:
                for x in auth_sessions:
                    if x not in sessions:
                        sessions.append(x)
            if sessions:
                uid, gid = sessions[:2]
                if not POSIX or (uid==os.getuid() and gid==os.getgid()):
                    self.reap()
                    i = 0
                    for p,v in self.processes.items():
                        d,_ = v
                        info[i] = {
                                   "display"    : d,
                                   "live"       : p.is_alive(),
                                   "pid"        : p.pid,
                                   }
                        i += 1
                    info["proxies"] = len(self.processes)
        return info
