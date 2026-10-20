#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from xpra.os_util import get_hex_uuid
from xpra.server.base import ServerBase
from xpra.server.core import ServerCore
from xpra.server.subsystem.client_session import ClientSessionServer
from xpra.util.objects import typedict
from unit.server.subsystem.servermixintest_util import FakeServerBase


class FakeSource:

    def __init__(self, uuid: str):
        self.uuid = uuid


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


class VariantServer(ServerCore):

    def parse_hello(self, ss, caps: typedict):
        result = super().parse_hello(ss, caps)
        self.calls.variant_parse_hello(ss, caps)
        return result

    def add_new_client(self, ss, caps: typedict) -> None:
        super().add_new_client(ss, caps)
        self.calls.variant_add_new_client(ss, caps)

    def send_initial_data(self, ss) -> None:
        super().send_initial_data(ss)
        self.calls.variant_send_initial_data(ss)

    def client_startup_complete(self, ss) -> None:
        super().client_startup_complete(ss)
        self.calls.variant_client_startup_complete(ss)


class ClientSessionTest(unittest.TestCase):

    def setUp(self) -> None:
        self.server = FakeServer()
        self.session = ClientSessionServer(self.server)
        self.server.subsystems[self.session.PREFIX] = self.session

    def test_handshake_calls_variant_hooks_in_order(self) -> None:
        for rejection in ("", "denied:reason"):
            with self.subTest(rejection=rejection):
                calls = Mock()
                calls.parse_hello.return_value = rejection
                server = VariantServer.__new__(VariantServer)
                server.calls = calls
                server._closing = False
                server.send_hello = calls.send_hello
                server.server_event = calls.server_event
                server.notify_new_user = calls.notify_new_user
                session = ClientSessionServer(server)
                peer = SimpleNamespace(parse_hello=calls.parse_hello, add_new_client=calls.add_new_client,
                                       send_initial_data=calls.send_initial_data)
                server.subsystems = {"peer": peer, session.PREFIX: session}
                proto = object()
                source = SimpleNamespace(uuid="source", protocol=proto, startup_complete=calls.startup_complete)
                caps = typedict({"client_type": "test"})
                auth_caps = {"cipher": "test"}
                expected = [call.parse_hello(source, caps), call.variant_parse_hello(source, caps)]
                if rejection:
                    server.subsystems["network"] = SimpleNamespace(disconnect_client=calls.disconnect_client)
                    expected.append(call.disconnect_client(proto, "denied", "reason"))
                else:
                    expected += [
                        call.send_hello(source, auth_caps), call.server_event("handshake-complete"), call.notify_new_user(source),
                        call.add_new_client(source, caps), call.variant_add_new_client(source, caps),
                        call.send_initial_data(source), call.variant_send_initial_data(source),
                        call.startup_complete(), call.server_event("startup-complete", source.uuid),
                        call.variant_client_startup_complete(source),
                    ]
                session.process_hello_ui(source, caps, auth_caps)
                self.assertEqual(calls.mock_calls, expected)

    def test_client_info_filtering(self) -> None:
        server = ServerBase.__new__(ServerBase)
        session = ClientSessionServer(server)
        server.subsystems = {session.PREFIX: session, "network": SimpleNamespace(_potential_protocols=[])}
        for uuid in ("one", "two"):
            session.sources[uuid] = SimpleNamespace(uuid=uuid, get_info=lambda uuid=uuid: {"uuid": uuid})
        session.ui_driver = "two"
        for client_uuids, selected in (((), ("one", "two")), (("two",), ("two",)), (("missing",), ())):
            with self.subTest(client_uuids=client_uuids), patch.object(ServerCore, "get_threaded_info", return_value={}):
                info = server.get_threaded_info(None, client_uuids=client_uuids)
            self.assertEqual(info["clients"], {"": 2, "unauthenticated": 0})
            self.assertEqual(info["client"], {
                i: {"uuid": uuid, "ui-driver": uuid == "two"} for i, uuid in enumerate(selected)
            })
        server.subsystems.pop(session.PREFIX)
        with patch.object(ServerCore, "get_threaded_info", return_value={}):
            self.assertEqual(server.get_threaded_info(None), {})

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

        self.assertIs(self.session.cleanup_client_protocol(proto1), source1)
        self.assertNotIn(proto1, self.session.sources)
        self.assertEqual(self.server.cleaned, [source1])

    def test_ui_driver_handover(self) -> None:
        # cleaning up a source runs in the network thread,
        # so the ui driver must be handed over from the main thread:
        server_events = []
        self.server.server_event = lambda *args: server_events.append(args)
        sources = {object(): FakeConnection(None, None, None, None) for _ in range(2)}
        source1, source2 = sources.values()
        source1.uuid, source2.uuid = "one", "two"
        source1.counter, source2.counter = 1, 2
        self.session.sources.update(sources)
        self.session.set_ui_driver(source1)
        self.server.emitted.clear()

        proto1 = next(iter(sources))
        self.session.sources.pop(proto1)
        self.session.do_cleanup_source(source1)
        self.assertEqual(self.server.emitted, [("client-exited", (source1,))])
        self.assertEqual(self.server.idle_calls, [(self.session.replace_ui_driver, "one")])
        self.session.replace_ui_driver("one")
        self.assertEqual(self.session.ui_driver, "two")
        self.assertEqual(self.server.emitted[-1], ("new-ui-driver", (source2,)))

        # another client took over before the handover ran:
        self.session.set_ui_driver(source1)
        self.session.sources[proto1] = source1
        self.session.set_ui_driver(source2)
        self.session.replace_ui_driver("one")
        self.assertEqual(self.session.ui_driver, "two")
        # the same client reconnected before the handover ran:
        self.session.set_ui_driver(source1)
        self.session.replace_ui_driver("one")
        self.assertEqual(self.session.ui_driver, "one")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
