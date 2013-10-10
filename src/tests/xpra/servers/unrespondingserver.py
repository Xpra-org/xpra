#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import gobject
gobject.threads_init()

from xpra.log import Logger
log = Logger()

from xpra.server.server_core import ServerCore

class UnrespondingServer(ServerCore):

    def __init__(self):
        ServerCore.__init__(self)
        self.main_loop = None
        self.idle_add = gobject.idle_add
        self.timeout_add = gobject.timeout_add
        self.source_remove = gobject.source_remove

    def do_run(self):
        self.main_loop = gobject.MainLoop()
        self.main_loop.run()

    def do_quit(self):
        self.main_loop.quit()

    def add_listen_socket(self, socktype, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def send_version_info(self, proto):
        #we just ignore it!
        pass

    def send_hello_info(self, proto):
        #we just ignore it!
        pass

    def verify_connection_accepted(self, protocol):
        #we just ignore it!
        pass

    def verify_client_has_timedout(self, protocol):
        if protocol._closed:
            return
        log.error("ERROR: client connection %s is still open, client has failed to time out!", protocol)

    def hello_oked(self, proto, packet, c, auth_caps):
        log.info("client should be accepted - but we'll just ignore it!")
        gobject.timeout_add(10*1000, self.verify_client_has_timedout, proto)


def main():
    print("main()")
    import gtk
    import signal
    from xpra.scripts.server import setup_local_socket, start_Xvfb, check_xvfb_process
    from xpra.scripts.main import parse_cmdline, configure_logging
    from xpra.dotxpra import DotXpra
    script_file = sys.argv[0]
    print("main() script_file=%s" % script_file)
    cmdline = sys.argv
    print("main() cmdline=%s" % cmdline)
    parser, opts, args, mode = parse_cmdline(cmdline)
    print("main() parser=%s" % parser)
    print("main() options=%s" % opts)
    print("main() mode=%s" % mode)
    display_name = args.pop(0)
    print("main() display=%s" % display_name)
    assert mode=="start", "only start mode is supported by this test server"
    configure_logging(opts, mode)
    dotxpra = DotXpra(opts.socket_dir)
    socket, cleanup_socket = setup_local_socket(dotxpra, display_name, False, opts.mmap_group)
    sockets = [socket]
    xvfb = start_Xvfb(opts.xvfb, display_name)
    assert check_xvfb_process(xvfb), "xvfb error"

    from xpra.x11.gtk_x11 import gdk_display_source
    assert gdk_display_source

    from xpra.x11.bindings.window_bindings import X11WindowBindings     #@UnresolvedImport
    X11Window = X11WindowBindings()
    assert X11Window

    try:
        app = UnrespondingServer()
        app.init(opts)
        app.init_sockets(sockets)
        signal.signal(signal.SIGTERM, app.signal_quit)
        signal.signal(signal.SIGINT, app.signal_quit)
        return app.run()
    finally:
        for display in gtk.gdk.display_manager_get().list_displays():
            display.close()
        xvfb.terminate()
        cleanup_socket()


if __name__ == "__main__":
    main()
