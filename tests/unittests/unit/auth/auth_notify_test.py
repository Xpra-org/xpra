#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.thread import start_thread

GLib = gi_import("GLib")

try:
    from xpra.auth import notify
    from xpra.dbus import auth_request
except ImportError:
    notify = auth_request = None


def make_notifier_class(handles_actions=True, response=None):
    shown = []
    closed = []

    class FakeNotifier:

        def __init__(self, closed_cb, action_cb):
            self.closed_cb = closed_cb
            self.action_cb = action_cb
            self.handles_actions = handles_actions

        def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                        summary, body, actions, hints, expire_timeout, icon):
            shown.append((nid, summary, body, actions, expire_timeout))
            if response == "closed":
                GLib.idle_add(self.closed_cb, nid, 2, "dismissed by the user")
            elif response:
                GLib.idle_add(self.action_cb, nid, response)

        def cleanup(self):
            closed.extend(nid for nid, *_ in shown)

    return FakeNotifier, shown, closed


@unittest.skipIf(auth_request is None, "dbus notifications are not available")
class TestNotifyAuthenticator(unittest.TestCase):

    def run_auth(self, timeout=5, **kwargs):
        notifier_class, shown, closed = make_notifier_class(**kwargs)
        connection = SimpleNamespace(remote=("10.0.0.1", 12345), options={})
        auth = notify.Authenticator(connection=connection, timeout=timeout)
        assert repr(auth) == "notify"
        assert not auth.requires_challenge()
        result = []
        loop = GLib.MainLoop()

        def authenticate():
            result.append(auth.authenticate(typedict()))
            GLib.idle_add(loop.quit)

        with patch("xpra.dbus.auth_request.AuthNotifier", notifier_class):
            start_thread(authenticate, "test-notify-auth", daemon=True)
            GLib.timeout_add((timeout + 5) * 1000, loop.quit)
            loop.run()
            # let the cleanup callbacks run:
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
        assert len(result) == 1, "authentication did not complete"
        return result[0], shown, closed

    def test_allow(self):
        r, shown, _ = self.run_auth(response="allow")
        assert r is True
        assert len(shown) == 1
        nid, summary, body, actions, expire_timeout = shown[0]
        assert "10.0.0.1" in body
        assert actions[0] == "allow"
        assert expire_timeout == 5000

    def test_deny(self):
        r, shown, _ = self.run_auth(response="deny")
        assert r is False
        assert len(shown) == 1

    def test_closed(self):
        r, _, _ = self.run_auth(response="closed")
        assert r is False

    def test_timeout(self):
        r, shown, closed = self.run_auth(timeout=1)
        assert r is False
        assert closed == [shown[0][0]], "the request should be closed on timeout"

    def test_no_actions(self):
        r, shown, _ = self.run_auth(handles_actions=False, response="allow")
        assert r is False
        assert not shown

    def test_main_thread(self):
        notifier_class, shown, _ = make_notifier_class(response="allow")
        connection = SimpleNamespace(remote=("10.0.0.1", 12345), options={})
        auth = notify.Authenticator(connection=connection)
        with patch("xpra.dbus.auth_request.AuthNotifier", notifier_class):
            assert auth.authenticate(typedict()) is False
        assert not shown

    def test_missing_connection(self):
        with self.assertRaises(ValueError):
            notify.Authenticator()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
