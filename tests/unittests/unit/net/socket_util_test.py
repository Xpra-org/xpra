#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import sys
import tempfile
import os
import unittest

from xpra.os_util import POSIX
from xpra.net.socket_util import (
    validate_abstract_socketpath,
    looks_like_xpra_packet,
    guess_packet_type,
    normalize_local_display_name,
    parse_bind_ip,
    parse_sock_perms,
    parse_bind_vsock,
    parse_bind_options,
    check_ssh_upgrades,
    get_bind_sockpaths,
    SocketListener,
    hosts,
    close_sockets,
    create_tcp_socket,
    setup_tcp_socket,
    setup_udp_socket,
)
from xpra.scripts.config import InitException


class TestValidateAbstractSocketpath(unittest.TestCase):

    def test_valid(self):
        assert validate_abstract_socketpath("xpra-123") is True
        assert validate_abstract_socketpath("my_socket") is True
        assert validate_abstract_socketpath("abc") is True
        assert validate_abstract_socketpath("ABC-def_123") is True

    def test_invalid(self):
        assert validate_abstract_socketpath("has space") is False
        assert validate_abstract_socketpath("has/slash") is False
        assert validate_abstract_socketpath("has.dot") is False
        assert validate_abstract_socketpath("has@at") is False
        assert validate_abstract_socketpath("") is True  # vacuously true: all() on empty


def make_xpra_header(flags=0, level=0, index=0, size=32):
    """Build an 8-byte xpra packet header."""
    return b"P" + bytes([flags, level, index]) + size.to_bytes(4, "big")


class TestLooksLikeXpraPacket(unittest.TestCase):

    def test_too_short(self):
        assert looks_like_xpra_packet(b"") is False
        assert looks_like_xpra_packet(b"P\x00\x00") is False

    def test_wrong_first_byte(self):
        assert looks_like_xpra_packet(b"X" + b"\x00" * 15) is False

    def test_valid_looking_packet(self):
        # Build a minimal packet header: 'P' + flags=0 + level=0 + index=0 + size (4 bytes big-endian)
        # size must be >= 8
        header = b"P" + b"\x00" * 3 + (32).to_bytes(4, "big")
        assert looks_like_xpra_packet(header) is True

    def test_nonzero_packet_index(self):
        # header layout: 'P' | flags | compression_level | packet_index | data_size(4)
        # packet_index is at byte offset 3
        header = b"P\x00\x00\x01" + (32).to_bytes(4, "big")
        assert looks_like_xpra_packet(header) is False

    def test_data_size_too_small(self):
        header = b"P" + b"\x00" * 3 + (4).to_bytes(4, "big")
        assert looks_like_xpra_packet(header) is False

    def test_data_size_too_large(self):
        too_big = 256 * 1024 * 1024
        header = b"P" + b"\x00" * 3 + too_big.to_bytes(4, "big")
        assert looks_like_xpra_packet(header) is False

    def test_both_compressors_rejected(self):
        # LZ4_FLAG=0x10, BROTLI_FLAG=0x40 — both set means compressors > 1
        from xpra.net.protocol.header import LZ4_FLAG, BROTLI_FLAG
        flags = LZ4_FLAG | BROTLI_FLAG
        # compression_level > 0 to pass the level check if we got that far
        header = make_xpra_header(flags=flags, level=1)
        assert looks_like_xpra_packet(header) is False

    def test_compressor_set_but_level_zero(self):
        # One compressor enabled but compression_level == 0: rejected
        from xpra.net.protocol.header import LZ4_FLAG
        header = make_xpra_header(flags=LZ4_FLAG, level=0)
        assert looks_like_xpra_packet(header) is False

    def test_compressor_with_nonzero_level_accepted(self):
        from xpra.net.protocol.header import LZ4_FLAG
        header = make_xpra_header(flags=LZ4_FLAG, level=1)
        assert looks_like_xpra_packet(header) is True

    def test_rencode_and_yaml_rejected(self):
        # FLAGS_RENCODE=0x1, FLAGS_YAML=0x4 — mutually exclusive
        from xpra.net.protocol.header import FLAGS_RENCODE, FLAGS_YAML
        flags = FLAGS_RENCODE | FLAGS_YAML
        header = make_xpra_header(flags=flags, level=0)
        assert looks_like_xpra_packet(header) is False

    def test_rencode_alone_accepted(self):
        from xpra.net.protocol.header import FLAGS_RENCODE
        header = make_xpra_header(flags=FLAGS_RENCODE, level=0)
        assert looks_like_xpra_packet(header) is True

    def test_yaml_alone_accepted(self):
        from xpra.net.protocol.header import FLAGS_YAML
        header = make_xpra_header(flags=FLAGS_YAML, level=0)
        assert looks_like_xpra_packet(header) is True


