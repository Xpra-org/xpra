#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.session_discovery import (
    SessionEndpoint,
    endpoint_uri,
    group_session_endpoints,
    mdns_txt_to_dict,
    normalize_mdns_host,
    session_group_key,
    vsock_endpoint_from_txt,
)


def make_endpoint(host="host.local", display=":10", uuid="", name="", session="", mode="tcp",
                  username="", platform="", session_type="", icon=None):
    text = {
        "display": display,
        "mode": mode,
    }
    if uuid:
        text["uuid"] = uuid
    if name:
        text["name"] = name
    if session:
        text["session"] = session
    if username:
        text["username"] = username
    if platform:
        text["platform"] = platform
    if session_type:
        text["type"] = session_type
    if icon is not None:
        text["icon"] = icon
    return SessionEndpoint(
        source="mdns",
        protocol=0,
        name="service",
        stype="_xpra._tcp.",
        domain="local",
        host=host,
        address="192.0.2.1",
        port=14500,
        text=text,
    )


class TestSessionGrouping(unittest.TestCase):

    def test_uuid_groups_multiple_endpoints(self):
        tcp = make_endpoint(host="example.local", display=":10", uuid="u1", mode="tcp")
        ws = make_endpoint(host="example.local", display=":10", uuid="u1", mode="ws")

        groups = group_session_endpoints([tcp, ws])

        self.assertEqual(list(groups), ["u1"])
        group = groups["u1"]
        self.assertEqual(group.key, "u1")
        self.assertEqual(group.endpoints, [tcp, ws])
        self.assertEqual(group.display, ":10")
        self.assertEqual(group.uuid, "u1")

    def test_fallback_key_uses_normalized_host_and_display(self):
        endpoint = make_endpoint(host="example.local", display=":20")

        self.assertEqual(session_group_key(endpoint), ("example", ":20"))

    def test_group_copies_first_available_metadata(self):
        icon = object()
        endpoint = make_endpoint(
            uuid="u1",
            name="desktop",
            username="alice",
            platform="linux",
            session_type="desktop",
            icon=icon,
        )

        group = group_session_endpoints([endpoint])["u1"]

        self.assertEqual(group.session_name, "desktop")
        self.assertEqual(group.username, "alice")
        self.assertEqual(group.platform, "linux")
        self.assertEqual(group.session_type, "desktop")
        self.assertIs(group.icon, icon)

    def test_session_name_falls_back_to_session_txt_key(self):
        endpoint = make_endpoint(uuid="u1", session="legacy-name")

        group = group_session_endpoints([endpoint])["u1"]

        self.assertEqual(group.session_name, "legacy-name")

    def test_uuid_group_local_host_label_matches_existing_ui(self):
        endpoint = make_endpoint(host="localhost", uuid="u1")

        group = group_session_endpoints([endpoint])["u1"]

        self.assertEqual(group.host, "local")

    def test_fallback_group_keeps_local_host_for_display_title(self):
        endpoint = make_endpoint(host="localhost")

        group = group_session_endpoints([endpoint])[("localhost", ":10")]

        self.assertEqual(group.host, "localhost")
        self.assertEqual(group.display, ":10")

    def test_mdns_helpers_decode_and_normalize(self):
        text = mdns_txt_to_dict({b"mode": b"tcp", b"username": b"alice"})

        self.assertEqual(text, {"mode": "tcp", "username": "alice"})
        self.assertEqual(normalize_mdns_host("host._xpra._tcp.local.", "_xpra._tcp.", "local", "tcp"), "host")

    def test_endpoint_uri_uses_existing_display_uri_shape(self):
        endpoint = make_endpoint(username="alice", display=":10")

        self.assertEqual(endpoint_uri("", endpoint), "tcp://alice@192.0.2.1/10")

    def test_vsock_endpoint_from_txt(self):
        endpoint = make_endpoint(username="alice", display=":10", uuid="u1")
        endpoint.text["vsock"] = "7:14500"

        vsock_endpoint = vsock_endpoint_from_txt(endpoint)

        self.assertIsNotNone(vsock_endpoint)
        self.assertEqual(vsock_endpoint.address, "7")
        self.assertEqual(vsock_endpoint.port, 14500)
        self.assertEqual(vsock_endpoint.mode, "vsock")
        self.assertEqual(vsock_endpoint.uuid, "u1")
        self.assertEqual(session_group_key(vsock_endpoint), session_group_key(endpoint))
        self.assertEqual(endpoint_uri("", vsock_endpoint), "vsock://alice@7:14500/10")

    def test_vsock_endpoint_from_txt_rejects_invalid_values(self):
        for value in ("", "7", ":14500", "7:notaport", "7:0"):
            endpoint = make_endpoint()
            endpoint.text["vsock"] = value
            self.assertIsNone(vsock_endpoint_from_txt(endpoint))

    def test_endpoint_uri_accepts_valid_fields(self):
        # benign values (including a screen suffix and modes with `-`/`+`) are preserved:
        self.assertEqual(endpoint_uri("", make_endpoint(display=":10.0")), "tcp://192.0.2.1/10.0")
        self.assertEqual(endpoint_uri("", make_endpoint(username="alice-1.test")),
                         "tcp://alice-1.test@192.0.2.1/10")
        # modes containing `-` / `+` are valid (the port is appended since they have no default):
        self.assertTrue(endpoint_uri("", make_endpoint(mode="named-pipe")).startswith("named-pipe://192.0.2.1"))
        self.assertTrue(endpoint_uri("", make_endpoint(mode="vnc+ssh")).startswith("vnc+ssh://192.0.2.1"))

    def test_endpoint_uri_rejects_unsafe_display(self):
        # an untrusted advertisement must not be able to smuggle URL syntax
        # (query string, extra host, path traversal, ...) into the attach URI:
        for display in (":10?proxy-host=evil.com&proxy-port=1080", ":10@evil/10", ":10/../x", ":10 22"):
            self.assertEqual(endpoint_uri("", make_endpoint(display=display)), "")

    def test_endpoint_uri_rejects_unsafe_username(self):
        for username in ("alice?proxy-host=evil", "alice@evil", "alice/x", "a:b"):
            self.assertEqual(endpoint_uri("", make_endpoint(username=username)), "")

    def test_endpoint_uri_rejects_unsafe_mode(self):
        for mode in ("tcp?x", "tcp://evil", "tcp ssl", "../tcp"):
            self.assertEqual(endpoint_uri("", make_endpoint(mode=mode)), "")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
