#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class NotificationForwarderMixinTest(ServerMixinTest):

    def test_notification(self):
        from xpra.server.mixins.notification_forwarder import NotificationForwarder
        opts = AdHocStruct()
        opts.notifications = "yes"
        self._test_mixin_class(NotificationForwarder, opts)
        self.verify_packet_error(("notification-close", 1, "test", "hello"))
        self.verify_packet_error(("notification-action", 1))
        self.handle_packet(("set-notify", False))

def main():
    unittest.main()


if __name__ == '__main__':
    main()
