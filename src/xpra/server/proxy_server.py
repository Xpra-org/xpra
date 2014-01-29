# This file is part of Xpra.
# Copyright (C) 2013-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import gobject
gobject.threads_init()
from multiprocessing import Queue as MQueue

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_PROXY_DEBUG")

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
        signal.signal(signal.SIGCHLD, self.sigchld)

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        if not opts.auth:
            raise Exception("The proxy server requires an authentication mode")
        ServerCore.init(self, opts)

    def get_server_mode(self):
        return "proxy"

    def init_aliases(self):
        pass

    def do_run(self):
        self.main_loop = gobject.MainLoop()
        self.main_loop.run()

    def stop_all_proxies(self):
        processes = self.processes
        self.processes = {}
        log("stop_all_proxies() will stop proxy processes: %s", processes)
        for process, v in processes.items():
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
            self.send_disconnect(protocol, "connection timeout")

    def hello_oked(self, proto, packet, c, auth_caps):
        if c.boolget("stop_request"):
            self.clean_quit()
            return
        self.accept_client(proto, c)
        self.start_proxy(proto, c, auth_caps)

    def start_proxy(self, client_proto, c, auth_caps):
        assert client_proto.authenticator is not None
        #find the target server session:
        def disconnect(msg):
            self.send_disconnect(client_proto, msg)
        sessions = client_proto.authenticator.get_sessions()
        if sessions is None:
            disconnect("no sessions found")
            return
        debug("start_proxy(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        uid, gid, displays, env_options, session_options = sessions
        #debug("unused options: %s, %s", env_options, session_options)
        if len(displays)==0:
            disconnect("no displays found")
            return
        display = c.strget("display")
        proxy_virtual_display = os.environ["DISPLAY"]
        #ensure we don't loop back to the proxy:
        if proxy_virtual_display in displays:
            displays.remove(proxy_virtual_display)
        if display==proxy_virtual_display:
            disconnect("invalid display")
            return
        if display:
            if display not in displays:
                disconnect("display not found")
                return
        else:
            if len(displays)!=1:
                disconnect("please specify a display (more than one available)")
                return
            display = displays[0]

        debug("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)
        def parse_error(*args):
            disconnect("invalid display string")
            log.warn("parse error on %s: %s", display, args)
            raise Exception("parse error on %s: %s" % (display, args))
        opts = make_defaults_struct()
        opts.username = c.strget("username")
        disp_desc = parse_display_name(parse_error, opts, display)
        debug("display description(%s) = %s", display, disp_desc)
        try:
            server_conn = connect_to(disp_desc)
        except Exception, e:
            log.error("cannot start proxy connection to %s: %s", disp_desc, e)
            disconnect("failed to connect to display")
            return
        debug("server connection=%s", server_conn)

        client_conn = client_proto.steal_connection()
        client_state = client_proto.save_state()
        cipher = None
        encryption_key = None
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                encryption_key = self.get_encryption_key(client_proto.authenticator)
        debug("start_proxy(..) client connection=%s", client_conn)
        debug("start_proxy(..) client state=%s", client_state)

        #this may block, so run it in a thread:
        def do_start_proxy():
            debug("do_start_proxy()")
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
                process = ProxyInstanceProcess(uid, gid, env_options, session_options, client_conn, client_state, cipher, encryption_key, server_conn, c, message_queue)
                debug("starting %s from pid=%s", process, os.getpid())
                process.start()
                debug("process started")
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
        log.info("sigchld(%s)", args)
        self.idle_add(self.reap)
        log.info("processes: %s", self.processes)

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
