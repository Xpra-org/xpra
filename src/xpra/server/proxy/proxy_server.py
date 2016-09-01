# This file is part of Xpra.
# Copyright (C) 2013-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
from xpra.gtk_common.gobject_compat import import_glib
glib = import_glib()
try:
    glib.threads_init()
except AttributeError:
    pass
from multiprocessing import Queue as MQueue, freeze_support
freeze_support()

from xpra.log import Logger
log = Logger("proxy")


from xpra.scripts.config import InitException
from xpra.util import LOGIN_TIMEOUT, AUTHENTICATION_ERROR, SESSION_NOT_FOUND, repr_ellipsized, print_nested_dict
from xpra.server.proxy.proxy_instance_process import ProxyInstanceProcess
from xpra.server.server_core import ServerCore
from xpra.server.control_command import ArgsControlCommand, ControlError
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import parse_display_name, connect_to
from xpra.make_thread import start_thread


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
        self.idle_add = glib.idle_add
        self.timeout_add = glib.timeout_add
        self.source_remove = glib.source_remove
        self._socket_timeout = PROXY_SOCKET_TIMEOUT
        self.control_commands["stop"] = ArgsControlCommand("stop", "stops the proxy instance on the given display", self.handle_stop_command, min_args=1, max_args=1)

        #ensure we cache the platform info before intercepting SIGCHLD
        #as this will cause a fork and SIGCHLD to be emitted:
        from xpra.version_util import get_platform_info
        get_platform_info()
        signal.signal(signal.SIGCHLD, self.sigchld)

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        if not opts.tcp_auth:
            raise InitException("The proxy server requires an authentication mode (use 'none' to disable authentication)")
        self.video_encoders = opts.video_encoders
        self.csc_modules = opts.csc_modules
        ServerCore.init(self, opts)

    def init_components(self, opts):
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
                log.info("stop command: found process %s with pid %s for display %s, sending it 'stop' request", process, pid, display)
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
        except Exception as e:
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
            log.warn("Error: parsing failed for display string '%s':", display)
            for arg in args:
                log.warn(" %s", arg)
            raise Exception("parse error on %s: %s" % (display, args))
        opts = make_defaults_struct()
        opts.username = client_proto.authenticator.username
        disp_desc = parse_display_name(parse_error, opts, display)
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
            return
        log("server connection=%s", server_conn)

        #no other packets should be arriving until the proxy instance responds to the initial hello packet
        def unexpected_packet(packet):
            if packet:
                log.warn("received an unexpected packet on the proxy connection: %s", repr_ellipsized(packet))
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
                ioe = client_proto.wait_for_io_threads_exit(0.5+self._socket_timeout)
                if not ioe:
                    log.error("some network IO threads have failed to terminate!")
                    return
                client_conn.set_active(True)
                assert uid!=0 and gid!=0
                process = ProxyInstanceProcess(uid, gid, env_options, session_options, self._socket_dir,
                                               self.video_encoders, self.csc_modules,
                                               client_conn, client_state, cipher, encryption_key, server_conn, c, message_queue)
                log("starting %s from pid=%s", process, os.getpid())
                self.processes[process] = (display, message_queue)
                process.start()
                log("process started")
            finally:
                #now we can close our handle on the connection:
                client_conn.close()
                server_conn.close()
                message_queue.put("socket-handover-complete")
            #FIXME: remove processes that have terminated
        start_thread(do_start_proxy, "start_proxy(%s)" % client_conn)


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
        info = {"server.type" : "Python/GLib/proxy"}
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
                    info[i] = {"display"    : d,
                               "live"       : p.is_alive(),
                               "pid"        : p.pid}
                    i += 1
                info["proxies"] = len(self.processes)
        return info
