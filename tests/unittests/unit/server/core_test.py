#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.net.socket_util import SocketListener
from xpra.scripts.config import InitExit
from xpra.server.core import ServerCore


class TestServerCore(unittest.TestCase):

    def test_fatal_subsystem_errors_propagate(self):
        for merge in (False, True):
            with self.subTest(merge=merge):
                server = ServerCore.__new__(ServerCore)
                error = InitExit(1, "startup failed")
                following = Mock()
                server.subsystems = {
                    "failing": SimpleNamespace(setup=Mock(side_effect=error), get_info=Mock(side_effect=error)),
                    "following": SimpleNamespace(setup=following, get_info=following),
                }
                with self.assertRaises(InitExit) as raised:
                    if merge:
                        server._dispatch_merge("get_info")
                    else:
                        server._dispatch_fire("setup")
                self.assertIs(raised.exception, error)
                following.assert_not_called()

    def test_other_subsystem_errors_warn_and_continue(self):
        for merge in (False, True):
            with self.subTest(merge=merge):
                server = ServerCore.__new__(ServerCore)
                following = Mock(return_value={"ready": True})
                server.subsystems = {
                    "failing": SimpleNamespace(setup=Mock(side_effect=ValueError), get_info=Mock(side_effect=ValueError)),
                    "following": SimpleNamespace(setup=following, get_info=following),
                }
                with patch("xpra.server.core.log") as log:
                    if merge:
                        self.assertEqual(server._dispatch_merge("get_info"), {"ready": True})
                    else:
                        server._dispatch_fire("setup")
                following.assert_called_once_with()
                log.warn.assert_called_once()

    def test_handle_invalid_packet_from_detached_protocol(self):
        server = SimpleNamespace(
            _closing=False,
            _potential_protocols=[],
            get_server_source=Mock(return_value=None),
        )
        proto = Mock()
        proto.is_closed.return_value = False
        packet = Packet("logging-event")

        with patch("xpra.server.core.netlog") as netlog:
            ServerCore.handle_invalid_packet(server, proto, packet)

        netlog.assert_called_once_with(
            "packet from detached protocol %s: %s", proto, packet,
        )
        netlog.error.assert_not_called()
        proto.close.assert_called_once_with()

    def test_init_starts_background_worker_first(self):
        server = ServerCore.__new__(ServerCore)
        with patch("xpra.server.core.get_worker") as get_worker:
            # Missing options stop init immediately after the worker is started.
            with self.assertRaises(AttributeError):
                server.init(SimpleNamespace())
        get_worker.assert_called_once_with()

    def test_handle_ssh_connection_uses_display_name_api(self):
        server = ServerCore.__new__(ServerCore)
        display = SimpleNamespace(get_display_name=lambda: ":42")
        server.subsystems = {"display": display}
        conn = SimpleNamespace(socktype_wrapped="tcp")
        with patch("xpra.server.ssh.make_ssh_server_connection", return_value="ssh-conn") as make_ssh:
            result = server.handle_ssh_connection(conn, {})

        assert result == "ssh-conn"
        make_ssh.assert_called_once()
        assert make_ssh.call_args.kwargs["display_name"] == ":42"

    def test_start_listen_sockets_shows_vsock_endpoint(self):
        server = ServerCore.__new__(ServerCore)
        server.sockets = [
            SocketListener("vsock", object(), (0xffffffff, 10000), {}, lambda: None, lambda: None),
        ]
        server.unix_socket_paths = []
        mdns = SimpleNamespace(extra_info={})
        server.subsystems = {"mdns": mdns}
        vsock_mod = SimpleNamespace(
            CID_ANY=0xffffffff,
            CID_TYPES={0xffffffff: "ANY"},
            get_local_cid=lambda: 7,
        )

        with patch.dict(sys.modules, {"xpra.net.vsock.vsock": vsock_mod}):
            with patch("xpra.server.core.GLib.idle_add") as idle_add:
                log = SimpleNamespace(info=Mock())
                with patch("xpra.server.core.log", log):
                    server.start_listen_sockets()

        idle_add.assert_called_once_with(server.add_listen_socket, server.sockets[0])
        log.info.assert_any_call("listening on %s at %s:%s", "vsock", 7, 10000)
        log.info.assert_any_call("  %s://%s:%s", "vsock", 7, 10000)
        self.assertEqual(mdns.extra_info["vsock"], "7:10000")


class ImmediateLoop:
    """Stand-in for an asyncio loop that runs call_soon_threadsafe inline."""

    def call_soon_threadsafe(self, callback, *args):
        callback(*args)


