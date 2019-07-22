#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest

from xpra.util import AdHocStruct
from xpra.os_util import OSEnvContext, WIN32, OSX
from unit.server.mixins.servermixintest_util import ServerMixinTest


class NotificationForwarderMixinTest(ServerMixinTest):

    def test_notification(self):
        with OSEnvContext():
            #remove any existing dbus environment so we don't pollute it:
            for k in tuple(os.environ.keys()):
                if k.startswith("DBUS"):
                    del os.environ[k]
            #start a dbus server:
            from xpra.server.dbus.dbus_start import start_dbus
            dbus_pid, dbus_env = start_dbus("dbus-launch --sh-syntax --close-stderr")
            try:
                if dbus_env:
                    os.environ.update(dbus_env)

                from xpra.server.mixins.notification_forwarder import NotificationForwarder
                opts = AdHocStruct()
                opts.notifications = "yes"
                self._test_mixin_class(NotificationForwarder, opts)
                self.verify_packet_error(("notification-close", 1, "test", "hello"))
                self.verify_packet_error(("notification-action", 1))
                self.handle_packet(("set-notify", False))
            finally:
                if dbus_pid:
                    import signal
                    os.kill(dbus_pid, signal.SIGINT)

def main():
    if WIN32 or OSX:
        print("skipping test on %s" % sys.platform)
    else:
        unittest.main()


if __name__ == '__main__':
    main()
