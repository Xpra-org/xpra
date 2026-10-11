#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from typing import List
from unittest.mock import patch

try:
    import paramiko
    HAVE_PARAMIKO = bool(paramiko)
except ImportError:
    HAVE_PARAMIKO = False


def start_fake_win32_agent() -> List[int]:
    """
    Serve a minimal OpenSSH agent on its named pipe, unless a real one is already there.
    It answers `SSH2_AGENTC_REQUEST_IDENTITIES` with zero keys.
    Returns the list of request types received, which is updated as requests come in.
    """
    import ctypes
    import struct
    import threading
    from ctypes import wintypes
    pipe_name = r"\\.\pipe\openssh-ssh-agent"
    requests: List[int] = []
    if any(name.lower() == "openssh-ssh-agent" for name in os.listdir("\\\\.\\pipe\\")):
        return requests
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateNamedPipeW.restype = wintypes.HANDLE
    k32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k32.WriteFile.argtypes = k32.ReadFile.argtypes
    k32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def read(handle, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        got = wintypes.DWORD()
        data = b""
        while len(data) < size:
            if not k32.ReadFile(handle, buf, size - len(data), ctypes.byref(got), None) or not got.value:
                return b""
            data += buf.raw[:got.value]
        return data

    def serve(handle) -> None:
        try:
            while True:
                header = read(handle, 4)
                if not header:
                    return
                msg = read(handle, struct.unpack(">I", header)[0])
                if not msg:
                    return
                requests.append(msg[0])
                # IDENTITIES_ANSWER with no keys, or SSH_AGENT_FAILURE:
                reply = bytes([12]) + struct.pack(">I", 0) if msg[0] == 11 else bytes([5])
                data = struct.pack(">I", len(reply)) + reply
                k32.WriteFile(handle, data, len(data), ctypes.byref(wintypes.DWORD()), None)
        finally:
            k32.DisconnectNamedPipe(handle)
            k32.CloseHandle(handle)

    def listen() -> None:
        while True:
            handle = k32.CreateNamedPipeW(pipe_name, 3, 0, 255, 4096, 4096, 0, None)
            if handle == wintypes.HANDLE(-1).value:
                return
            k32.ConnectNamedPipe(handle, None)
            threading.Thread(target=serve, args=(handle, ), daemon=True).start()

    threading.Thread(target=listen, daemon=True).start()
    return requests


class AgentForwardingServer:
    """
    An in-process paramiko ssh server, which records agent forwarding requests
    and can query the forwarded agent like `ssh-add -l` would.
    """

    def __init__(self):
        import socket
        import threading
        import paramiko
        self.agent_forwarding_requested = False
        self.exec_command = b""
        self.exec_event = threading.Event()
        outer = self

        class Server(paramiko.ServerInterface):
            def check_auth_none(self, username):
                return paramiko.AUTH_SUCCESSFUL

            def get_allowed_auths(self, username):
                return "none"

            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED

            def check_channel_forward_agent_request(self, channel):
                outer.agent_forwarding_requested = True
                return True

            def check_channel_exec_request(self, channel, command):
                outer.exec_command = command
                outer.exec_event.set()
                return True

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        server_transport_ready = threading.Event()

        def accept() -> None:
            sock, _ = listener.accept()
            listener.close()
            self.server_transport = paramiko.Transport(sock)
            self.server_transport.add_server_key(paramiko.RSAKey.generate(2048))
            self.server_transport.start_server(server=Server())
            server_transport_ready.set()
            self.session = self.server_transport.accept(10)

        threading.Thread(target=accept, daemon=True).start()
        self.client_transport = paramiko.Transport(socket.create_connection(listener.getsockname()))
        self.client_transport.start_client(timeout=10)
        self.client_transport.auth_none("user")
        server_transport_ready.wait(10)

    def query_forwarded_agent(self, timeout: float = 2) -> bytes:
        import socket
        import struct
        chan = self.server_transport.open_forward_agent_channel()
        chan.settimeout(timeout)
        # SSH2_AGENTC_REQUEST_IDENTITIES:
        chan.send(struct.pack(">I", 1) + bytes([11]))
        try:
            return chan.recv(4096)
        except socket.timeout:
            return b""
        finally:
            chan.close()

    def close(self) -> None:
        self.client_transport.close()
        self.server_transport.close()


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestAgentForwarding(unittest.TestCase):

    def setUp(self):
        from xpra.net.ssh import paramiko_client
        patcher = patch.object(paramiko_client, "WIN32_AGENT_FORWARDING", False, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = AgentForwardingServer()

    def tearDown(self):
        self.server.close()

    def open_channel(self, agent: str):
        from xpra.net.ssh import paramiko_client
        responses = {
            "echo %OS%": ["%OS%"], "echo $OSTYPE": ["linux"],
            "command": [], "command -v xpra": ["xpra"],
        }

        def command_result(_transport, command):
            return responses[command], [], 0

        with patch.object(paramiko_client, "run_test_command", side_effect=command_result):
            chan = paramiko_client.run_remote_xpra(
                self.server.client_transport, ["_proxy_start"], ["xpra"],
                display_as_args=[":100"], paramiko_config={"agent": agent},
            )
        assert self.server.exec_event.wait(10)
        self.assertEqual(self.server.exec_command, b'"xpra" "_proxy_start" ":100"')
        return chan

    def test_agent_disabled(self):
        self.open_channel("no")
        assert not self.server.agent_forwarding_requested

    @unittest.skipIf(os.name == "nt", "agent forwarding is not supported on MS Windows")
    def test_agent_enabled(self):
        self.open_channel("yes")
        assert self.server.agent_forwarding_requested

    def test_agent_not_forwarded_on_win32(self):
        from xpra.net.ssh import paramiko_client
        # Exercise the Windows policy on every platform: remote requests would hang.
        with patch.object(paramiko_client, "WIN32", True):
            self.open_channel("yes")
        assert not self.server.agent_forwarding_requested

    def test_agent_forwarding_can_be_forced_on_win32(self):
        from xpra.net.ssh import paramiko_client
        with patch.object(paramiko_client, "WIN32", True), \
                patch.object(paramiko_client, "WIN32_AGENT_FORWARDING", True):
            self.open_channel("yes")
        assert self.server.agent_forwarding_requested

    @unittest.skipUnless(os.name == "nt", "MS Windows only")
    def test_paramiko_win32_agent_forwarding_hangs(self):
        """
        Reproducer for #4353, this is a paramiko bug:
        the local agent can be reached directly, but not through `AgentRequestHandler`.
        If this test starts failing, paramiko has been fixed
        and `XPRA_SSH_WIN32_AGENT_FORWARDING` can be enabled by default.
        """
        import threading
        from paramiko.agent import Agent, AgentRequestHandler
        requests = start_fake_win32_agent()
        agent = Agent()
        agent.close()
        if requests:
            assert requests == [11]
        chan = self.server.client_transport.open_session(timeout=10)
        handler = AgentRequestHandler(chan)
        chan.exec_command("xpra _proxy_start :100")
        assert self.server.exec_event.wait(10)
        assert self.server.agent_forwarding_requested
        # paramiko's `AgentProxyThread` raises "Unable to connect to SSH agent" in its thread:
        with patch.object(threading, "excepthook"):
            reply = self.server.query_forwarded_agent()
        # paramiko closes the agent connections again from `__del__`, which raises `EBADF`:
        proxies = handler._AgentRequestHandler__clientProxys
        for proxy in proxies:
            proxy.close()
            proxy._conn = None
        proxies.clear()
        assert reply == b"", "paramiko forwarded the agent request"


if __name__ == "__main__":
    unittest.main()
