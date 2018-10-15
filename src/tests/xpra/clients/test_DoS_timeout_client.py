#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.log import Logger
log = Logger()

from xpra.client.gobject_client_base import CommandConnectClient


class TestTimeoutClient(CommandConnectClient):
    """
        Use this test against a password protected server.
        The server should kick us within 10 seconds out as we aren't replying
        to its challenge request.
    """

    def __init__(self, conn, opts):
        CommandConnectClient.__init__(self, conn, opts)
        def check_connection_timeout(*args):
            log.error("BUG: timeout did not fire: we are still connected!")
            self.quit()
        gobject.timeout_add(20*1000, check_connection_timeout)

    def _process_challenge(self, packet):
        log.info("got challenge - which we shall ignore!")

    def _process_hello(self, packet):
        log.error("cannot try to DoS this server: it has no password protection!")
        self.quit()

    def quit(self, *args):
        log.info("OK: server correctly terminated the connection")
        CommandConnectClient.quit(self, 0)

def main():
    import sys
    from tests.xpra.clients.test_DoS_client import test_DoS
    test_DoS(TestTimeoutClient, sys.argv)

if __name__ == "__main__":
    main()
