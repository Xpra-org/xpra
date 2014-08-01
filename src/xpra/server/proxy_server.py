# This file is part of Xpra.
# Copyright (C) 2013-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import gobject
gobject.threads_init()
from multiprocessing import Queue as MQueue, freeze_support
freeze_support()

from xpra.log import Logger
log = Logger("proxy")


from xpra.util import LOGIN_TIMEOUT, AUTHENTICATION_ERROR, SESSION_NOT_FOUND
from xpra.server.proxy_instance_process import ProxyInstanceProcess
from xpra.server.server_core import ServerCore
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import parse_display_name, connect_to
from xpra.daemon_thread import make_daemon_thread


PROXY_SOCKET_TIMEOUT = float(os.environ.get("XPRA_PROXY_SOCKET_TIMEOUT", "0.1"))
assert PROXY_SOCKET_TIMEOUT>0, "invalid proxy socket timeout"


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
        self.main_loop = None
        #keep track of the proxy process instances
        #the display they're on and the message queue we can
        # use to communicate with them
        self.processes = {}
        self.idle_add = gobject.idle_add
        self.timeout_add = gobject.timeout_add
        self.source_remove = gobject.source_remove
        self._socket_timeout = PROXY_SOCKET_TIMEOUT
        self._socket_dir = None
        self.control_commands = ["hello", "stop"]
        #ensure we cache the platform info before intercepting SIGCHLD
        #as this will cause a fork and SIGCHLD to be emitted:
        from xpra.version_util import get_platform_info
        get_platform_info()
        signal.signal(signal.SIGCHLD, self.sigchld)

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        if not opts.auth:
            raise Exception("The proxy server requires an authentication mode (use 'none' to disable authentication)")
        self._socket_dir = opts.socket_dir
        self.video_encoders = opts.video_encoders
        self.csc_modules = opts.csc_modules
        ServerCore.init(self, opts)

    def get_server_mode(self):
        return "proxy"

    def init_aliases(self):
        pass

    def do_run(self):
        self.main_loop = gobject.MainLoop()
        self.main_loop.run()

    def do_handle_command_request(self, command, args):
        assert command=="stop"
        if len(args)!=1:
            return 4, "invalid number of arguments, usage: 'xpra control stop DISPLAY'"
        display = args[0]
        log("stop command: will try to find proxy process for display %s", display)
        for process, v in list(self.processes.items()):
            disp,mq = v
            if disp==display:
                pid = process.pid
                log.info("stop command: found process %s with pid %s for display %s, sending it 'stop' request", process, pid, display)
                mq.put("stop")
                return 0, "stopped proxy process with pid %s" % pid
        return 14, "no proxy found for display %s" % display


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
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)
        self.socket_types[sock] = socktype

    def verify_connection_accepted(self, protocol):
        #if we start a proxy, the protocol will be closed
        #(a new one is created in the proxy process)
        if not protocol._closed:
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def hello_oked(self, proto, packet, c, auth_caps):
        if c.boolget("stop_request"):
            self.clean_quit()
            return
        self.accept_client(proto, c)
        self.start_proxy(proto, c, auth_caps)

    def start_proxy(self, client_proto, c, auth_caps):
        assert client_proto.authenticator is not None
        #find the target server session:
        def disconnect(reason, *extras):
            self.send_disconnect(client_proto, reason, *extras)
        try:
            sessions = client_proto.authenticator.get_sessions()
        except Exception, e:
            log.error("failed to get the list of sessions: %s", e)
            disconnect(AUTHENTICATION_ERROR)
            return
        if sessions is None:
            disconnect(SESSION_NOT_FOUND, "no sessions found")
            return
        log("start_proxy(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        uid, gid, displays, env_options, session_options = sessions
        #log("unused options: %s, %s", env_options, session_options)
        if len(displays)==0:
            disconnect(SESSION_NOT_FOUND, "no displays found")
            return
        display = c.strget("display")
        proxy_virtual_display = os.environ.get("DISPLAY")
        #ensure we don't loop back to the proxy:
        if proxy_virtual_display in displays:
            displays.remove(proxy_virtual_display)
        if display==proxy_virtual_display:
            disconnect(SESSION_NOT_FOUND, "invalid display")
            return
        if display:
            if display not in displays:
                disconnect(SESSION_NOT_FOUND, "display not found")
                return
        else:
            if len(displays)!=1:
                disconnect(SESSION_NOT_FOUND, "please specify a display (more than one available)")
                return
            display = displays[0]

        log("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)
        def parse_error(*args):
            disconnect(SESSION_NOT_FOUND, "invalid display string")
            log.warn("parse error on %s: %s", display, args)
            raise Exception("parse error on %s: %s" % (display, args))
        opts = make_defaults_struct()
        opts.username = client_proto.authenticator.username
        disp_desc = parse_display_name(parse_error, opts, display)
        log("display description(%s) = %s", display, disp_desc)
        try:
            server_conn = connect_to(disp_desc)
        except Exception, e:
            log.error("cannot start proxy connection to %s: %s", disp_desc, e, exc_info=True)
            disconnect(SESSION_NOT_FOUND, "failed to connect to display")
            return
        log("server connection=%s", server_conn)

        client_conn = client_proto.steal_connection()
        client_state = client_proto.save_state()
        cipher = None
        encryption_key = None
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                encryption_key = self.get_encryption_key(client_proto.authenticator)
        log("start_proxy(..) client connection=%s", client_conn)
        log("start_proxy(..) client state=%s", client_state)

        #this may block, so run it in a thread:
        def do_start_proxy():
            log("do_start_proxy()")
            try:
                #stop IO in proxy:
                #(it may take up to _socket_timeout until the thread exits)
                client_conn.set_active(False)
                ioe = client_proto.wait_for_io_threads_exit(0.1+self._socket_timeout)
                if not ioe:
                    log.error("IO threads have failed to terminate!")
                    return
                #now we can go back to using blocking sockets:
                self.set_socket_timeout(client_conn, None)
                client_conn.set_active(True)

                assert uid!=0 and gid!=0
                message_queue = MQueue()
                process = ProxyInstanceProcess(uid, gid, env_options, session_options, self._socket_dir,
                                               self.video_encoders, self.csc_modules,
                                               client_conn, client_state, cipher, encryption_key, server_conn, c, message_queue)
                log("starting %s from pid=%s", process, os.getpid())
                process.start()
                log("process started")
                #FIXME: remove processes that have terminated
                self.processes[process] = (display, message_queue)
            finally:
                #now we can close our handle on the connection:
                client_conn.close()
                server_conn.close()
        make_daemon_thread(do_start_proxy, "start_proxy(%s)" % client_conn).start()


    def reap(self):
        dead = []
        for p in self.processes.keys():
            live = p.is_alive()
            if not live:
                dead.append(p)
        for p in dead:
            del self.processes[p]

    def sigchld(self, *args):
        log("sigchld(%s)", args)
        self.idle_add(self.reap)
        log("processes: %s", self.processes)

    def get_info(self, proto, *args):
        info = {"server.type" : "Python/GObject/proxy"}
        #only show more info if we have authenticated
        #as the user running the proxy server process:
        sessions = proto.authenticator.get_sessions()
        if sessions:
            uid, gid = sessions[:2]
            if uid==os.getuid() and gid==os.getgid():
                info.update(ServerCore.get_info(self, proto))
                self.reap()
                i = 0
                for p,v in self.processes.items():
                    d,_ = v
                    info["proxy[%s].display" % i] = d
                    info["proxy[%s].live" % i] = p.is_alive()
                    info["proxy[%s].pid" % i] = p.pid
                    i += 1
                info["proxies"] = len(self.processes)
        return info