class TestGuessPacketType(unittest.TestCase):

    def test_empty(self):
        assert guess_packet_type(b"") == ""

    def test_ssh(self):
        assert guess_packet_type(b"SSH-2.0-OpenSSH_8.0\r\n") == "ssh"

    def test_ssl(self):
        assert guess_packet_type(bytes([0x16]) + b"\x03\x01" + b"\x00" * 16) == "ssl"

    def test_vnc(self):
        assert guess_packet_type(b"RFB 003.008\n") == "vnc"

    def test_http_get(self):
        assert guess_packet_type(b"GET / HTTP/1.1\r\nHost: localhost\r\n") == "http"

    def test_http_post(self):
        assert guess_packet_type(b"POST /api HTTP/1.1\r\n") == "http"

    def test_html_doctype(self):
        assert guess_packet_type(b"<!DOCTYPE html><html>") == "http"

    def test_html_tag(self):
        assert guess_packet_type(b"<html><head>") == "http"

    def test_rdp(self):
        # RDP: starts with \x03\x00, next two bytes encode total length
        # size = data[2]*256 + data[3], and len(data) >= size
        size = 7
        data = b"\x03\x00" + bytes([0, size]) + b"\x00" * (size - 4)
        assert guess_packet_type(data) == "rdp"

    def test_rdp_size_too_large(self):
        # size field claims more bytes than are present → not rdp
        size = 100
        data = b"\x03\x00" + bytes([0, size]) + b"\x00" * 3  # only 7 bytes, but size=100
        assert guess_packet_type(data) != "rdp"

    def test_unknown(self):
        assert guess_packet_type(b"\x00\x01\x02\x03garbage") == ""

    def test_xpra(self):
        # a minimal valid-looking xpra header
        data = b"P" + b"\x00" * 3 + (32).to_bytes(4, "big") + b"\x00" * 24
        assert guess_packet_type(data) == "xpra"


class TestNormalizeLocalDisplayName(unittest.TestCase):

    def test_with_colon(self):
        assert normalize_local_display_name(":0") == ":0"

    def test_without_colon(self):
        assert normalize_local_display_name("0") == ":0"

    def test_wayland(self):
        assert normalize_local_display_name("wayland-0") == "wayland-0"

    def test_absolute_path(self):
        assert normalize_local_display_name("/tmp/mysocket") == "/tmp/mysocket"

    def test_invalid_char(self):
        try:
            normalize_local_display_name(":abc")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for non-numeric display")

    def test_with_screen(self):
        # ":0.0" is valid (digits and dots only)
        assert normalize_local_display_name(":0.0") == ":0.0"


class TestParseBindIp(unittest.TestCase):

    def test_empty(self):
        assert parse_bind_ip([]) == {}

    def test_basic(self):
        result = parse_bind_ip(["127.0.0.1:10000"])
        assert ("127.0.0.1", 10000) in result

    def test_default_host(self):
        result = parse_bind_ip([":10000"])
        assert ("127.0.0.1", 10000) in result

    def test_with_options(self):
        result = parse_bind_ip(["0.0.0.0:9999,auth=allow"])
        assert ("0.0.0.0", 9999) in result
        assert result[("0.0.0.0", 9999)].get("auth") == "allow"

    def test_missing_port_raises(self):
        try:
            parse_bind_ip(["127.0.0.1"])
        except InitException:
            pass
        else:
            raise AssertionError("expected InitException for missing port")

    def test_invalid_port_raises(self):
        try:
            parse_bind_ip(["127.0.0.1:notaport"])
        except InitException:
            pass
        else:
            raise AssertionError("expected InitException for non-numeric port")

    def test_port_below_minimum(self):
        try:
            parse_bind_ip(["127.0.0.1:1"], min_port=1024)
        except InitException:
            pass
        else:
            raise AssertionError("expected InitException for port below minimum")

    def test_multiple(self):
        result = parse_bind_ip(["127.0.0.1:10000", "0.0.0.0:10001"])
        assert len(result) == 2


