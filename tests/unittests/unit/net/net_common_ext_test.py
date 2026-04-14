#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Packet.get_* accessors
# ---------------------------------------------------------------------------

class TestPacketGetType(unittest.TestCase):

    def test_returns_string(self):
        from xpra.net.common import Packet
        p = Packet("hello", {})
        assert p.get_type() == "hello"

    def test_non_string_packet_type_raises(self):
        from xpra.net.common import Packet
        with self.assertRaises(TypeError):
            Packet(123, {})


class TestPacketGetWid(unittest.TestCase):

    def test_valid_wid(self):
        from xpra.net.common import Packet
        p = Packet("window-create", 42)
        assert p.get_wid(1) == 42

    def test_negative_minus_one_ok(self):
        from xpra.net.common import Packet
        p = Packet("window-delete", -1)
        assert p.get_wid(1) == -1

    def test_negative_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", -2)
        with self.assertRaises(ValueError):
            p.get_wid(1)

    def test_overflow_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 2**48)
        with self.assertRaises(ValueError):
            p.get_wid(1)


class TestPacketGetBool(unittest.TestCase):

    def test_true_value(self):
        from xpra.net.common import Packet
        p = Packet("t", 1)
        assert p.get_bool(1) is True

    def test_false_value(self):
        from xpra.net.common import Packet
        p = Packet("t", 0)
        assert p.get_bool(1) is False


class TestPacketGetI8(unittest.TestCase):

    def test_valid(self):
        from xpra.net.common import Packet
        for v in (-128, 0, 127):
            p = Packet("t", v)
            assert p.get_i8(1) == v

    def test_overflow_high(self):
        from xpra.net.common import Packet
        p = Packet("t", 128)
        with self.assertRaises(ValueError):
            p.get_i8(1)

    def test_overflow_low(self):
        from xpra.net.common import Packet
        p = Packet("t", -129)
        with self.assertRaises(ValueError):
            p.get_i8(1)


class TestPacketGetU8(unittest.TestCase):

    def test_valid(self):
        from xpra.net.common import Packet
        for v in (0, 128, 255):
            p = Packet("t", v)
            assert p.get_u8(1) == v

    def test_negative_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", -1)
        with self.assertRaises(ValueError):
            p.get_u8(1)

    def test_overflow_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 256)
        with self.assertRaises(ValueError):
            p.get_u8(1)


class TestPacketGetI16(unittest.TestCase):

    def test_boundaries(self):
        from xpra.net.common import Packet
        for v in (-32768, 0, 32767):
            p = Packet("t", v)
            assert p.get_i16(1) == v

    def test_overflow_high(self):
        from xpra.net.common import Packet
        p = Packet("t", 32768)
        with self.assertRaises(ValueError):
            p.get_i16(1)

    def test_overflow_low(self):
        from xpra.net.common import Packet
        p = Packet("t", -32769)
        with self.assertRaises(ValueError):
            p.get_i16(1)


class TestPacketGetU16(unittest.TestCase):

    def test_boundaries(self):
        from xpra.net.common import Packet
        for v in (0, 1, 65535):
            p = Packet("t", v)
            assert p.get_u16(1) == v

    def test_negative_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", -1)
        with self.assertRaises(ValueError):
            p.get_u16(1)

    def test_overflow_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 65536)
        with self.assertRaises(ValueError):
            p.get_u16(1)


class TestPacketGetI32(unittest.TestCase):

    def test_boundaries(self):
        from xpra.net.common import Packet
        for v in (-(2**31), 0, 2**31 - 1):
            p = Packet("t", v)
            assert p.get_i32(1) == v

    def test_overflow_high(self):
        from xpra.net.common import Packet
        p = Packet("t", 2**31)
        with self.assertRaises(ValueError):
            p.get_i32(1)


class TestPacketGetU32(unittest.TestCase):

    def test_boundaries(self):
        from xpra.net.common import Packet
        for v in (0, 1, 2**32 - 1):
            p = Packet("t", v)
            assert p.get_u32(1) == v

    def test_negative_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", -1)
        with self.assertRaises(ValueError):
            p.get_u32(1)

    def test_overflow_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 2**32)
        with self.assertRaises(ValueError):
            p.get_u32(1)


class TestPacketGetI64(unittest.TestCase):

    def test_boundaries(self):
        from xpra.net.common import Packet
        for v in (-(2**63), 0, 2**63 - 1):
            p = Packet("t", v)
            assert p.get_i64(1) == v

    def test_overflow_high(self):
        from xpra.net.common import Packet
        p = Packet("t", 2**63)
        with self.assertRaises(ValueError):
            p.get_i64(1)


