#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import gtk

from xpra.log import Logger
log = Logger()

from xpra.client.gobject_client_base import CommandConnectClient
from collections import deque


class gobject_loop_adapter(object):

    def quit(self):
        gtk.main_quit()

    def run(self):
        gtk.main()


class ServerMessenger(CommandConnectClient):

    def run(self):
        self._protocol.start()
        #override so we can use the gtk main loop here:
        self.gobject_mainloop = gobject_loop_adapter()
        self.gobject_mainloop.run()
        return  self.exit_code

    def verify_connected(self):
        pass

    def timeout(self, *args):
        pass

    def _process_ping(self, packet):
        time_to_echo = packet[1]
        #skip load average and latency:
        self.send("ping_echo", time_to_echo, 0, 0, 0, -1)
        log.info("sending ping echo")

    def _process_hello(self, packet):
        hello = packet[1]
        log.info("got hello back: %s", hello)
        self._packet_handlers["ping"] = self._process_ping


class ScrolledWindowExample(gtk.Window):

    def __init__(self):
        gtk.Window.__init__(self)
        self.set_default_size(800, 600)

        button1 = gtk.Button("Button 1")
        button2 = gtk.Button("Button 2")

        layout = gtk.Layout()
        layout.set_size(800, 1200)
        layout.put(button1, 20, 20)
        layout.put(button2, 700, 350)

        vadjust = layout.get_vadjustment()
        hadjust = layout.get_hadjustment()

        self.vscroll = gtk.VScrollbar(vadjust)
        self.vscroll.connect("change-value", self.vscroll_changed)
        self.hscroll = gtk.HScrollbar(hadjust)
        self.hscroll.connect("change-value", self.hscroll_changed)

        table = gtk.Table(2, 2, False)
        table.attach(layout, 0, 1, 0, 1, gtk.FILL | gtk.EXPAND, gtk.FILL | gtk.EXPAND)
        table.attach(self.vscroll, 1, 2, 0, 1, gtk.FILL | gtk.SHRINK, gtk.FILL | gtk.SHRINK)
        table.attach(self.hscroll, 0, 1, 1, 2, gtk.FILL | gtk.SHRINK, gtk.FILL | gtk.SHRINK)

        self.add(table)
        self.show_all()
        self.connect("destroy", lambda w: gtk.main_quit())

    def vscroll_changed(self, *args):
        #print("vscroll_changed(%s)" % str(args))
        pass

    def hscroll_changed(self, *args):
        #print("hscroll_changed(%s)" % str(args))
        pass

def main():
    import time
    import sys
    assert len(sys.argv)==2, "usage: %s :DISPLAY" % sys.argv[0]
    display = sys.argv[1]

    from xpra.scripts.config import make_defaults_struct
    opts = make_defaults_struct()
    from xpra.platform.dotxpra import DotXpra
    target = DotXpra().socket_path(display)
    print("will attempt to connect to socket: %s" % target)

    import socket
    sock = socket.socket(socket.AF_UNIX)
    sock.connect(target)

    from xpra.net.bytestreams import SocketConnection
    conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), target, "scroll-test")
    print("socket connection=%s" % conn)

    app = ServerMessenger(conn, opts)
    window = ScrolledWindowExample()

    vscroll_events = deque(maxlen=1000)
    hscroll_events = deque(maxlen=1000)
    def vscroll(scrollbar, scrolltype, value):
        #print("vscroll(%s) n=%s" % ((scrollbar, scrolltype, value), len(vscroll_events)))
        now = time.time()
        needs_reset = False
        if len(vscroll_events)>0:
            #get the previous event
            t, _ = vscroll_events[-1]
            #print("last vscroll event was %sms ago" % (now-t))
            if now-t<1:
                #last event was less than a second ago
                print("lowering quality to jpeg @ 1%!")
                app.send("command_request", "encoding", "jpeg", "strict")
                app.send("command_request", "quality", 1, "*")
                app.send("command_request", "speed", 100, "*")
                needs_reset = True
        vscroll_events.append((now, value))
        if needs_reset:
            def may_reset_quality(*args):
                #if no new events since, reset quality:
                t, _ = vscroll_events[-1]
                if now==t:
                    print("resetting quality to h264")
                    app.send("command_request", "encoding", "h264", "nostrict")
                    app.send("command_request", "quality", -1, "*")     #means auto
                    app.send("command_request", "speed", -1, "*")       #means auto
            gobject.timeout_add(1000, may_reset_quality)
    def hscroll(scrollbar, scrolltype, value):
        print("hscroll(%s)" % (scrollbar, scrolltype, value))
        hscroll_events.append((time.time(), value))
    window.vscroll.connect("change-value", vscroll)
    window.hscroll.connect("change-value", hscroll)
    try:
        app.run()
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