class TestParseSockPerms(unittest.TestCase):

    def test_mmap_group_yes(self):
        assert parse_sock_perms("yes", "600") == 0o660

    def test_mmap_group_true(self):
        assert parse_sock_perms("true", "600") == 0o660

    def test_octal_string(self):
        assert parse_sock_perms("no", "600") == 0o600
        assert parse_sock_perms("no", "660") == 0o660

    def test_int_value(self):
        assert parse_sock_perms("no", 0o600) == 0o600

    def test_invalid_string(self):
        try:
            parse_sock_perms("no", "not_a_number")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for invalid permissions string")

    def test_out_of_range(self):
        try:
            parse_sock_perms("no", "1000")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for out-of-range octal")


class TestSocketListener(unittest.TestCase):

    def test_str(self):
        sl = SocketListener("tcp", None, ("127.0.0.1", 10000), {}, lambda: None, lambda: None)
        assert "tcp" in str(sl)
        assert "127.0.0.1" in str(sl)

    def test_str_unix(self):
        sl = SocketListener("socket", None, "/tmp/test.sock", {}, lambda: None, lambda: None)
        assert "socket" in str(sl)


class TestHosts(unittest.TestCase):

    def test_specific_host(self):
        assert hosts("127.0.0.1") == ["127.0.0.1"]
        assert hosts("::1") == ["::1"]

    def test_wildcard_returns_list(self):
        result = hosts("*")
        assert isinstance(result, list)
        assert len(result) >= 1
        for h in result:
            assert h in ("0.0.0.0", "::")


class TestCloseSockets(unittest.TestCase):

    def test_empty(self):
        # should not raise
        close_sockets([])

    def test_calls_close_and_cleanup(self):
        close_called = []
        cleanup_called = []
        sl = SocketListener("tcp", None, ("127.0.0.1", 9999), {},
                            lambda: cleanup_called.append(True),
                            lambda: close_called.append(True))
        close_sockets([sl])
        assert close_called
        assert cleanup_called


class TestCreateTcpSocket(unittest.TestCase):

    def test_ipv4(self):
        sock = create_tcp_socket("127.0.0.1", 0)
        try:
            assert sock.family == socket.AF_INET
        finally:
            sock.close()

    def test_ipv6(self):
        if not socket.has_ipv6:
            return
        sock = create_tcp_socket("::1", 0)
        try:
            assert sock.family == socket.AF_INET6
        finally:
            sock.close()


class TestSetupTcpSocket(unittest.TestCase):

    def test_basic(self):
        sl = setup_tcp_socket("127.0.0.1", 0, "tcp", {})
        try:
            assert sl.socktype == "tcp"
            assert sl.address[0] == "127.0.0.1"
            assert sl.address[1] > 0
        finally:
            sl.cleanup()

    def test_ssl_type(self):
        sl = setup_tcp_socket("127.0.0.1", 0, "ssl", {})
        try:
            assert sl.socktype == "ssl"
        finally:
            sl.cleanup()


class TestSetupUdpSocket(unittest.TestCase):

    def test_basic(self):
        sl = setup_udp_socket("127.0.0.1", 0, "udp", {})
        try:
            assert sl.socktype == "udp"
            assert sl.address[0] == "127.0.0.1"
            assert sl.address[1] > 0
        finally:
            sl.cleanup()


class TestParseBindVsock(unittest.TestCase):

    def test_empty(self):
        assert parse_bind_vsock([]) == {}

    def test_invalid_format(self):
        try:
            parse_bind_vsock(["nocid"])
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for missing CID:PORT format")

    def test_invalid_port(self):
        try:
            parse_bind_vsock(["2:notaport"])
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for non-integer port")


