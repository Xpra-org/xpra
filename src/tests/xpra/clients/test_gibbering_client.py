#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.net.bencode import bencode
from xpra.log import Logger
log = Logger()

from xpra.client.gobject_client_base import CommandConnectClient

class TestGiberringCommandClient(CommandConnectClient):
    """
        Sending an illegal command should get us kicked out
    """

    def __init__(self, conn, opts):
        CommandConnectClient.__init__(self, conn, opts)
        def check_kicked_out(*args):
            if not self._protocol._closed:
                self.bug("illegal command did not get us kicked out: we are still connected!")
            else:
                self.quit()
        gobject.timeout_add(5*1000, check_kicked_out)

    def try_sending_again(self):
        self.send("irrelevant: should be kicked out already")

    def _queue_write(self, data):
        self._protocol._write_queue.put([(data, None, None)])

    def send_hello(self, challenge_response=None):
        CommandConnectClient.send_hello(self, challenge_response)
        self._queue_write("PS00000000000006l201234567890123456789")
        gobject.timeout_add(1000, self.try_sending_again)

    def bug(self, msg):
        log.warn("BUG: %s" % msg)
        CommandConnectClient.quit(self, -1)

    def quit(self, *args):
        log.info("OK: server correctly terminated the connection")
        CommandConnectClient.quit(self, 0)

class TestGiberringCommandClientNoPacketSize(TestGiberringCommandClient):
    def send_hello(self, challenge_response=None):
        hello = self.make_hello(challenge_response)
        self._queue_write(bencode(["hello", hello]))
        def send_gibberish():
            self._queue_write("01234567890123456789")
        gobject.timeout_add(1000, send_gibberish)
        gobject.timeout_add(3000, self.try_sending_again)


def main():
    import sys
    from tests.xpra.clients.test_DoS_client import test_DoS
    #test_DoS(TestGiberringCommandClient, sys.argv)
    test_DoS(TestGiberringCommandClientNoPacketSize, sys.argv)


if __name__ == "__main__":
    main()
