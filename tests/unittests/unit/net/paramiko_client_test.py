#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

try:
    import paramiko
    HAVE_PARAMIKO = bool(paramiko)
except ImportError:
    HAVE_PARAMIKO = False


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestLoadHostKeys(unittest.TestCase):

    def test_returns_tuple(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        result = load_host_keys()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_filename_is_string(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        filename, _ = load_host_keys()
        assert isinstance(filename, str)

    def test_host_keys_is_hostkeys(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        from paramiko.hostkeys import HostKeys
        _, host_keys = load_host_keys()
        assert isinstance(host_keys, HostKeys)

    def test_with_no_known_hosts(self):
        # Patch platform to return no known hosts files
        from xpra.net.ssh.paramiko.client import load_host_keys
        with patch("xpra.net.ssh.paramiko.client.get_ssh_known_hosts_files", return_value=[]):
            filename, host_keys = load_host_keys()
        assert filename == ""

    def test_with_real_known_hosts_file(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        from paramiko.rsakey import RSAKey
        from paramiko.hostkeys import HostKeys

        key = RSAKey.generate(1024)
        with tempfile.NamedTemporaryFile(mode="w", suffix="_known_hosts", delete=False) as f:
            path = f.name
            hk = HostKeys()
            hk.add("example.com", key.get_name(), key)
            hk.save(path)

        try:
            with patch("xpra.net.ssh.paramiko.client.get_ssh_known_hosts_files", return_value=[path]):
                filename, host_keys = load_host_keys()
            assert filename == path
            assert len(list(host_keys.keys())) > 0
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestVerifyHostkey(unittest.TestCase):

    def _gen_key(self):
        from paramiko.rsakey import RSAKey
        return RSAKey.generate(1024)

    def test_matching_key_returns_empty_string(self):
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key = self._gen_key()
        host_keys = HostKeys()
        host_keys.add("myhost.example", key.get_name(), key)
        with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=("", host_keys)):
            result = verify_hostkey("myhost.example", key,
                                    verifyhostkeydns=False,
                                    stricthostkeychecking=False,
                                    addkey=False)
        assert result == ""

    def test_different_key_unknown_host(self):
        # host not in known_hosts → prompts; mock confirm() to return False
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key = self._gen_key()
        host_keys = HostKeys()  # empty – host unknown
        with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=("", host_keys)):
            with patch("xpra.net.ssh.paramiko.client.confirm", return_value=False):
                result = verify_hostkey("unknown.host", key,
                                        verifyhostkeydns=False,
                                        stricthostkeychecking=False,
                                        addkey=False)
        assert "Unknown" in result or result != ""

    def test_strict_checking_known_mismatch(self):
        # Known host with a *different* key + strict → returns non-empty error string
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key_stored = self._gen_key()
        key_presented = self._gen_key()
        host_keys = HostKeys()
        host_keys.add("strict.host", key_stored.get_name(), key_stored)
        with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=("", host_keys)):
            result = verify_hostkey("strict.host", key_presented,
                                    verifyhostkeydns=False,
                                    stricthostkeychecking=True,
                                    addkey=False)
        assert result != ""

    def test_confirmed_unknown_with_addkey_true(self):
        # confirm() returns True; addkey=True → saves key (no crash)
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key = self._gen_key()
        host_keys = HostKeys()
        with tempfile.NamedTemporaryFile(mode="w", suffix="_kh", delete=False) as f:
            path = f.name
        try:
            with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=(path, host_keys)):
                with patch("xpra.net.ssh.paramiko.client.confirm", return_value=True):
                    with patch("xpra.net.ssh.paramiko.client.get_ssh_known_hosts_files", return_value=[path]):
                        result = verify_hostkey("newhost.example", key,
                                                verifyhostkeydns=False,
                                                stricthostkeychecking=False,
                                                addkey=True)
            assert result == ""
        finally:
            if os.path.exists(path):
                os.unlink(path)


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestSafeLookup(unittest.TestCase):

    def test_regular_lookup(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        from paramiko import SSHConfig
        import io
        config_text = "Host myserver\n  HostName 192.168.1.1\n  User testuser\n"
        ssh_config = SSHConfig()
        ssh_config.parse(io.StringIO(config_text))
        result = safe_lookup(ssh_config, "myserver")
        assert isinstance(result, dict)
        assert result.get("hostname") == "192.168.1.1"
        assert result.get("user") == "testuser"

    def test_wildcard_lookup(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        from paramiko import SSHConfig
        import io
        config_text = "Host *\n  ServerAliveInterval 60\n"
        ssh_config = SSHConfig()
        ssh_config.parse(io.StringIO(config_text))
        result = safe_lookup(ssh_config, "*")
        assert isinstance(result, dict)

    def test_import_error_returns_empty(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        broken = MagicMock(spec=["lookup"])
        broken.lookup = MagicMock(side_effect=ImportError("test import error"))
        result = safe_lookup(broken, "some.host")
        assert result == {}

    def test_key_error_returns_empty(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        broken = MagicMock(spec=["lookup"])
        broken.lookup = MagicMock(side_effect=KeyError("test key error"))
        result = safe_lookup(broken, "some.host")
        assert result == {}


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestConnectToErrors(unittest.TestCase):

    def test_missing_host_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({})

    def test_missing_remote_xpra_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({"host": "localhost"})

    def test_missing_proxy_command_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({"host": "localhost", "remote_xpra": ["/usr/bin/xpra"]})

    def test_missing_display_as_args_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({
                "host": "localhost",
                "remote_xpra": ["/usr/bin/xpra"],
                "proxy_command": ["_proxy_start"],
            })


def start_fake_win32_agent() -> list[int]:
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
    requests: list[int] = []
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
            while header := read(handle, 4):
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


SSH_AGENT_FAILURE_REPLY = bytes([0, 0, 0, 1, 5])
NO_IDENTITIES_REPLY = bytes([0, 0, 0, 5, 12, 0, 0, 0, 0])


class FakePageantConnection:
    """
    Behaves like `paramiko.win_pageant.PageantConnection`:
    `send` processes the whole query and returns `None`, `recv` reads the buffered response.
    """

    def __init__(self):
        self.requests: list[bytes] = []
        self.response = b""
        self.lost = False

    def send(self, data: bytes) -> None:
        self.requests.append(data[4:])
        self.response = b"" if self.lost else NO_IDENTITIES_REPLY

    def recv(self, n: int) -> bytes:
        data, self.response = self.response[:n], self.response[n:]
        return data

    def close(self) -> None:
        pass


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
        self.server = AgentForwardingServer()

    def tearDown(self):
        self.server.close()

    def open_channel(self, agent: str, override: bool = True):
        from xpra.net.ssh.paramiko import client
        crf = client.ChannelRunFactory(self.server.client_transport, ["_proxy_start"], ["xpra"], [], [":100"],
                                       {"agent": agent})
        with (
            patch.object(client.ChannelRunFactory, "get_xpra_command", return_value="xpra _proxy_start :100"),
            patch.object(client, "AGENT_OVERRIDE", override),
        ):
            chan = crf.open()
        assert self.server.exec_event.wait(10)
        assert self.server.exec_command == b"xpra _proxy_start :100"
        return chan

    def test_agent_disabled(self):
        self.open_channel("no")
        assert not self.server.agent_forwarding_requested

    def test_agent_override_default(self):
        from xpra.net.ssh.paramiko import client
        assert client.AGENT_OVERRIDE == (os.name == "nt")

    def test_agent_enabled(self):
        self.open_channel("yes")
        assert self.server.agent_forwarding_requested

    def test_agent_override_disabled(self):
        with patch("paramiko.agent.AgentRequestHandler") as handler:
            self.open_channel("yes", override=False)
        handler.assert_called_once()

    def test_no_local_agent(self):
        with patch("xpra.net.ssh.paramiko.agent.get_agent_connection", return_value=None):
            self.open_channel("yes")
            assert self.server.query_forwarded_agent(5) == SSH_AGENT_FAILURE_REPLY
            # the channel is still usable:
            assert self.server.query_forwarded_agent(5) == SSH_AGENT_FAILURE_REPLY

    def test_pageant_style_agent(self):
        agent = FakePageantConnection()
        with patch("xpra.net.ssh.paramiko.agent.get_agent_connection", return_value=agent):
            self.open_channel("yes")
            assert self.server.query_forwarded_agent(5) == NO_IDENTITIES_REPLY
        assert agent.requests == [bytes([11])]

    def test_lost_local_agent(self):
        agent = FakePageantConnection()
        agent.lost = True
        with patch("xpra.net.ssh.paramiko.agent.get_agent_connection", return_value=agent):
            self.open_channel("yes")
            assert self.server.query_forwarded_agent(5) == SSH_AGENT_FAILURE_REPLY

    @unittest.skipUnless(os.name == "nt", "MS Windows only")
    def test_win32_openssh_agent_forwarding(self):
        # the fix for #4353: the forwarded agent request gets a reply
        requests = start_fake_win32_agent()
        self.open_channel("yes")
        reply = self.server.query_forwarded_agent(5)
        # IDENTITIES_ANSWER, from either the fake agent or a real one:
        assert reply[4:5] == bytes([12]), f"unexpected reply {reply!r}"
        if requests:
            assert reply == NO_IDENTITIES_REPLY
            assert requests == [11]

    @unittest.skipUnless(os.name == "nt", "MS Windows only")
    def test_paramiko_win32_agent_forwarding_hangs(self):
        """
        Reproducer for #4353, this is a paramiko bug:
        the local agent can be reached directly, but not through `AgentRequestHandler`.
        If this test starts failing, paramiko has been fixed
        and `XPRA_SSH_AGENT_OVERRIDE` may no longer be needed.
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


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestAgentRelay(unittest.TestCase):

    def test_recv_message_chunked(self):
        from xpra.net.ssh.paramiko.agent import recv_message
        data = bytearray(NO_IDENTITIES_REPLY)

        def recv(n: int) -> bytes:
            chunk = bytes(data[:min(n, 2)])
            del data[:len(chunk)]
            return chunk
        assert recv_message(recv) == NO_IDENTITIES_REPLY

    def test_recv_message_truncated(self):
        from xpra.net.ssh.paramiko.agent import recv_message
        data = bytearray(NO_IDENTITIES_REPLY[:-1])

        def recv(n: int) -> bytes:
            chunk = bytes(data[:n])
            del data[:n]
            return chunk
        assert recv_message(recv) == b""

    def test_recv_message_too_large(self):
        import struct
        from xpra.net.ssh.paramiko.agent import recv_message, MAX_MESSAGE_SIZE
        header = struct.pack(">I", MAX_MESSAGE_SIZE + 1)
        with self.assertRaises(ValueError):
            recv_message(lambda n: header[:n])

    def test_send_all_partial_writes(self):
        from xpra.net.ssh.paramiko.agent import send_all
        written = []

        class Pipe:
            def send(self, data):
                written.append(data[:3])
                return len(written[-1])
        send_all(Pipe(), NO_IDENTITIES_REPLY)
        assert b"".join(written) == NO_IDENTITIES_REPLY


def main():
    unittest.main()


if __name__ == "__main__":
    main()