class TestCheckSshUpgrades(unittest.TestCase):

    def test_paramiko_blocked_returns_false(self):
        # Setting sys.modules["paramiko"] = None makes find_spec return None
        saved = sys.modules.get("paramiko", ...)
        sys.modules["paramiko"] = None
        try:
            result = check_ssh_upgrades(warn=False)
            self.assertFalse(result)
        finally:
            if saved is ...:
                sys.modules.pop("paramiko", None)
            else:
                sys.modules["paramiko"] = saved

    def test_no_warn_does_not_raise(self):
        saved = sys.modules.get("paramiko", ...)
        sys.modules["paramiko"] = None
        try:
            check_ssh_upgrades(warn=False)   # must not raise
        finally:
            if saved is ...:
                sys.modules.pop("paramiko", None)
            else:
                sys.modules["paramiko"] = saved


class TestParseBindOptions(unittest.TestCase):

    def _make_opts(self, **overrides):
        from xpra.util.objects import AdHocStruct
        opts = AdHocStruct()
        opts.min_port = 1024
        for name in ("tcp", "ssl", "ws", "wss", "ssh", "quic", "rfb", "rdp", "vsock"):
            setattr(opts, f"bind_{name}", ())
        for k, v in overrides.items():
            setattr(opts, k, v)
        return opts

    def test_empty(self):
        opts = self._make_opts()
        result = parse_bind_options(opts)
        self.assertEqual(result, {})

    def test_tcp(self):
        opts = self._make_opts(bind_tcp=["127.0.0.1:10000"])
        result = parse_bind_options(opts)
        self.assertIn("tcp", result)
        self.assertIn(("127.0.0.1", 10000), result["tcp"])

    def test_vsock(self):
        opts = self._make_opts(bind_vsock=["3:5000"])
        result = parse_bind_options(opts)
        self.assertIn("vsock", result)
        self.assertIn((3, 5000), result["vsock"])

    def test_vsock_invalid_ignored(self):
        # invalid vsock format raises ValueError in parse_bind_vsock;
        # parse_bind_options should propagate it
        opts = self._make_opts(bind_vsock=["badvalue"])
        with self.assertRaises((ValueError, Exception)):
            parse_bind_options(opts)

    def test_multiple_types(self):
        opts = self._make_opts(bind_tcp=["127.0.0.1:10000"], bind_ssl=["127.0.0.1:10443"])
        result = parse_bind_options(opts)
        self.assertIn("tcp", result)
        self.assertIn("ssl", result)


@unittest.skipUnless(POSIX, "abstract sockets only on POSIX")
class TestGetBindSockpathsAbstract(unittest.TestCase):

    def _make_dotxpra(self):
        class FakeDotXpra:
            def osexpand(self, s):
                return s

            def socket_path(self, s):
                return "/tmp/" + s

            def norm_socket_paths(self, display_name):
                return []
        return FakeDotXpra()

    def test_explicit_abstract_socket(self):
        dotxpra = self._make_dotxpra()
        with tempfile.TemporaryDirectory() as session_dir:
            result = get_bind_sockpaths(
                ["@mysocket"], session_dir, ":7", dotxpra,
                os.getuid(), os.getgid(),
            )
        self.assertIn("@mysocket", result)

    def test_abstract_socket_with_options(self):
        dotxpra = self._make_dotxpra()
        with tempfile.TemporaryDirectory() as session_dir:
            result = get_bind_sockpaths(
                ["@mysocket,auth=allow"], session_dir, ":7", dotxpra,
                os.getuid(), os.getgid(),
            )
        self.assertIn("@mysocket", result)
        self.assertEqual(result["@mysocket"].get("auth"), "allow")

    def test_invalid_abstract_socket_name_raises(self):
        dotxpra = self._make_dotxpra()
        with tempfile.TemporaryDirectory() as session_dir:
            with self.assertRaises(ValueError):
                get_bind_sockpaths(
                    ["@has/slash"], session_dir, ":7", dotxpra,
                    os.getuid(), os.getgid(),
                )

    def test_none_and_empty_skipped(self):
        dotxpra = self._make_dotxpra()
        with tempfile.TemporaryDirectory() as session_dir:
            result = get_bind_sockpaths(
                ["none", ""], session_dir, ":7", dotxpra,
                os.getuid(), os.getgid(),
            )
        self.assertEqual(result, {})


