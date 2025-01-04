#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import unittest

from xpra.util.objects import AdHocStruct
from xpra.os_util import WIN32, OSX
from xpra.util.env import OSEnvContext

from unit.test_util import silence_info
from unit.server.mixins.servermixintest_util import ServerMixinTest


class NotificationForwarderMixinTest(ServerMixinTest):

    def test_notification(self):
        with OSEnvContext():
            #remove any existing dbus environment so we don't pollute it:
            for k in tuple(os.environ.keys()):
                if k.startswith("DBUS"):
                    del os.environ[k]
            #start a dbus server:
            from xpra.server.dbus.start import start_dbus
            dbus_pid, dbus_env = start_dbus("dbus-launch --sh-syntax --close-stderr")
            try:
                if dbus_env:
                    os.environ.update(dbus_env)

                from xpra.server.mixins import notification
                opts = AdHocStruct()
                opts.notifications = "yes"
                with silence_info(notification):
                    self._test_mixin_class(notification.NotificationForwarder, opts)
                self.verify_packet_error(("notification-close", 1, "test", "hello"))
                self.verify_packet_error(("notification-action", 1))
                self.handle_packet(("notification-status", False))
                self.mixin.cleanup()
                time.sleep(0.1)
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
