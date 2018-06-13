# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.gtk_common.gobject_compat import import_glib, import_gobject
glib = import_glib()
try:
    glib.threads_init()
except AttributeError:
    import_gobject().threads_init()
from multiprocessing import Queue as MQueue, freeze_support
freeze_support()

from xpra.log import Logger
log = Logger("proxy")
authlog = Logger("proxy", "auth")


from xpra.util import LOGIN_TIMEOUT, AUTHENTICATION_ERROR, PERMISSION_ERROR, SESSION_NOT_FOUND, SERVER_ERROR, repr_ellipsized, print_nested_dict, csv, envbool, typedict
from xpra.os_util import get_username_for_uid, get_groups
from xpra.server.proxy.proxy_instance_process import ProxyInstanceProcess
from xpra.server.server_core import ServerCore
from xpra.server.control_command import ArgsControlCommand, ControlError
from xpra.child_reaper import getChildReaper
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import parse_display_name, connect_to, start_server_subprocess
from xpra.make_thread import start_thread


PROXY_SOCKET_TIMEOUT = float(os.environ.get("XPRA_PROXY_SOCKET_TIMEOUT", "0.1"))
PROXY_WS_TIMEOUT = float(os.environ.get("XPRA_PROXY_WS_TIMEOUT", "1.0"))
assert PROXY_SOCKET_TIMEOUT>0, "invalid proxy socket timeout"
CAN_STOP_PROXY = envbool("XPRA_CAN_STOP_PROXY", False)


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
        self.control_commands["stop"] = ArgsControlCommand("stop", "stops the proxy instance on the given display", self.handle_stop_command, min_args=1, max_args=1)

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

    def init_components(self, opts):
        pass

    def init_packet_handlers(self):
        ServerCore.init_packet_handlers(self)
        #add shutdown handler
        self._default_packet_handlers["shutdown-server"] = self._process_proxy_shutdown_server

    def _process_proxy_shutdown_server(self, proto, packet):
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

    def add_listen_socket(self, socktype, sock):
        sock.listen(5)
        glib.io_add_watch(sock, glib.IO_IN, self._new_connection, sock)
        self.socket_types[sock] = socktype

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
        if any(c.boolget("%s_request" % x) for x in ("screenshot", "event", "print", "exit")):
            self.send_disconnect(proto, "invalid request")
            return
        if c.boolget("stop_request"):
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
        else:
            self.start_proxy(proto, c, auth_caps)

    def start_proxy(self, client_proto, c, auth_caps):
        def disconnect(reason, *extras):
            log("disconnect(%s, %s)", reason, extras)
            self.send_disconnect(client_proto, reason, *extras)

        #find the target server session:
        if not client_proto.authenticator:
            log.error("Error: the proxy server requires an authentication mode,")
            try:
                log.error(" client connection '%s' does not specify one", client_proto._conn.socktype)
            except:
                pass
            log.error(" use 'none' to disable authentication")
            disconnect(SESSION_NOT_FOUND, "no sessions found")
            return
        try:
            sessions = client_proto.authenticator.get_sessions()
        except Exception as e:
            authlog("failed to get the list of sessions", exc_info=True)
            authlog.error("Error: failed to get the list of sessions using '%s' authenticator", client_proto.authenticator)
            authlog.error(" %s", e)
            disconnect(AUTHENTICATION_ERROR, "cannot access sessions")
            return
        authlog("start_proxy(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        if sessions is None:
            disconnect(SESSION_NOT_FOUND, "no sessions found")
            return
        uid, gid, displays, env_options, session_options = sessions
        if os.name=="posix":
            if uid==0 or gid==0:
                log.error("Error: proxy instances should not run as root")
                log.error(" use a different uid and gid (ie: nobody)")
                disconnect(AUTHENTICATION_ERROR, "cannot run proxy instances as root")
                return
            username = get_username_for_uid(uid)
            groups = get_groups(username)
            if "xpra" not in groups:
                log("user '%s' (uid=%i) is not in the xpra group", username, uid)
                log(" it belongs to: %s", csv(groups) or None)
        #ensure we don't loop back to the proxy:
        proxy_virtual_display = os.environ.get("DISPLAY")
        if proxy_virtual_display in displays:
            displays.remove(proxy_virtual_display)
        #remove proxy instance virtual displays:
        displays = [x for x in displays if not x.startswith(":proxy-")]
        #log("unused options: %s, %s", env_options, session_options)
        opts = make_defaults_struct()
        display = None
        proc = None
        sns = c.dictget("start-new-session")
        authlog("start_proxy: displays=%s, start-new-session=%s", displays, bool(sns))
        if len(displays)==0 or sns:
            if self._start_sessions:
                #start a new session
                mode = sns.get("mode", "start")
                assert mode in ("start", "start-desktop", "shadow"), "invalid start-new-session mode '%s'" % mode
                sns = typedict(sns)
                display = sns.get("display")
                args = []
                if display:
                    args = [display]
                start = sns.strlistget("start")
                start_child = sns.strlistget("start-child")
                exit_with_children = sns.boolget("exit-with-children")
                exit_with_client = sns.boolget("exit-with-client")
                log("starting new server subprocess: mode=%s, socket-dir=%s, socket-dirs=%s, start=%s, start-child=%s, exit-with-children=%s, exit-with-client=%s, uid=%s, gid=%s",
                    mode, opts.socket_dir, opts.socket_dirs, start, start_child, exit_with_children, exit_with_client, uid, gid)
                try:
                    proc, socket_path = start_server_subprocess(sys.argv[0], args, mode, opts,
                                                                opts.socket_dir, opts.socket_dirs,
                                                                start, start_child,
                                                                exit_with_children, exit_with_client,
                                                                uid=uid, gid=gid)
                    display = "socket:%s" % socket_path
                except Exception as e:
                    log("start_server_subprocess failed", exc_info=True)
                    log.error("Error: failed to start server subprocess:")
                    log.error(" %s", e)
                    disconnect(SERVER_ERROR, "failed to start a new session")
                    return
                if proc:
                    self.child_reaper.add_process(proc, "server-%s" % display, "xpra start", True, True)
            else:
                disconnect(SESSION_NOT_FOUND, "no displays found")
                return
        if display is None:
            display = c.strget("display")
            authlog("start_proxy: proxy-virtual-display=%s (ignored), user specified display=%s, found displays=%s", proxy_virtual_display, display, displays)
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

        def stop_server_subprocess():
            if proc:
                proc.terminate()

        log("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)
        def parse_error(*args):
            stop_server_subprocess()
            disconnect(SESSION_NOT_FOUND, "invalid display string")
            log.warn("Error: parsing failed for display string '%s':", display)
            for arg in args:
                log.warn(" %s", arg)
            raise Exception("parse error on %s: %s" % (display, args))
        opts.username = client_proto.authenticator.username
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
            log.error(" %s", e)
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
                encryption_key = self.get_encryption_key(client_proto.authenticator, client_proto.keyfile)
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


    def get_info(self, proto, *args):
        info = ServerCore.get_info(self, proto)
        info.setdefault("server", {})["type"] = "Python/GLib/proxy"
        #only show more info if we have authenticated
        #as the user running the proxy server process:
        pa = proto.authenticator
        if pa:
            sessions = pa.get_sessions()
            if sessions:
                uid, gid = sessions[:2]
                if os.name!="posix" or (uid==os.getuid() and gid==os.getgid()):
                    info.update(ServerCore.get_info(self, proto))
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