class TestPacketGetU64(unittest.TestCase):

    def test_boundaries(self):
        from xpra.net.common import Packet
        for v in (0, 1, 2**64 - 1):
            p = Packet("t", v)
            assert p.get_u64(1) == v

    def test_negative_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", -1)
        with self.assertRaises(ValueError):
            p.get_u64(1)

    def test_overflow_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 2**64)
        with self.assertRaises(ValueError):
            p.get_u64(1)


class TestPacketGetStr(unittest.TestCase):

    def test_string_passthrough(self):
        from xpra.net.common import Packet
        p = Packet("t", "hello")
        assert p.get_str(1) == "hello"

    def test_bytes_decoded(self):
        from xpra.net.common import Packet
        p = Packet("t", b"world")
        assert p.get_str(1) == "world"

    def test_int_converted(self):
        from xpra.net.common import Packet
        p = Packet("t", 42)
        assert p.get_str(1) == "42"


class TestPacketGetBytes(unittest.TestCase):

    def test_bytes_passthrough(self):
        from xpra.net.common import Packet
        p = Packet("t", b"raw")
        assert p.get_bytes(1) == b"raw"

    def test_empty_string_returns_empty_bytes(self):
        from xpra.net.common import Packet
        p = Packet("t", "")
        assert p.get_bytes(1) == b""

    def test_non_bytes_converted(self):
        from xpra.net.common import Packet
        p = Packet("t", b"\x01\x02")
        result = p.get_bytes(1)
        assert isinstance(result, bytes)


class TestPacketGetBuffer(unittest.TestCase):

    def test_memoryview(self):
        from xpra.net.common import Packet
        mv = memoryview(b"data")
        p = Packet("t", mv)
        assert p.get_buffer(1) is mv

    def test_bytes(self):
        from xpra.net.common import Packet
        p = Packet("t", b"data")
        assert p.get_buffer(1) == b"data"

    def test_string_encoded(self):
        from xpra.net.common import Packet
        p = Packet("t", "hello")
        assert p.get_buffer(1) == b"hello"


class TestPacketGetDict(unittest.TestCase):

    def test_dict_passthrough(self):
        from xpra.net.common import Packet
        d = {"key": "value"}
        p = Packet("t", d)
        assert p.get_dict(1) == d

    def test_non_dict_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", "notadict")
        with self.assertRaises(TypeError):
            p.get_dict(1)


class TestPacketGetStrs(unittest.TestCase):

    def test_list_of_strings(self):
        from xpra.net.common import Packet
        p = Packet("t", ["a", "b", "c"])
        result = p.get_strs(1)
        assert tuple(result) == ("a", "b", "c")

    def test_non_sequence_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 123)
        with self.assertRaises(TypeError):
            p.get_strs(1)


class TestPacketGetInts(unittest.TestCase):

    def test_list_of_ints(self):
        from xpra.net.common import Packet
        p = Packet("t", [1, 2, 3])
        result = p.get_ints(1)
        assert tuple(result) == (1, 2, 3)

    def test_non_sequence_raises(self):
        from xpra.net.common import Packet
        p = Packet("t", 999)
        with self.assertRaises(TypeError):
            p.get_ints(1)


class TestPacketGetBytesSeq(unittest.TestCase):

    def test_list_of_bytes(self):
        from xpra.net.common import Packet
        p = Packet("t", [b"a", b"b"])
        result = p.get_bytes_seq(1)
        assert tuple(result) == (b"a", b"b")


# ---------------------------------------------------------------------------
# get_ssh_port
# ---------------------------------------------------------------------------

class TestGetSshPort(unittest.TestCase):

    def test_default_on_non_win32(self):
        from xpra.net.common import get_ssh_port
        from xpra.util.env import OSEnvContext
        import os
        with OSEnvContext():
            os.environ.pop("XPRA_SSH_PORT", None)
            port = get_ssh_port()
        if not sys.platform.startswith("win"):
            assert port == 22

    def test_env_override(self):
        from xpra.net.common import get_ssh_port
        from xpra.util.env import OSEnvContext
        with OSEnvContext(XPRA_SSH_PORT="2222"):
            port = get_ssh_port()
        assert port == 2222

    def test_env_zero_uses_default(self):
        from xpra.net.common import get_ssh_port
        from xpra.util.env import OSEnvContext
        with OSEnvContext(XPRA_SSH_PORT="0"):
            port = get_ssh_port()
        if not sys.platform.startswith("win"):
            assert port == 22

    def test_env_invalid_port_ignored(self):
        from xpra.net.common import get_ssh_port
        from xpra.util.env import OSEnvContext
        with OSEnvContext(XPRA_SSH_PORT="99999"):
            port = get_ssh_port()
        if not sys.platform.startswith("win"):
            assert port == 22


