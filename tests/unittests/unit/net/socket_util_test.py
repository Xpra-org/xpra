#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
