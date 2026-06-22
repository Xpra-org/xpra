#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util.objects import typedict
from xpra.server.session_registry import Session
from xpra.server.session_registry.helper import load_session_registry
from xpra.server.session_registry import mdns


class FakeAuth:
    def __init__(self, uid=1000, gid=1000):
        self.uid = uid
        self.gid = gid

    def get_uid(self):
        return self.uid

    def get_gid(self):
        return self.gid


class FakeListener:
    instances = []

    def __init__(self, service_type, mdns_add=None, mdns_remove=None, mdns_update=None):
        self.service_type = service_type
        self.mdns_add = mdns_add
        self.mdns_remove = mdns_remove
        self.mdns_update = mdns_update
        self.started = False
        self.stopped = False
        FakeListener.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class TestMdnsRegistry(unittest.TestCase):

    def setUp(self):
        FakeListener.instances = []
        patcher = patch.object(mdns, "get_listener_class", return_value=FakeListener)
        self.addCleanup(patcher.stop)
        patcher.start()

    def make_registry(self):
        return mdns.Registry()

    def add_endpoint(self, listener, uuid="u1", name="alpha", display=":10",
                     mode="tcp", address="192.0.2.1", port=14500, session_type="seamless"):
        listener.mdns_add(
            1,
            0,
            f"host {display} ({mode})._xpra._tcp.local.",
            "_xpra._tcp.",
            "local",
            "host._xpra._tcp.local.",
            address,
            port,
            {
                b"uuid": uuid.encode(),
                b"name": name.encode(),
                b"display": display.encode(),
                b"mode": mode.encode(),
                b"username": b"alice",
                b"type": session_type.encode(),
            },
        )

    def test_starts_and_cleans_up_listeners(self):
        registry = self.make_registry()
        self.assertEqual(len(FakeListener.instances), 2)
        self.assertTrue(all(listener.started for listener in FakeListener.instances))

        registry.cleanup()

        self.assertTrue(all(listener.stopped for listener in FakeListener.instances))

    def test_load_registry(self):
        registry = load_session_registry("mdns")

        self.assertEqual(registry.NAME, "mdns")
        registry.cleanup()

    def test_lookup_without_hint_returns_first_session(self):
        registry = self.make_registry()
        self.add_endpoint(FakeListener.instances[0], uuid="u1", name="alpha", display=":10")
        self.add_endpoint(FakeListener.instances[0], uuid="u2", name="beta", display=":20", address="192.0.2.2")

        session = registry.lookup(FakeAuth())

        self.assertIsInstance(session, Session)
        self.assertEqual(session.uuid, "u1")
        self.assertEqual(session.session_name, "alpha")
        self.assertEqual(session.uid, 1000)
        self.assertEqual(session.gid, 1000)
        self.assertEqual(session.displays, ["tcp://alice@192.0.2.1/10"])
        self.assertEqual(session.selected_display, "tcp://alice@192.0.2.1/10")

    def test_proxy_services_are_ignored_by_default(self):
        registry = self.make_registry()
        self.add_endpoint(FakeListener.instances[0], uuid="proxy-uuid", name="proxy", display=":proxy",
                          session_type="proxy")

        self.assertIsNone(registry.lookup(FakeAuth()))

    def test_own_uuid_is_ignored(self):
        registry = mdns.Registry(uuid="u1")
        self.add_endpoint(FakeListener.instances[0], uuid="u1", name="proxy", display=":10")

        self.assertIsNone(registry.lookup(FakeAuth()))

    def test_load_registry_passes_extra_options(self):
        registry = load_session_registry("mdns", uuid="u1")
        self.add_endpoint(FakeListener.instances[0], uuid="u1", name="proxy", display=":10")

        self.assertIsNone(registry.lookup(FakeAuth()))
        registry.cleanup()

    def test_proxy_services_can_be_included(self):
        registry = mdns.Registry(**{"include-proxy": "yes"})
        self.add_endpoint(FakeListener.instances[0], uuid="proxy-uuid", name="proxy", display=":proxy",
                          session_type="proxy")

        session = registry.lookup(FakeAuth())

        self.assertIsNotNone(session)
        self.assertEqual(session.uuid, "proxy-uuid")

    def test_lookup_by_session_name(self):
        registry = self.make_registry()
        self.add_endpoint(FakeListener.instances[0], uuid="u1", name="alpha", display=":10")
        self.add_endpoint(FakeListener.instances[0], uuid="u2", name="beta", display=":20", address="192.0.2.2")

        session = registry.lookup(FakeAuth(), typedict({"session-name": "beta"}))

        self.assertIsNotNone(session)
        self.assertEqual(session.uuid, "u2")
        self.assertEqual(session.displays, ["tcp://alice@192.0.2.2/20"])
        self.assertEqual(session.selected_display, "tcp://alice@192.0.2.2/20")

    def test_lookup_by_display_and_uri(self):
        registry = self.make_registry()
        self.add_endpoint(FakeListener.instances[0], uuid="u1", name="alpha", display=":10")

        by_display = registry.lookup(FakeAuth(), typedict({"display": "10"}))
        by_uri = registry.lookup(FakeAuth(), typedict({"display": "tcp://alice@192.0.2.1/10"}))

        self.assertIsNotNone(by_display)
        self.assertEqual(by_display.uuid, "u1")
        self.assertIsNotNone(by_uri)
        self.assertEqual(by_uri.uuid, "u1")
        self.assertEqual(by_uri.selected_display, "tcp://alice@192.0.2.1/10")

    def test_remove_endpoint(self):
        registry = self.make_registry()
        listener = FakeListener.instances[0]
        self.add_endpoint(listener, uuid="u1", name="alpha", display=":10")
        self.assertIsNotNone(registry.lookup(FakeAuth()))

        listener.mdns_remove(1, 0, "host :10 (tcp)._xpra._tcp.local.", "_xpra._tcp.", "local", 0)

        self.assertIsNone(registry.lookup(FakeAuth()))

    def test_get_info_lists_mdns_sessions(self):
        registry = self.make_registry()
        self.add_endpoint(FakeListener.instances[0], uuid="u1", name="alpha", display=":10")

        info = registry.get_info()

        self.assertEqual(info["mdns"]["sessions"][0]["uuid"], "u1")
        self.assertEqual(info["mdns"]["sessions"][0]["endpoints"], ["tcp://alice@192.0.2.1/10"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
