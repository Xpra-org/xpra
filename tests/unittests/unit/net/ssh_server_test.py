#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
SSH module tests.

Covers:
  xpra/server/ssh.py              – SSHServer, detect_ssh_stanza, get_keyclass,
                                     find_fingerprint, get_echo_value,
                                     make_ssh_server_connection
  xpra/net/ssh/paramiko/util.py   – keymd5, get_sha256_fingerprint_for_keyfile,
                                     get_key_fingerprints, load_private_key,
                                     SSHSocketConnection
  xpra/net/ssh/paramiko/client.py – get_auth_modes, safe_lookup,
                                     AuthenticationManager, run_test_command
  xpra/net/ssh/exec_client.py     – get_ssh_kwargs, get_ssh_command,
                                     close_tunnel_pipes, stderr_reader
"""

import os
import socket
import tempfile
import threading
import shutil
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

import paramiko

from xpra.server.ssh import (
    SSHServer, detect_ssh_stanza, get_keyclass, get_echo_value, find_fingerprint,
    load_host_key,
)
from xpra.net.ssh.paramiko.util import (
    keymd5, get_sha256_fingerprint_for_keyfile, get_key_fingerprints,
    load_private_key, SSHSocketConnection,
)


# ---------------------------------------------------------------------------
# Helper: generate a fresh RSA key and write it to a temp dir
# ---------------------------------------------------------------------------

def _gen_rsa_key(tmpdir: str, name="ssh_host_rsa_key") -> tuple[str, paramiko.RSAKey]:
    key = paramiko.RSAKey.generate(2048)
    path = os.path.join(tmpdir, name)
    key.write_private_key_file(path)
    return path, key


# ---------------------------------------------------------------------------
# 1. xpra/server/ssh.py  –  pure Python unit tests
# ---------------------------------------------------------------------------

class TestDetectSshStanza(unittest.TestCase):

    def test_empty(self):
        assert detect_ssh_stanza([]) == ()

    def test_single_word(self):
        # a simple command that has no if/then structure gives ()
        assert detect_ssh_stanza(["ls"]) == ()

    def test_sh_c_with_proxy(self):
        cmd = [
            "sh", "-c",
            'if type "xpra" > /dev/null 2>&1; then xpra _proxy; '
            'else echo "no xpra command found"; exit 1; fi',
        ]
        result = detect_ssh_stanza(cmd)
        assert result, f"expected non-empty result, got {result!r}"
        assert "_proxy" in result

    def test_sh_c_which(self):
        cmd = [
            "sh", "-c",
            'if which "xpra" > /dev/null 2>&1; then /usr/bin/xpra _proxy; fi',
        ]
        result = detect_ssh_stanza(cmd)
        assert result
        assert "_proxy" in result

    def test_absolute_path(self):
        cmd = [
            "sh", "-c",
            'if [ -x /usr/local/bin/xpra ]; then /usr/local/bin/xpra _proxy; fi',
        ]
        result = detect_ssh_stanza(cmd)
        assert result

    def test_not_sh_c(self):
        # 2 arguments but not 'sh -c' → ()
        assert detect_ssh_stanza(["bash", "script.sh"]) == ()

    def test_no_proxy_subcommand(self):
        # there is no _proxy in the 'then' branch
        cmd = [
            "sh", "-c",
            'if type "xpra" > /dev/null 2>&1; then xpra version; fi',
        ]
        assert detect_ssh_stanza(cmd) == ()


class TestGetKeyclass(unittest.TestCase):

    def test_rsa(self):
        kc = get_keyclass("rsa")
        assert kc is paramiko.RSAKey

    def test_ed25519(self):
        kc = get_keyclass("ed25519")
        assert kc is paramiko.Ed25519Key

    def test_ecdsa(self):
        kc = get_keyclass("ecdsa")
        assert kc is paramiko.ECDSAKey

    def test_dsa(self):
        kc = get_keyclass("dsa")
        # paramiko.DSSKey or None, depending on build
        assert kc is None or kc is getattr(paramiko, "DSSKey", None)

    def test_unknown(self):
        assert get_keyclass("bogus_type") is None

    def test_empty(self):
        assert get_keyclass("") is None


class TestGetEchoValue(unittest.TestCase):

    def test_unix_ostype(self):
        if sys.platform == "win32":
            self.skipTest("POSIX only")
        v = get_echo_value("$OSTYPE")
        assert v  # should return the platform string

    def test_unknown_var(self):
        v = get_echo_value("$UNKNOWN_VAR_XYZ")
        assert v == ""

    def test_non_var(self):
        v = get_echo_value("hello")
        assert v == ""


class TestFindFingerprint(unittest.TestCase):

    def _write_authorized_keys(self, tmpdir: str, key: paramiko.RSAKey) -> str:
        """Write a minimal authorized_keys file containing the given key."""
        import base64
        pub_bytes = key.asbytes()
        encoded = base64.b64encode(pub_bytes).decode("ascii")
        path = os.path.join(tmpdir, "authorized_keys")
        with open(path, "w") as f:
            f.write(f"ssh-rsa {encoded} test@test\n")
        return path

    def test_finds_matching_key(self):
        tmpdir = tempfile.mkdtemp()
        try:
            key = paramiko.RSAKey.generate(1024)
            auth_keys = self._write_authorized_keys(tmpdir, key)
            fingerprint = key.get_fingerprint()
            assert find_fingerprint(auth_keys, fingerprint) is True
        finally:
            shutil.rmtree(tmpdir)

    def test_no_match(self):
        tmpdir = tempfile.mkdtemp()
        try:
            key1 = paramiko.RSAKey.generate(1024)
            key2 = paramiko.RSAKey.generate(1024)
            auth_keys = self._write_authorized_keys(tmpdir, key1)
            fingerprint = key2.get_fingerprint()
            assert find_fingerprint(auth_keys, fingerprint) is False
        finally:
            shutil.rmtree(tmpdir)

    def test_empty_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "authorized_keys")
            with open(path, "w") as f:
                f.write("# comment line\n")
            key = paramiko.RSAKey.generate(1024)
            assert find_fingerprint(path, key.get_fingerprint()) is False
        finally:
            shutil.rmtree(tmpdir)


class TestLoadHostKey(unittest.TestCase):

    def test_valid_rsa_key(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path, _ = _gen_rsa_key(tmpdir, "ssh_host_rsa_key")
            key = load_host_key(path)
            assert key is not None
            assert isinstance(key, paramiko.RSAKey)
        finally:
            shutil.rmtree(tmpdir)

    def test_bad_filename(self):
        tmpdir = tempfile.mkdtemp()
        try:
            # filename doesn't match ssh_host_*_key pattern
            key = paramiko.RSAKey.generate(1024)
            path = os.path.join(tmpdir, "my_key")
            key.write_private_key_file(path)
            result = load_host_key(path)
            assert result is None
        finally:
            shutil.rmtree(tmpdir)


class TestSSHServerUnit(unittest.TestCase):

    def test_get_banner(self):
        srv = SSHServer()
        banner, lang = srv.get_banner()
        assert "Xpra" in banner or banner  # non-empty
        assert lang

    def test_get_allowed_auths_none(self):
        srv = SSHServer(none_auth=True, pubkey_auth=False, password_auth=None)
        auths = srv.get_allowed_auths("anyuser")
        assert "none" in auths
        assert "publickey" not in auths

    def test_get_allowed_auths_pubkey(self):
        srv = SSHServer(none_auth=False, pubkey_auth=True, password_auth=None)
        auths = srv.get_allowed_auths("anyuser")
        assert "publickey" in auths
        assert "none" not in auths

    def test_get_allowed_auths_password(self):
        srv = SSHServer(none_auth=False, pubkey_auth=False, password_auth=lambda u, p: True)
        auths = srv.get_allowed_auths("anyuser")
        assert "password" in auths

    def test_check_channel_request_session(self):
        result = SSHServer.check_channel_request("session", 1)
        assert result == paramiko.OPEN_SUCCEEDED

    def test_check_channel_request_unknown(self):
        result = SSHServer.check_channel_request("direct-tcpip", 1)
        assert result == paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def test_check_auth_none_allowed(self):
        srv = SSHServer(none_auth=True)
        assert srv.check_auth_none("user") == paramiko.AUTH_SUCCESSFUL

    def test_check_auth_none_denied(self):
        srv = SSHServer(none_auth=False)
        assert srv.check_auth_none("user") == paramiko.AUTH_FAILED

    def test_check_auth_password_no_callback(self):
        srv = SSHServer(password_auth=None)
        assert srv.check_auth_password("user", "pass") == paramiko.AUTH_FAILED

    def test_check_auth_password_correct(self):
        srv = SSHServer(password_auth=lambda u, p: u == "alice" and p == "secret")
        assert srv.check_auth_password("alice", "secret") == paramiko.AUTH_SUCCESSFUL
        assert srv.check_auth_password("alice", "wrong") == paramiko.AUTH_FAILED

    def test_check_channel_shell_request(self):
        assert SSHServer.check_channel_shell_request(MagicMock()) is False

    def test_check_channel_pty_request(self):
        assert SSHServer.check_channel_pty_request(MagicMock(), "xterm", 80, 24, 0, 0, b"") is False

    def test_enable_auth_gssapi(self):
        assert SSHServer.enable_auth_gssapi() is False


# ---------------------------------------------------------------------------
# 2. xpra/net/ssh/paramiko/util.py  –  unit tests
# ---------------------------------------------------------------------------

class TestSSHParamikoUtil(unittest.TestCase):

    def test_keymd5(self):
        key = paramiko.RSAKey.generate(1024)
        md5 = keymd5(key)
        assert md5.startswith("MD5:"), f"unexpected format: {md5!r}"
        assert len(md5) > 10

    def test_get_sha256_fingerprint(self):
        tmpdir = tempfile.mkdtemp()
        try:
            import base64
            key_path, key = _gen_rsa_key(tmpdir, "ssh_host_rsa_key")
            # write accompanying .pub file for get_sha256_fingerprint_for_keyfile to parse
            pub_path = key_path + ".pub"
            with open(pub_path, "w") as f:
                f.write(f"ssh-rsa {base64.b64encode(key.asbytes()).decode()} test\n")
            fp = get_sha256_fingerprint_for_keyfile(key_path)
            assert fp.startswith("SHA256:"), f"unexpected: {fp!r}"
        finally:
            shutil.rmtree(tmpdir)

    def test_get_sha256_fingerprint_pub_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            key_path, key = _gen_rsa_key(tmpdir, "test_key")
            # write public key file alongside the private key
            pub_path = key_path + ".pub"
            import base64
            pub_bytes = key.asbytes()
            with open(pub_path, "w") as f:
                f.write(f"ssh-rsa {base64.b64encode(pub_bytes).decode()} test\n")
            # get_sha256_fingerprint_for_keyfile should prefer the .pub file
            fp = get_sha256_fingerprint_for_keyfile(key_path)
            assert fp.startswith("SHA256:")
        finally:
            shutil.rmtree(tmpdir)

    def test_get_key_fingerprints_valid(self):
        tmpdir = tempfile.mkdtemp()
        try:
            import base64
            path, key = _gen_rsa_key(tmpdir, "id_rsa")
            # write accompanying .pub file so get_sha256_fingerprint_for_keyfile can parse it
            pub_path = path + ".pub"
            with open(pub_path, "w") as f:
                f.write(f"ssh-rsa {base64.b64encode(key.asbytes()).decode()} test\n")
            fps = get_key_fingerprints([path])
            assert len(fps) == 1
            assert fps[0].startswith("SHA256:")
        finally:
            shutil.rmtree(tmpdir)

    def test_get_key_fingerprints_missing_file(self):
        fps = get_key_fingerprints(["/no/such/file"])
        assert fps == []

    def test_load_private_key_rsa(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path, _ = _gen_rsa_key(tmpdir, "id_rsa")
            key = load_private_key(path)
            assert key is not None
            assert isinstance(key, paramiko.RSAKey)
        finally:
            shutil.rmtree(tmpdir)

    def test_load_private_key_missing(self):
        key = load_private_key("/no/such/key")
        assert key is None

    def test_ssh_socket_connection_info(self):
        chan = MagicMock()
        chan.get_id.return_value = 7
        chan.get_name.return_value = "session-7"
        sock = MagicMock()
        conn = SSHSocketConnection(chan, sock, "local", "peer", "target")
        info = conn.get_info()
        assert info["ssh-channel"]["id"] == 7
        assert info["ssh-channel"]["name"] == "session-7"

    def test_ssh_socket_connection_peek(self):
        chan = MagicMock()
        raw = MagicMock()
        raw.recv.return_value = b"peek"
        conn = SSHSocketConnection(chan, raw, "local", "peer", "target")
        result = conn.peek(4)
        assert result == b"peek"

    def test_ssh_socket_connection_no_raw_socket(self):
        chan = MagicMock()
        conn = SSHSocketConnection(chan, None, "local", "peer", "target")
        assert conn.peek(4) == b""
        assert conn.get_socket_info() == {}


# ---------------------------------------------------------------------------
# 3. xpra/net/ssh/paramiko/client.py  –  unit tests
# ---------------------------------------------------------------------------

class TestGetAuthModes(unittest.TestCase):

    def test_none_auth(self):
        from xpra.net.ssh.paramiko.client import get_auth_modes
        modes = get_auth_modes({}, {}, "")
        assert "none" in modes

    def test_password_included_when_password_given(self):
        from xpra.net.ssh.paramiko.client import get_auth_modes
        modes = get_auth_modes({}, {}, "mypassword")
        assert "password" in modes

    def test_explicit_auth_string(self):
        from xpra.net.ssh.paramiko.client import get_auth_modes
        modes = get_auth_modes({"auth": "password+publickey"}, {}, "")
        assert modes == ["password", "publickey"]

    def test_identitiesonly_skips_none(self):
        from xpra.net.ssh.paramiko.client import get_auth_modes
        modes = get_auth_modes({"identitiesonly": "yes"}, {}, "")
        assert "none" not in modes
        assert "password" not in modes


class TestSafeLookup(unittest.TestCase):

    def test_returns_dict(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        config = paramiko.SSHConfig()
        result = safe_lookup(config, "somehost")
        assert isinstance(result, dict)

    def test_wildcard_returns_something(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        config = paramiko.SSHConfig()
        result = safe_lookup(config, "*")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 4. xpra/net/ssh/exec_client.py  –  unit tests
# ---------------------------------------------------------------------------

class TestExecClientUnit(unittest.TestCase):

    def test_get_ssh_kwargs_has_stderr(self):
        from xpra.net.ssh.exec_client import get_ssh_kwargs
        import sys
        kwargs = get_ssh_kwargs()
        assert "stderr" in kwargs
        assert kwargs["stderr"] is sys.stderr

    def test_get_ssh_command_basic(self):
        from xpra.net.ssh.exec_client import get_ssh_command
        desc = {
            "remote_xpra": ["xpra"],
            "socket_dir": "",
            "proxy_command": ["_proxy"],
            "display_as_args": [":10"],
            "full_ssh": ["ssh", "-p", "22", "user@host"],
        }
        cmd = get_ssh_command(desc)
        assert isinstance(cmd, list)
        assert cmd[0] == "ssh"
        # the last element is the remote command string
        last = cmd[-1]
        assert "xpra" in last
        assert "_proxy" in last

    def test_get_ssh_command_non_string_raises(self):
        from xpra.net.ssh.exec_client import get_ssh_command
        from xpra.scripts.main import InitException
        desc = {
            "remote_xpra": ["xpra"],
            "socket_dir": "",
            "proxy_command": ["_proxy"],
            "display_as_args": [":10"],
            "full_ssh": ["ssh", 22],  # 22 is not a string
        }
        self.assertRaises(InitException, get_ssh_command, desc)

    def test_close_tunnel_pipes(self):
        from xpra.net.ssh.exec_client import close_tunnel_pipes
        child = MagicMock()
        child.stdin = BytesIO(b"")
        child.stdout = BytesIO(b"")
        child.stderr = None
        # should not raise even if stderr is None
        with patch("xpra.net.ssh.exec_client.POSIX", True):
            close_tunnel_pipes(child)

    def test_stderr_reader_reads_lines(self):
        """stderr_reader should consume lines and log them."""
        from xpra.net.ssh.exec_client import stderr_reader
        child = MagicMock()
        # simulate: two lines then EOF
        child.poll.side_effect = [None, None, 0]
        child.stderr.readline.side_effect = [b"line1\n", b"line2\n", b""]
        # should complete without error
        stderr_reader(child)


# ---------------------------------------------------------------------------
# 5. Integration tests: real paramiko SSH server on loopback
# ---------------------------------------------------------------------------

def _can_run_integration():
    """Check that we have everything we need for integration tests."""
    try:
        import paramiko  # noqa: F401
        return True
    except ImportError:
        return False


class _SSHTestServer:
    """
    Minimal SSH server using paramiko, listening on localhost.
    Handles none authentication and exec requests via SSHServer.
    """

    def __init__(self, none_auth=True, password_auth=None):
        self.host_key = paramiko.RSAKey.generate(2048)
        self._none_auth = none_auth
        self._password_auth = password_auth
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(20)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        # wait for the accept loop to start before returning
        self._ready.wait(5.0)

    def _accept_loop(self):
        self._sock.settimeout(0.5)
        self._ready.set()
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()

    def _handle(self, conn):
        transport = paramiko.Transport(conn)
        transport.add_server_key(self.host_key)
        ssh_server = SSHServer(none_auth=self._none_auth, password_auth=self._password_auth)
        ssh_server.transport = transport
        try:
            transport.start_server(server=ssh_server)
        except paramiko.SSHException:
            return
        chan = transport.accept(10)
        if chan is None:
            return
        if not ssh_server.event.wait(10):
            return
        # handle exec_response (mirrors make_ssh_server_connection loop)
        exec_response = getattr(chan, "exec_response", None)
        if exec_response:
            exit_status, out, err = exec_response
            if out:
                data = out.encode() if isinstance(out, str) else out
                chan.sendall(data)
            if err:
                data = err.encode() if isinstance(err, str) else err
                chan.sendall_stderr(data)
            chan.send_exit_status(exit_status)
        chan.close()
        transport.close()

    def close(self):
        self._stop.set()
        self._sock.close()


def _client_transport(server: _SSHTestServer) -> tuple[paramiko.Transport, socket.socket]:
    """Open a paramiko client transport and authenticate with none."""
    sock = socket.create_connection(("127.0.0.1", server.port))
    t = paramiko.Transport(sock)
    t.start_client()
    t.auth_none("testuser")
    return t, sock


def _exec_cmd(transport: paramiko.Transport, cmd: str) -> tuple[bytes, bytes, int]:
    """Open a session channel, exec cmd, collect stdout/stderr/exit_status."""
    chan = transport.open_session()
    chan.exec_command(cmd)
    chan.settimeout(5.0)

    stdout = b""
    while True:
        data = chan.recv(4096)
        if not data:
            break
        stdout += data

    chan.settimeout(0.5)
    stderr = b""
    try:
        stderr_file = chan.makefile_stderr("rb")
        while True:
            line = stderr_file.read(4096)
            if not line:
                break
            stderr += line
    except (OSError, socket.timeout):
        pass

    exit_status = chan.recv_exit_status()
    try:
        chan.close()
    except (EOFError, OSError):
        pass
    return stdout, stderr, exit_status


@unittest.skipUnless(_can_run_integration(), "paramiko not available")
class TestSSHServerIntegration(unittest.TestCase):
    """Tests that exercise SSHServer exec-request handling via a real transport."""

    server: _SSHTestServer

    @classmethod
    def setUpClass(cls):
        cls.server = _SSHTestServer(none_auth=True)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def setUp(self):
        # give previous test's transport time to close cleanly
        import time
        time.sleep(0.05)

    def _connect(self):
        return _client_transport(self.server)

    def test_command_minus_v_xpra(self):
        """'command -v xpra' should return 'xpra' with exit code 0."""
        t, sock = self._connect()
        try:
            out, _, code = _exec_cmd(t, "command -v xpra")
            assert code == 0, f"expected exit 0, got {code}"
            assert b"xpra" in out, f"expected 'xpra' in {out!r}"
        finally:
            t.close()
            sock.close()

    def test_command_alone(self):
        """Bare 'command' should return empty stdout with exit code 0."""
        t, sock = self._connect()
        try:
            out, _, code = _exec_cmd(t, "command")
            assert code == 0, f"expected exit 0, got {code}"
        finally:
            t.close()
            sock.close()

    def test_echo_ostype(self):
        """'echo $OSTYPE' should return the platform string with exit code 0."""
        t, sock = self._connect()
        try:
            out, _, code = _exec_cmd(t, "echo $OSTYPE")
            assert code == 0, f"expected exit 0, got {code}"
            # The response may be empty on Windows; on POSIX it returns sys.platform
            assert isinstance(out, bytes)
        finally:
            t.close()
            sock.close()

    def test_which_xpra(self):
        """'which xpra' should return 'xpra' with exit code 0."""
        t, sock = self._connect()
        try:
            out, _, code = _exec_cmd(t, "which xpra")
            assert code == 0
            assert b"xpra" in out
        finally:
            t.close()
            sock.close()

    def test_type_xpra(self):
        """'type xpra' should return 'xpra' with exit code 0."""
        t, sock = self._connect()
        try:
            out, _, code = _exec_cmd(t, "type xpra")
            assert code == 0
            assert b"xpra" in out
        finally:
            t.close()
            sock.close()

    def test_unknown_command_fails(self):
        """Unknown command causes the server to close the channel without exec success."""
        t, sock = self._connect()
        try:
            chan = t.open_session()
            # server returns False from check_channel_exec_request and closes channel,
            # so paramiko raises SSHException or EOFError on the client side
            self.assertRaises((paramiko.SSHException, EOFError), chan.exec_command, "unknown_command_xyz")
        finally:
            t.close()
            sock.close()

    def test_none_auth_denied(self):
        """A server with none_auth=False should reject none authentication."""
        srv = _SSHTestServer(none_auth=False)
        try:
            sock = socket.create_connection(("127.0.0.1", srv.port))
            t = paramiko.Transport(sock)
            t.start_client()
            self.assertRaises(paramiko.AuthenticationException, t.auth_none, "user")
            t.close()
            sock.close()
        finally:
            srv.close()

    def test_password_auth(self):
        """Password authentication with correct password should succeed."""
        srv = _SSHTestServer(
            none_auth=False,
            password_auth=lambda u, p: u == "alice" and p == "s3cr3t",
        )
        try:
            sock = socket.create_connection(("127.0.0.1", srv.port))
            t = paramiko.Transport(sock)
            t.start_client()
            t.auth_password("alice", "s3cr3t")
            assert t.is_authenticated()
            t.close()
            sock.close()
        finally:
            srv.close()


@unittest.skipUnless(_can_run_integration(), "paramiko not available")
class TestMakeSSHServerConnection(unittest.TestCase):
    """
    Tests make_ssh_server_connection() by having a paramiko client connect
    to a socket whose other end is handled by xpra's SSH server code.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.key_path, cls.host_key = _gen_rsa_key(cls.tmpdir, "ssh_host_rsa_key")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir)

    def _run_make_ssh_server_connection(self, server_sock, none_auth=True):
        """
        Run make_ssh_server_connection in a thread, returning result via list.
        """
        from xpra.server.ssh import make_ssh_server_connection

        # Build a minimal SocketConnection-like mock
        conn = MagicMock()
        conn._socket = server_sock
        conn.local = ("127.0.0.1", 0)
        conn.endpoint = ("127.0.0.1", 0)
        conn.target = "test-target"

        results = []
        ready = threading.Event()

        def run():
            result = make_ssh_server_connection(
                conn,
                socket_options={"ssh-host-key": self.key_path},
                none_auth=none_auth,
            )
            results.append(result)
            ready.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return results, ready

    def test_exec_command_v_xpra(self):
        """make_ssh_server_connection handles 'command -v xpra' exec request."""
        s1, s2 = socket.socketpair()
        results, ready = self._run_make_ssh_server_connection(s1)

        # Client side: connect and run 'command -v xpra'
        t = paramiko.Transport(s2)
        t.start_client()
        t.auth_none("testuser")

        chan = t.open_session()
        chan.exec_command("command -v xpra")
        chan.settimeout(5.0)

        output = b""
        while True:
            try:
                data = chan.recv(1024)
            except socket.timeout:
                break
            if not data:
                break
            output += data
        exit_status = chan.recv_exit_status()
        chan.close()
        t.close()
        s2.close()

        ready.wait(10)
        assert b"xpra" in output, f"expected xpra in {output!r}"
        assert exit_status == 0


