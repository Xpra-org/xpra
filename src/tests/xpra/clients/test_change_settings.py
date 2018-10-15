#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.log import Logger
log = Logger()

from xpra.client.gobject_client_base import CommandConnectClient


class TestChangeSettings(CommandConnectClient):
    """
        Change encoding settings using "control" packets
    """

    def verify_connected(self):
        pass

    def timeout(self, *args):
        log.info("ignoring timeout")

    def send_from_queue(self):
        x = self.queue[0]
        self.queue = self.queue[1:]
        log.info("sending %s", x)
        self.send(*x)
        if len(self.queue)>0:
            #run again
            return True
        self.quit(0)    #all done!

    def _process_ping(self, packet):
        time_to_echo = packet[1]
        #skip load average and latency:
        self.send("ping_echo", time_to_echo, 0, 0, 0, -1)
        log.info("sending ping echo")

    def do_command(self):
        self._packet_handlers["ping"] = self._process_ping
        self.queue = []
        for i in range(10):
            self.queue.append(("command_request", "auto-refresh", "%.4f" % (i/100)))
            for encoding in ("rgb", "png", "jpeg", "h264", "vp8", "webp"):
                self.queue.append(("command_request", "encoding", encoding, "strict"))
                self.queue.append(("command_request", "quality", "*", 1))
                self.queue.append(("command_request", "quality", "*", 100))
        #send one command every 2 seconds:
        gobject.timeout_add(2*1000, self.send_from_queue)

def main():
    import sys
    from tests.xpra.clients.test_DoS_client import test_DoS
    test_DoS(TestChangeSettings, sys.argv)


if __name__ == "__main__":
    main()