class TestReloadSSLCommand(unittest.TestCase):
    """control_command_reload_ssl + QUIC configuration bookkeeping."""

    def _make_server(self, entries):
        import threading
        from xpra.server.core import ServerCore
        server = ServerCore.__new__(ServerCore)
        server.quic_certificates = list(entries)
        server.quic_certificates_lock = threading.Lock()
        server.quic_reload_lock = threading.Lock()
        return server

    def _make_config(self, cert_path, key_path):
        from aioquic.quic.configuration import QuicConfiguration
        configuration = QuicConfiguration(is_client=False)
        configuration.load_cert_chain(cert_path, key_path)
        return configuration

    def _cert_pems(self, name):
        from unit.net.quic.listener_test import _make_key_and_cert
        return _make_key_and_cert(name)

    def _write(self, path, data):
        with open(path, "wb") as f:
            f.write(data)

    def setUp(self):
        import tempfile
        try:
            import aioquic  # noqa: F401
        except ImportError:
            self.skipTest("aioquic not available")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.cert_path = os.path.join(self.tmpdir.name, "cert.pem")
        self.key_path = os.path.join(self.tmpdir.name, "key.pem")

    def _register_one(self):
        """Register one entry whose files live at self.cert_path/key_path."""
        key_pem, cert_pem = self._cert_pems("reload-a")
        self._write(self.cert_path, cert_pem)
        self._write(self.key_path, key_pem)
        configuration = self._make_config(self.cert_path, self.key_path)
        old_serial = configuration.certificate.serial_number
        store = self._make_store()
        server = self._make_server([])
        server.add_quic_configuration(
            self.cert_path, self.key_path, configuration, store, ImmediateLoop())
        return server, configuration, old_serial, store

    def _make_store(self):
        from xpra.net.quic.session_ticket_store import SessionTicketStore
        return SessionTicketStore()

    def test_reload_with_no_registered_configurations(self):
        server = self._make_server([])
        message = server.control_command_reload_ssl()
        assert "no QUIC listeners" in message
        assert "TCP" in message

    def test_reload_swaps_certificate_from_same_paths(self):
        # a renewal overwrites the SAME files the listener registered
        server, configuration, old_serial, store = self._register_one()
        new_key_pem, new_cert_pem = self._cert_pems("reload-b")
        self._write(self.cert_path, new_cert_pem)
        self._write(self.key_path, new_key_pem)
        message = server.control_command_reload_ssl()
        assert "notAfter" in message
        assert "TCP" in message
        assert configuration.certificate.serial_number != old_serial
        assert store.tickets == {}

    def test_reload_failure_leaves_live_config_unchanged(self):
        server, configuration, old_serial, store = self._register_one()
        with open(self.cert_path, "wb") as f:
            f.write(b"not a certificate")
        from xpra.net.control.common import ControlError
        with self.assertRaises(ControlError):
            server.control_command_reload_ssl()
        assert configuration.certificate.serial_number == old_serial
        # restoring the files makes a subsequent reload succeed. the restored
        # files are a fresh reload-a cert (new random serial), so the swap
        # replaces the live certificate — assert the full success contract:
        key_pem, cert_pem = self._cert_pems("reload-a")
        self._write(self.cert_path, cert_pem)
        self._write(self.key_path, key_pem)
        message = server.control_command_reload_ssl()
        assert "notAfter" in message
        assert configuration.certificate.serial_number != old_serial
        assert store.tickets == {}

    def test_remove_quic_configuration_identity(self):
        # two field-equal QuicConfiguration instances: only identity removal
        # can tell them apart
        from aioquic.quic.configuration import QuicConfiguration
        first = QuicConfiguration(is_client=False)
        second = QuicConfiguration(is_client=False)
        assert first == second
        server = self._make_server([])
        server.add_quic_configuration("c", "k", first, None, None)
        server.add_quic_configuration("c", "k", second, None, None)
        server.remove_quic_configuration(first)
        assert len(server.quic_certificates) == 1
        assert server.quic_certificates[0][2] is second
        # removing an unknown configuration is a no-op:
        server.remove_quic_configuration(object())
        assert server.quic_certificates == [("c", "k", second, None, None)]

    def test_reload_catches_late_registration(self):
        # a listener that finishes starting up while the reload is running
        # must not keep serving the pre-reload certificate
        server, configuration, old_serial, _store = self._register_one()
        from xpra.net.quic import listener as listener_module
        # the late listener loads the pre-reload cert from disk:
        late_configuration = self._make_config(self.cert_path, self.key_path)
        # ... then the renewal overwrites the files:
        new_key_pem, new_cert_pem = self._cert_pems("reload-b")
        self._write(self.cert_path, new_cert_pem)
        self._write(self.key_path, new_key_pem)
        real_apply = listener_module.apply_quic_certificate
        registered = []

        def apply_and_register(cfg, certificate, chain, private_key,
                               ticket_store, loop, cert, timeout=10):
            if not registered:
                registered.append(True)
                server.add_quic_configuration(
                    self.cert_path, self.key_path, late_configuration,
                    self._make_store(), ImmediateLoop())
            return real_apply(cfg, certificate, chain, private_key,
                              ticket_store, loop, cert, timeout=timeout)

        with patch("xpra.net.quic.listener.apply_quic_certificate",
                   apply_and_register):
            server.control_command_reload_ssl()
        # the late registration was reloaded in a second pass:
        assert late_configuration.certificate.serial_number != old_serial

    def test_reload_ssl_command_registered(self):
        from xpra.server.core import ServerCore
        server = ServerCore.__new__(ServerCore)

        class StubControl:
            def __init__(self):
                self.commands = {}

            def add_control_command(self, name, control):
                self.commands[name] = control

        server.subsystems = {"control": StubControl()}
        server.add_core_control_commands()
        command = server.subsystems["control"].commands["reload-ssl"]
        assert command.max_args == 0
        assert "reload" in command.help.lower()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
