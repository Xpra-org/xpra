#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform import program_context
from tests.xpra.net.test_protocol_base import SimpleClient, SimpleServer
import gobject

def main():
    with program_context("Network-Test", "Xpra Network Protocol Test Tool"):
        mainloop = gobject.MainLoop()
        ss = SimpleServer()
        ss.init(mainloop.quit)
        def start_client(*args):
            sc = SimpleClient()
            sc.init(mainloop.quit, [("hello", ()), ("disconnect", "because we want to")])
            return False
        gobject.timeout_add(1000*1, start_client)
        mainloop.run()

if __name__ == "__main__":
    main()
