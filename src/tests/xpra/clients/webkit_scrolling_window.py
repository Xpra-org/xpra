#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os
import socket
import gobject
import gtk
gobject.threads_init()

from browser import WebBrowser, vscroll_listeners, hscroll_listeners

from xpra.log import Logger
log = Logger()

from xpra.platform.dotxpra import DotXpra
from xpra.client.gobject_client_base import CommandConnectClient
from xpra.net.bytestreams import SocketConnection
from collections import deque


class gobject_loop_adapter(object):

    def quit(self):
        gtk.main_quit()

    def run(self):
        gtk.main()


class ServerMessenger(CommandConnectClient):

    def client_type(self):
        return "XpraBrowser"

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
        log("sending ping echo")

    def _process_hello(self, packet):
        hello = packet[1]
        log.info("got hello back from the server: %s", hello)
        self._packet_handlers["ping"] = self._process_ping
        #disable min quality:
        self.send("command_request", "min-quality", -1, "*")


class XpraBrowser(object):
    """
        Uses the webkit browser events and a ServerMessenger
        to help xpra tune its encoding settings.
    """

    def __init__(self):
        dotxpra = DotXpra()
        display = os.environ.get("DISPLAY")
        from xpra.scripts.config import make_defaults_struct
        opts = make_defaults_struct()
        target = dotxpra.socket_path(display)
        log.info("attempting to connect to socket: %s", target)
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(target)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), target, "scroll-test")
        log.info("successfully created our socket connection: %s", conn)
        self.server = ServerMessenger(conn, opts)

        self.vscroll_events = deque(maxlen=1000)
        self.hscroll_events = deque(maxlen=1000)

        browser = WebBrowser()
        #hook some events:
        browser.content_tabs.connect("focus-view-title-changed", self.title_changed)
        vscroll_listeners.append(self.vscroll)
        hscroll_listeners.append(self.hscroll)
        #the things we tune:
        self.quality = -1
        self.speed = -1
        self.encoding = None
        self.strict = False

    def title_changed(self, tabbed_pane, frame, title):
        if not title:
            title = frame.get_uri() or ""
        log.info("setting session title=%s", title)
        self.server.send("command_request", "name", title)

    def update_settings(self, encoding, strict, quality, speed):
        self.encoding = encoding
        self.strict = strict
        self.quality = quality
        self.speed = speed
        self.send_settings()

    def send_settings(self):
        self.server.send("command_request", "encoding", self.encoding, ["nostrict", "strict"][int(self.strict)])
        self.server.send("command_request", "quality", self.quality, "*")
        self.server.send("command_request", "speed", self.speed, "*")

    def may_reset_quality(self):
        t = [0]
        if len(self.vscroll_events)>0:
            #add last vscroll event time:
            t.append(self.vscroll_events[-1][0])
        if len(self.hscroll_events)>0:
            #add last hscroll event time:
            t.append(self.hscroll_events[-1][0])
        last_event_time = max(t)
        elapsed = time.time()-last_event_time
        if elapsed>1:
            log.info("no events for %.1fs, resetting encoding", elapsed)
            self.update_settings("h264", False, -1, -1)

    def vscroll(self, scrollbar, scrolltype, value):
        #print("vscroll(%s) n=%s" % ((scrollbar, scrolltype, value), len(vscroll_events)))
        now = time.time()
        if len(self.vscroll_events)==0:
            self.vscroll_events.append((now, value))
            return
        #get the previous event
        t, _ = self.vscroll_events[-1]
        #print("last vscroll event was %sms ago" % (now-t))
        if now-t<1:
            #very rough cut: last event was less than a second ago, use low quality!
            if self.quality!=1:
                log.info("more than one scroll event per second: lowering quality")
                self.update_settings("jpeg", True, 1, 100)
            gobject.timeout_add(1000, self.may_reset_quality)
        self.vscroll_events.append((now, value))

    def hscroll(self, scrollbar, scrolltype, value):
        #we don't do anything with hscroll yet, just record it:
        #print("hscroll(%s)" % (scrollbar, scrolltype, value))
        self.hscroll_events.append((time.time(), value))

    def run(self):
        #this will run the gtk main loop:
        try:
            self.server.run()
        finally:
            self.server.cleanup()

def main():
    XpraBrowser().run()


if __name__ == "__main__":
    main()