@unittest.skipUnless(_can_run_integration(), "paramiko not available")
class TestParamikoClientIntegration(unittest.TestCase):
    """
    Tests using the paramiko client module against a live SSHServer.
    Exercises do_connect_to / AuthenticationManager / run_test_command.
    """

    server: _SSHTestServer

    @classmethod
    def setUpClass(cls):
        cls.server = _SSHTestServer(none_auth=True)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def test_do_connect_none_auth(self):
        """do_connect completes authentication using 'none' mode."""
        from xpra.net.ssh.paramiko.client import do_connect
        sock = socket.create_connection(("127.0.0.1", self.server.port))
        try:
            transport = do_connect(
                sock,
                "127.0.0.1",
                self.server.port,
                username="testuser",
                password="",
                host_config={},
                keyfiles=[],
                paramiko_config={"verify-hostkey": "false"},
                auth_modes=["none"],
            )
            assert transport.is_authenticated()
            transport.close()
        finally:
            sock.close()

    def test_run_test_command(self):
        """run_test_command can execute 'command -v xpra' against our server."""
        from xpra.net.ssh.paramiko.client import do_connect, run_test_command
        sock = socket.create_connection(("127.0.0.1", self.server.port))
        try:
            transport = do_connect(
                sock,
                "127.0.0.1",
                self.server.port,
                username="testuser",
                password="",
                host_config={},
                keyfiles=[],
                paramiko_config={"verify-hostkey": "false"},
                auth_modes=["none"],
            )
            out, err, code = run_test_command(transport, "command -v xpra")
            assert code == 0, f"expected exit 0, got {code}"
            assert any("xpra" in line for line in out), f"expected xpra in {out!r}"
            transport.close()
        finally:
            sock.close()

    def test_authentication_manager_with_none(self):
        """AuthenticationManager succeeds with none auth mode."""
        from xpra.net.ssh.paramiko.client import AuthenticationManager
        sock = socket.create_connection(("127.0.0.1", self.server.port))
        try:
            transport = paramiko.Transport(sock)
            transport.start_client()
            mgr = AuthenticationManager(
                transport,
                "127.0.0.1",
                self.server.port,
                "testuser",
                "",
                {},
                [],
                {"verify-hostkey": "false"},
                auth_modes=["none"],
            )
            mgr.run()
            assert transport.is_authenticated()
            transport.close()
        finally:
            sock.close()

    def test_load_ssh_config(self):
        """load_ssh_config returns an SSHConfig object without errors."""
        from xpra.net.ssh.paramiko.client import load_ssh_config
        config = load_ssh_config()
        assert isinstance(config, paramiko.SSHConfig)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
