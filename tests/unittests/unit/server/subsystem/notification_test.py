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
from unit.server.subsystem.servermixintest_util import ServerMixinTest


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

                from xpra.server.subsystem import notification
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

    def test_initial_data_without_notifications(self):
        from xpra.server.subsystem.notification import NotificationForwarder
        from xpra.server.source.notification import NotificationConnection
        # clients with notifications disabled do not have the `NotificationConnection` mixin:
        NotificationForwarder.send_initial_data(None, object())
        sent = []
        ss = NotificationConnection.__new__(NotificationConnection)
        ss.send_pending_notifications = lambda: sent.append(True)
        NotificationForwarder.send_initial_data(None, ss)
        self.assertEqual(sent, [True])

    def test_action_key(self):
        from xpra.net.common import Packet
        from xpra.dbus.notifications import DBUSNotificationsForwarder
        from xpra.server.subsystem.notification import NotificationForwarder, MAX_ACTION_KEY
        # a forwarder that is not registered on any bus:
        forwarder = object.__new__(DBUSNotificationsForwarder)
        forwarder.active_notifications = {}
        forwarder.notify_callback = None
        forwarder.counter = 0
        invoked = []
        forwarder.ActionInvoked = lambda nid, key: invoked.append((nid, key))
        forwarder.NotificationClosed = lambda nid, reason: None
        nid = forwarder.Notify("app", 0, "", "summary", "body", ["reply", "Reply", "default", "Open"], {}, 1000)

        source = AdHocStruct()
        source.notification_callbacks = {}
        source.user_event = lambda *_args: None
        server = AdHocStruct()
        server.get_server_source = lambda _proto: source
        nf = NotificationForwarder(server)
        nf.enabled = True
        nf.forwarder = forwarder

        def action(key: str, action_nid=nid) -> bool:
            invoked.clear()
            nf._process_action(None, Packet("notification-action", action_nid, key))
            return invoked == [(action_nid, key)]

        self.assertTrue(action("reply"))
        self.assertTrue(action("default"))
        # not offered by the application:
        self.assertFalse(action("Reply"))
        self.assertFalse(action("delete"))
        self.assertFalse(action("reply", nid + 1))
        # not something an application would offer:
        self.assertFalse(action("x" * (MAX_ACTION_KEY + 1)))
        self.assertFalse(action("reply\x00"))
        self.assertFalse(action("re\u202eply"))
        # no longer active:
        forwarder.notification_closed(nid, 2)
        self.assertFalse(action("reply"))


def main():
    if WIN32 or OSX:
        print("skipping test on %s" % sys.platform)
    else:
        unittest.main()


if __name__ == '__main__':
    main()