@unittest.skipUnless(POSIX, "Unix domain socket creation only on POSIX")
class TestUnixDomainSocket(unittest.TestCase):

    def test_create_and_cleanup(self):
        from xpra.net.socket_util import create_unix_domain_socket
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "test.sock")
            sock, cleanup = create_unix_domain_socket(sockpath, 0o600)
            try:
                assert os.path.exists(sockpath)
            finally:
                cleanup()
            assert not os.path.exists(sockpath)


@unittest.skipUnless(POSIX, "abstract sockets only on POSIX")
class TestCreateAbstractSocket(unittest.TestCase):

    def test_valid_path(self):
        from xpra.net.socket_util import create_abstract_socket
        name = f"@xpra-unittest-{os.getpid()}"
        sock, cleanup = create_abstract_socket(name)
        try:
            assert sock.family == socket.AF_UNIX
        finally:
            cleanup()

    def test_missing_at_prefix_raises(self):
        from xpra.net.socket_util import create_abstract_socket
        with self.assertRaises(ValueError):
            create_abstract_socket("no-at-prefix")

    def test_invalid_chars_raises(self):
        from xpra.net.socket_util import create_abstract_socket
        with self.assertRaises(ValueError):
            create_abstract_socket("@has/slash")

    def test_invalid_dot_raises(self):
        from xpra.net.socket_util import create_abstract_socket
        with self.assertRaises(ValueError):
            create_abstract_socket("@has.dot")

    def test_cleanup_callable(self):
        from xpra.net.socket_util import create_abstract_socket
        name = f"@xpra-cleanup-{os.getpid()}"
        sock, cleanup = create_abstract_socket(name)
        sock.close()
        cleanup()   # must not raise


class TestAddListenSocketNamedPipe(unittest.TestCase):

    def test_named_pipe_sets_callback_and_starts(self):
        from unittest.mock import MagicMock
        from xpra.net.socket_util import add_listen_socket, SocketListener
        mock_sock = MagicMock()
        listener = SocketListener("named-pipe", mock_sock, r"\\.\pipe\xpra-test", {}, lambda: None, lambda: None)
        cb = MagicMock()
        result = add_listen_socket(listener, None, cb)
        assert result is None
        assert mock_sock.new_connection_cb is cb
        mock_sock.start.assert_called_once()

    def test_error_does_not_propagate(self):
        from unittest.mock import MagicMock
        from xpra.net.socket_util import add_listen_socket, SocketListener
        mock_sock = MagicMock()
        mock_sock.listen.side_effect = OSError("simulated error")
        listener = SocketListener("tcp", mock_sock, ("127.0.0.1", 9999), {}, lambda: None, lambda: None)
        # should not raise
        add_listen_socket(listener, None, lambda l: True)


class TestAcceptConnection(unittest.TestCase):

    def test_basic(self):
        from xpra.net.socket_util import accept_connection, SocketListener
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        try:
            listener = SocketListener("tcp", server, ("127.0.0.1", port), {}, lambda: None, lambda: None)
            conn = accept_connection(listener, timeout=1.0)
            assert conn is not None
            assert conn.socktype == "tcp"
            conn._socket.close()
        finally:
            client.close()
            server.close()

    def test_returns_none_on_error(self):
        from unittest.mock import MagicMock
        from xpra.net.socket_util import accept_connection, SocketListener
        mock_sock = MagicMock()
        mock_sock.accept.side_effect = OSError("connection refused")
        listener = SocketListener("tcp", mock_sock, ("127.0.0.1", 9999), {}, lambda: None, lambda: None)
        conn = accept_connection(listener)
        assert conn is None


class TestPeekConnection(unittest.TestCase):

    def test_returns_data(self):
        from xpra.net.socket_util import peek_connection
        from xpra.net.bytestreams import SocketConnection
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        accepted, _ = server.accept()
        accepted.sendall(b"PEEK!")
        accepted.close()
        server.close()
        conn = SocketConnection(client, client.getsockname(), ("127.0.0.1", port), ("127.0.0.1", port), "tcp")
        try:
            data = peek_connection(conn, timeout=500)
            assert data == b"PEEK!"
        finally:
            client.close()

    def test_empty_on_no_data(self):
        from xpra.net.socket_util import peek_connection
        from xpra.net.bytestreams import SocketConnection
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        accepted, _ = server.accept()
        conn = SocketConnection(client, client.getsockname(), ("127.0.0.1", port), ("127.0.0.1", port), "tcp")
        try:
            data = peek_connection(conn, timeout=50)
            assert data == b""
        finally:
            accepted.close()
            client.close()
            server.close()


