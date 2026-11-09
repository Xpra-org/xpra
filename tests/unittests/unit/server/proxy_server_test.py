#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from xpra.os_util import POSIX, WIN32
from xpra.util.objects import typedict
from xpra.util.io import pollwait
from unit.server_test_util import ServerTestUtil, log


class ProxyControlTest(unittest.TestCase):

    def test_proxy_stop_control_command(self):
        from xpra.server.core import ServerCore
        from xpra.server.proxy.server import ProxyServer
        from xpra.server.subsystem.control import ControlHandler
        for enabled in (True, False, None):
            with self.subTest(control=enabled):
                server = ProxyServer.__new__(ProxyServer)
                server.hello_request_handlers = {}
                server.subsystems = {}
                server.session_registry_name = "auth"
                if enabled is not None:
                    control = ControlHandler(server)
                    server.subsystems["control"] = control
                    control.init(SimpleNamespace(control=enabled))
                    control.setup()
                registry = object()
                with patch.object(ServerCore, "setup") as setup, \
                     patch("xpra.server.proxy.server.load_session_registry", return_value=registry) as load_registry:
                    server.setup()
                setup.assert_called_once_with()
                load_registry.assert_called_once_with("auth", uuid="")
                self.assertIs(server.session_registry, registry)
                if enabled is None:
                    continue
                self.assertEqual("stop" in control.commands, enabled)
                if enabled:
                    self.assertIn("readonly", control.commands)
                    self.assertIn("client-readonly", control.commands)
                    instance = Mock(pid=123)
                    server.instances = {instance: (True, ":100", None)}
                    server.stop_proxy = Mock()
                    self.assertEqual(control.commands["stop"].run(":100"), "stopped proxy instance for display :100")
                    server.stop_proxy.assert_called_once_with(instance)

    def test_stop_request_client_shutdown(self):
        from xpra.server.proxy import server as proxy_server
        from xpra.server.proxy.server import ProxyServer

        def stop_allowed(client_shutdown, can_stop: bool, socktype="tcp", authenticators=(), options=None) -> bool:
            server = ProxyServer.__new__(ProxyServer)
            server.client_shutdown = client_shutdown
            server._requests = set()
            server.subsystems = {"network": Mock()}
            server.make_hello = Mock(return_value={})
            server.timeout_add = Mock()
            proto = Mock(authenticators=authenticators)
            proto._conn.options = options or {}
            with patch.object(proxy_server, "CAN_STOP_PROXY", can_stop), \
                 patch.object(proxy_server, "get_socktype", return_value=socktype):
                server.handle_stop_request(proto)
            allowed = proto in server._requests
            # a refused request is disconnected, an accepted one gets a hello back:
            self.assertEqual(server.network.send_disconnect.called, not allowed)
            self.assertEqual(proto.send_now.called, allowed)
            return allowed

        # "auto" uses the default policy:
        self.assertTrue(stop_allowed(None, True))
        self.assertFalse(stop_allowed(None, False))
        self.assertTrue(stop_allowed(None, False, socktype="named-pipe"))
        self.assertFalse(stop_allowed(None, False, socktype="socket"))
        self.assertTrue(stop_allowed(None, False, socktype="socket", authenticators=(Mock(), )))
        # the option overrides the default policy:
        for can_stop in (False, True):
            for socktype in ("tcp", "named-pipe", "socket"):
                self.assertTrue(stop_allowed(True, can_stop, socktype=socktype))
                self.assertFalse(stop_allowed(False, can_stop, socktype=socktype, authenticators=(Mock(), )))
        # the socket option still has the last word:
        self.assertFalse(stop_allowed(True, True, options={"stop": "no"}))
        self.assertTrue(stop_allowed(False, False, options={"stop": "yes"}))


class ProxyServerTest(ServerTestUtil):

    def test_proxy_instance_process_control_handler_init(self):
        from xpra.server.proxy.instance_process import ProxyInstanceProcess
        client_conn = MagicMock()
        client_conn.socktype = "tcp"
        server_conn = MagicMock()
        server_conn.socktype = "tcp"

        instance = ProxyInstanceProcess(1000, 1000, {}, {}, "/tmp", 0,
                                        client_conn, {"type": "tcp"}, {},
                                        "", "", b"", server_conn, typedict({}), MagicMock())

        control_handler = instance.subsystems["control"]
        self.assertIs(control_handler, instance.control_handler)
        self.assertIs(control_handler.server, instance)
        self.assertIn("command", instance.hello_request_handlers)
        if POSIX:
            self.assertEqual(instance._start_method, "fork")

    def test_proxy_start_stop(self):
        display = self.find_free_display()
        log(f"using free display={display}")
        cmd = ["proxy", display, "--no-daemon"]
        cmdstr = " ".join(f"'{c}'" for c in cmd)
        proxy = self.run_xpra(cmd)
        r = pollwait(proxy, 5)
        if r is not None:
            self.show_proc_pipes(proxy)
        assert r is None, f"proxy failed to start with cmd={cmdstr}, exit code={r}"
        displays = self.dotxpra.displays()
        assert display in displays, f"proxy display {display!r} not found in {displays}"
        self.check_stop_server(proxy, "stop", display)

    def stop_server(self, server_proc, subcommand, *connect_args):
        if WIN32:
            super().stop_server(server_proc, subcommand, *connect_args)
            return
        log("stop_server%s", (server_proc, subcommand, connect_args))
        if server_proc.poll() is not None:
            return
        server_proc.terminate()
        assert pollwait(server_proc) is not None, f"server process {server_proc} failed to exit"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
