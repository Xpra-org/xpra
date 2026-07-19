#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net.common import Packet
from xpra.os_util import get_hex_uuid
from xpra.server.subsystem.client_session import ClientSessionServer
from xpra.util.objects import typedict
from unit.server.subsystem.servermixintest_util import FakeServerBase


class FakeSource:

    def __init__(self, uuid: str):
        self.uuid = uuid
        self.settings = []
        self.client_readonly = False
        self.enforced_readonly = False

    def send_setting_change(self, setting: str, value) -> None:
        self.settings.append((setting, value))

    def server_enforced_readonly(self) -> bool:
        return self.enforced_readonly

    def set_client_readonly(self, readonly: bool) -> None:
        self.client_readonly = readonly


class FakeConnection(FakeSource):

    def __init__(self, proto, drop_client, server, setting_changed):
        super().__init__("connection")
        self.protocol = proto
        self.drop_client = drop_client
        self.server = server
        self.setting_changed = setting_changed
        self.caps = None

    def parse_hello(self, caps: typedict) -> None:
        self.caps = caps

    def close(self) -> None:
        pass


class FakeServer(FakeServerBase):

    def __init__(self):
        super().__init__()
        self.dispatched = []
        self.cleaned = []
        self.emitted = []
        self.accepted = []
        self.disconnected = []
        self._potential_protocols = []
        self.idle_calls = []

    def idle_add(self, *args) -> int:
        # subsystems copy this from the server they are constructed with,
        # so recording here verifies the scheduler injection too:
        self.idle_calls.append(args)
        return 0

    def send_disconnect(self, proto, *messages) -> None:
        self.disconnected.append((proto, messages))

    def _dispatch_first_truthy(self, method: str, *args):
        self.dispatched.append((method, args))
        return ""

    def _dispatch_fire(self, method: str, *args) -> None:
        self.dispatched.append((method, args))

    def cleanup_source(self, source) -> None:
        self.cleaned.append(source)

    def sanity_checks(self, _proto, _caps: typedict) -> bool:
        return True

    def setting_changed(self, _setting: str, _value) -> None:
        pass

    def accept_protocol(self, proto, caps: typedict) -> None:
        self.accepted.append((proto, caps))

    def emit(self, signal: str, *args) -> None:
        self.emitted.append((signal, args))


class ClientSessionTest(unittest.TestCase):

    def setUp(self) -> None:
        self.server = FakeServer()
        self.session = ClientSessionServer(self.server)
        self.server.subsystems[self.session.PREFIX] = self.session

    def test_dispatch_hooks(self) -> None:
        source = FakeSource("source")
        self.assertEqual(self.session.dispatch_parse_hello(source, {}), "")
        self.session.dispatch_add_new_client(source, {})
        self.session.dispatch_send_initial_data(source)
        self.assertEqual([x[0] for x in self.server.dispatched],
                         ["parse_hello", "add_new_client", "send_initial_data"])

    def test_sanity_checks_uuids(self) -> None:
        proto = object()
        caps = typedict({"uuid": get_hex_uuid(), "session-id": get_hex_uuid()})
        self.assertTrue(self.session.sanity_checks(proto, caps))
        self.assertFalse(self.server.disconnected)
        # a uuid we may end up using as a filename must not contain a path:
        for attr in ("uuid", "session-id"):
            caps = typedict({attr: "../../../etc/passwd"})
            self.assertFalse(self.session.sanity_checks(proto, caps))
        self.assertEqual(len(self.server.disconnected), 2)

    def test_hello_creates_source(self) -> None:
        proto = object()
        caps = typedict({"client_type": "test"})
        with patch.object(ClientSessionServer, "get_client_connection_class", return_value=FakeConnection):
            self.assertTrue(self.session.hello_oked(proto, caps, {}))
        source = self.session.get_server_source(proto)
        self.assertIsInstance(source, FakeConnection)
        self.assertIs(source.caps, caps)
        self.assertEqual(self.server.accepted, [(proto, caps)])
        self.assertEqual(self.server.idle_calls, [(self.session.process_hello_ui, source, caps, {})])

    def test_source_state(self) -> None:
        proto1 = object()
        proto2 = object()
        source1 = FakeSource("one")
        source2 = FakeSource("two")
        self.session.sources.update({proto1: source1, proto2: source2})

        self.assertIs(self.session.get_server_source(proto1), source1)
        self.assertTrue(self.session.is_authenticated(proto2))
        self.assertEqual(self.session.get_sources_by_type(FakeSource, exclude=source2), (source1,))

        self.session.set_ui_driver(source1)
        self.assertEqual(self.session.ui_driver, source1.uuid)
        self.assertEqual(self.server.emitted, [("new-ui-driver", (source1,))])

        source1.enforced_readonly = True
        source2.enforced_readonly = False
        self.session.setting_changed("readonly", True)
        self.assertEqual(source1.settings, [("readonly", True)])
        self.assertEqual(source2.settings, [("readonly", False)])

        self.session._process_readonly_toggled(proto1, Packet("readonly-toggled", True))
        self.assertTrue(source1.client_readonly)
        self.assertFalse(source2.client_readonly)

        self.assertIs(self.session.cleanup_client_protocol(proto1), source1)
        self.assertNotIn(proto1, self.session.sources)
        self.assertEqual(self.server.cleaned, [source1])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