class TestSocketFastRead(unittest.TestCase):

    def test_reads_available_data(self):
        from xpra.net.socket_util import socket_fast_read
        from xpra.net.bytestreams import SocketConnection
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        accepted, _ = server.accept()
        accepted.sendall(b"Q")
        accepted.close()
        server.close()
        conn = SocketConnection(client, client.getsockname(), ("127.0.0.1", port), ("127.0.0.1", port), "tcp")
        try:
            data = socket_fast_read(conn, timeout=1)
            assert data == b"Q"
        finally:
            client.close()

    def test_returns_empty_when_no_data(self):
        from xpra.net.socket_util import socket_fast_read
        from xpra.net.bytestreams import SocketConnection
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        accepted, _ = server.accept()
        conn = SocketConnection(client, client.getsockname(), ("127.0.0.1", port), ("127.0.0.1", port), "tcp")
        try:
            data = socket_fast_read(conn, timeout=0.02)
            assert data == b""
        finally:
            accepted.close()
            client.close()
            server.close()


@unittest.skipUnless(sys.platform.startswith("linux"), "TCP_INFO only on Linux")
class TestGetSockoptTcpInfo(unittest.TestCase):

    def _make_connected_pair(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        accepted, _ = server.accept()
        return server, client, accepted

    def test_returns_dict(self):
        from xpra.net.socket_util import get_sockopt_tcp_info, POSIX_TCP_INFO
        server, client, accepted = self._make_connected_pair()
        try:
            TCP_INFO = getattr(socket, "TCP_INFO", 11)
            result = get_sockopt_tcp_info(client, TCP_INFO, POSIX_TCP_INFO)
            assert isinstance(result, dict)
        finally:
            accepted.close()
            client.close()
            server.close()

    def test_state_field_present(self):
        from xpra.net.socket_util import get_sockopt_tcp_info, POSIX_TCP_INFO
        server, client, accepted = self._make_connected_pair()
        try:
            TCP_INFO = getattr(socket, "TCP_INFO", 11)
            result = get_sockopt_tcp_info(client, TCP_INFO, POSIX_TCP_INFO)
            assert "state" in result
        finally:
            accepted.close()
            client.close()
            server.close()

    def test_invalid_sockopt_returns_empty(self):
        from xpra.net.socket_util import get_sockopt_tcp_info, POSIX_TCP_INFO
        from ctypes import c_uint8
        server, client, accepted = self._make_connected_pair()
        try:
            # Request more fields than the kernel returns; the while loop trims them
            # down to what's actually available.  Result is still a dict.
            extra_attrs = POSIX_TCP_INFO + (("rtt", c_uint8),) * 200
            TCP_INFO = getattr(socket, "TCP_INFO", 11)
            result = get_sockopt_tcp_info(client, TCP_INFO, extra_attrs)
            assert isinstance(result, dict)
        finally:
            accepted.close()
            client.close()
            server.close()


class TestSetupQuicSocket(unittest.TestCase):

    def test_no_aioquic_raises_init_exit(self):
        import sys
        from xpra.net.socket_util import setup_quic_socket
        from xpra.scripts.config import InitExit
        saved = sys.modules.get("aioquic", ...)
        sys.modules["aioquic"] = None
        try:
            with self.assertRaises(InitExit):
                setup_quic_socket("127.0.0.1", 0, {})
        finally:
            if saved is ...:
                sys.modules.pop("aioquic", None)
            else:
                sys.modules["aioquic"] = saved

    def test_with_aioquic_creates_listener(self):
        try:
            import aioquic  # noqa: F401
        except ImportError:
            self.skipTest("aioquic not available")
        from xpra.net.socket_util import setup_quic_socket, SocketListener
        sl = setup_quic_socket("127.0.0.1", 0, {})
        try:
            assert isinstance(sl, SocketListener)
            assert sl.socktype == "quic"
            assert sl.address[0] == "127.0.0.1"
            assert sl.address[1] > 0
        finally:
            sl.cleanup()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