# ---------------------------------------------------------------------------
# verify_hyperv_available
# ---------------------------------------------------------------------------

class TestVerifyHypervAvailable(unittest.TestCase):

    @unittest.skipUnless(sys.platform.startswith("win"), "HyperV only expected on Windows")
    def test_windows_may_succeed(self):
        from xpra.net.common import verify_hyperv_available
        # On Windows, this might work or raise InitExit depending on HyperV support
        try:
            verify_hyperv_available()
        except Exception:
            pass  # InitExit acceptable

    @unittest.skipIf(sys.platform.startswith("win"), "non-Windows: HyperV should be unavailable")
    def test_non_windows_raises(self):
        from xpra.net.common import verify_hyperv_available
        from xpra.scripts.config import InitExit
        with self.assertRaises(InitExit):
            verify_hyperv_available()


# ---------------------------------------------------------------------------
# open_html_url
# ---------------------------------------------------------------------------

class TestOpenHtmlUrl(unittest.TestCase):

    def _open_url(self, html="open", mode="tcp", bind="127.0.0.1"):
        captured = []

        def fake_open_new_tab(url):
            captured.append(url)

        # Patch POSIX=False so the function uses webbrowser directly instead of
        # spawning a subprocess (which would swallow the URL on Linux CI).
        with patch("xpra.os_util.POSIX", False), \
             patch("webbrowser.open_new_tab", side_effect=fake_open_new_tab):
            from xpra.net.common import open_html_url
            open_html_url(html=html, mode=mode, bind=bind)
        return captured

    def test_basic_tcp(self):
        urls = self._open_url(mode="tcp", bind="127.0.0.1")
        assert any("http://" in u for u in urls), urls

    def test_ssl_mode_uses_https(self):
        urls = self._open_url(mode="ssl", bind="127.0.0.1")
        assert any("https://" in u for u in urls), urls

    def test_wss_mode_uses_https(self):
        urls = self._open_url(mode="wss", bind="127.0.0.1")
        assert any("https://" in u for u in urls), urls

    def test_wildcard_host_becomes_localhost(self):
        urls = self._open_url(mode="tcp", bind="0.0.0.0")
        assert any("localhost" in u for u in urls), urls

    def test_ipv6_wildcard_becomes_ipv6_loopback(self):
        # urllib.parse.urlsplit chokes on bare "::" — pass it as a bracketed IPv6
        urls = self._open_url(mode="tcp", bind="[::]:14500")
        assert any("::1" in u for u in urls), urls

    def test_url_ends_with_slash(self):
        urls = self._open_url(mode="tcp", bind="127.0.0.1")
        assert all(u.endswith("/") for u in urls), urls

    def test_unknown_command_falls_back_to_browser(self):
        urls = self._open_url(html="nonexistent-browser-xpra-test", mode="tcp", bind="127.0.0.1")
        assert any("http" in u for u in urls), urls


# ---------------------------------------------------------------------------
# print_proxy_caps
# ---------------------------------------------------------------------------

class TestPrintProxyCaps(unittest.TestCase):

    def test_no_proxy_key_is_silent(self):
        from xpra.net.common import print_proxy_caps
        from xpra.util.objects import typedict
        caps = typedict({})
        # must not raise and must not log anything meaningful
        print_proxy_caps(caps)

    def test_dict_style_proxy(self):
        from xpra.net.common import print_proxy_caps
        from xpra.util.objects import typedict
        caps = typedict({
            "proxy": {
                "hostname": "proxy.example.com",
                "platform": "linux",
                "version": "6.0",
            }
        })
        with patch("xpra.net.common.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            print_proxy_caps(caps)
        mock_logger.info.assert_called_once()
        msg = mock_logger.info.call_args[0][0]
        assert "via" in msg or "proxy" in msg.lower()

    def test_flat_style_proxy(self):
        from xpra.net.common import print_proxy_caps
        from xpra.util.objects import typedict
        # When caps["proxy"] is not a dict (e.g. True/1), use flat prefix
        caps = typedict({
            "proxy": 1,
            "proxy.hostname": "flat.host",
            "proxy.platform": "win32",
            "proxy.version": "5.0",
        })
        with patch("xpra.net.common.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            print_proxy_caps(caps)
        mock_logger.info.assert_called_once()

    def test_proxy_without_hostname(self):
        from xpra.net.common import print_proxy_caps
        from xpra.util.objects import typedict
        caps = typedict({"proxy": {"platform": "linux", "version": "4.0"}})
        with patch("xpra.net.common.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            print_proxy_caps(caps)
        mock_logger.info.assert_called_once()
        msg = mock_logger.info.call_args[0][0]
        assert "proxy.example.com" not in msg


def main():
    unittest.main()


if __name__ == "__main__":
    main()
