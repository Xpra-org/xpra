#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest


SAMPLE_CERT = (
    b"-----BEGIN CERTIFICATE-----\n"
    b"MIICpDCCAYwCCQDU+pQ4pHgSpDANBgkqhkiG9w0BAQsFADAUMRIwEAYDVQQDDAls\n"
    b"b2NhbGhvc3QwHhcN...\n"
    b"-----END CERTIFICATE-----\n"
)

SAMPLE_KEY = (
    b"-----BEGIN PRIVATE KEY-----\n"
    b"MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC...\n"
    b"-----END PRIVATE KEY-----\n"
)


class TestStripCert(unittest.TestCase):

    def test_no_markers_unchanged(self):
        from xpra.net.tls.file import strip_cert
        data = b"some raw bytes without cert markers"
        assert strip_cert(data) == data

    def test_strips_leading_junk_before_begin(self):
        from xpra.net.tls.file import strip_cert
        data = b"junk\nstuff\n" + SAMPLE_CERT
        result = strip_cert(data)
        assert result.startswith(b"-----BEGIN CERTIFICATE-----")

    def test_strips_trailing_junk_after_end(self):
        from xpra.net.tls.file import strip_cert
        data = SAMPLE_CERT + b"\ntrailing junk\n"
        result = strip_cert(data)
        assert result.endswith(b"-----END CERTIFICATE-----\n")
        assert b"trailing junk" not in result

    def test_preserves_clean_cert(self):
        from xpra.net.tls.file import strip_cert
        result = strip_cert(SAMPLE_CERT)
        assert b"-----BEGIN CERTIFICATE-----" in result
        assert b"-----END CERTIFICATE-----" in result

    def test_empty_input(self):
        from xpra.net.tls.file import strip_cert
        assert strip_cert(b"") == b""


class TestLoadSslOptions(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        from xpra.net.tls.file import load_ssl_options
        result = load_ssl_options("nonexistent.host.example", 9999)
        assert isinstance(result, dict)
        assert result == {}

    def test_valid_options_file(self):
        from xpra.net.tls.file import load_ssl_options
        # We need a temp dir that the platform considers an ssl config dir.
        # The easiest is to mock get_ssl_hosts_config_dirs.
        with tempfile.TemporaryDirectory() as d:
            hostname = "test.host.example"
            port = 12345
            host_dir = os.path.join(d, f"{hostname}_{port}")
            os.makedirs(host_dir, exist_ok=True)
            options_file = os.path.join(host_dir, "options")
            with open(options_file, "w") as f:
                f.write("check-hostname=true\n")
                f.write("ca-certs=/etc/ssl/certs/ca-certificates.crt\n")

            import xpra.platform.paths as pp
            original = pp.get_ssl_hosts_config_dirs
            pp.get_ssl_hosts_config_dirs = lambda: [d]
            try:
                opts = load_ssl_options(hostname, port)
                assert opts.get("check-hostname") is True
                assert opts.get("ca-certs") == "/etc/ssl/certs/ca-certificates.crt"
            finally:
                pp.get_ssl_hosts_config_dirs = original

    def test_options_file_with_unknown_key(self):
        from xpra.net.tls.file import load_ssl_options
        with tempfile.TemporaryDirectory() as d:
            hostname = "bad.key.test"
            port = 9090
            host_dir = os.path.join(d, f"{hostname}_{port}")
            os.makedirs(host_dir, exist_ok=True)
            with open(os.path.join(host_dir, "options"), "w") as f:
                f.write("unknown-key=value\n")

            import xpra.platform.paths as pp
            original = pp.get_ssl_hosts_config_dirs
            pp.get_ssl_hosts_config_dirs = lambda: [d]
            try:
                opts = load_ssl_options(hostname, port)
                # unknown keys are silently ignored
                assert "unknown-key" not in opts
            finally:
                pp.get_ssl_hosts_config_dirs = original


class TestSaveLoadSslOptions(unittest.TestCase):

    def test_round_trip(self):
        from xpra.net.tls.file import save_ssl_options, load_ssl_options
        with tempfile.TemporaryDirectory() as d:
            hostname = "roundtrip.host.test"
            port = 4430
            host_dir = os.path.join(d, f"{hostname}_{port}")
            os.makedirs(host_dir, exist_ok=True)

            import xpra.platform.paths as pp
            original = pp.get_ssl_hosts_config_dirs
            pp.get_ssl_hosts_config_dirs = lambda: [d]
            try:
                options = {"ca-certs": "/tmp/certs.pem"}
                save_ssl_options(hostname, port, options)
                loaded = load_ssl_options(hostname, port)
                assert loaded.get("ca-certs") == "/tmp/certs.pem", repr(loaded)
            finally:
                pp.get_ssl_hosts_config_dirs = original


class TestGetSslAttributes(unittest.TestCase):

    def test_server_side_flag(self):
        from xpra.net.tls.file import get_ssl_attributes
        attrs = get_ssl_attributes(None, server_side=True)
        assert attrs.get("server-side") is True

    def test_client_side_flag(self):
        from xpra.net.tls.file import get_ssl_attributes
        attrs = get_ssl_attributes(None, server_side=False)
        assert attrs.get("server-side") is False

    def test_overrides_take_precedence(self):
        from xpra.net.tls.file import get_ssl_attributes
        overrides = {"ca-certs": "/custom/ca.pem"}
        attrs = get_ssl_attributes(None, server_side=True, overrides=overrides)
        assert attrs.get("ca-certs") == "/custom/ca.pem"

    def test_opts_object_attributes(self):
        from xpra.net.tls.file import get_ssl_attributes
        from xpra.net.tls.common import SSL_ATTRIBUTES

        class FakeOpts:
            pass

        opts = FakeOpts()
        for attr in SSL_ATTRIBUTES:
            setattr(opts, f"ssl_{attr.replace('-', '_')}", f"value-{attr}")
        attrs = get_ssl_attributes(opts, server_side=False)
        for attr in SSL_ATTRIBUTES:
            assert attrs.get(attr) == f"value-{attr}", f"missing {attr}"

    def test_none_opts(self):
        from xpra.net.tls.file import get_ssl_attributes
        from xpra.net.tls.common import SSL_ATTRIBUTES
        attrs = get_ssl_attributes(None)
        # all SSL_ATTRIBUTES should be present (value may be None)
        for attr in SSL_ATTRIBUTES:
            assert attr in attrs, f"missing attribute {attr!r}"


class TestDoFindSslConfigFile(unittest.TestCase):

    def test_no_dirs_returns_empty(self):
        from xpra.net.tls.file import do_find_ssl_config_file
        import xpra.platform.paths as pp
        original = pp.get_ssl_hosts_config_dirs
        pp.get_ssl_hosts_config_dirs = lambda: []
        try:
            result = do_find_ssl_config_file("example.com", 443, "cert.pem")
            assert result == ""
        finally:
            pp.get_ssl_hosts_config_dirs = original

    def test_finds_existing_file(self):
        from xpra.net.tls.file import do_find_ssl_config_file
        import xpra.platform.paths as pp
        with tempfile.TemporaryDirectory() as d:
            hostname = "myhost.test"
            port = 8443
            host_dir = os.path.join(d, f"{hostname}_{port}")
            os.makedirs(host_dir)
            cert_file = os.path.join(host_dir, "cert.pem")
            with open(cert_file, "wb") as f:
                f.write(SAMPLE_CERT)
            original = pp.get_ssl_hosts_config_dirs
            pp.get_ssl_hosts_config_dirs = lambda: [d]
            try:
                result = do_find_ssl_config_file(hostname, port, "cert.pem")
                assert result == os.path.abspath(cert_file), repr(result)
            finally:
                pp.get_ssl_hosts_config_dirs = original

    def test_returns_empty_for_missing_file(self):
        from xpra.net.tls.file import do_find_ssl_config_file
        import xpra.platform.paths as pp
        with tempfile.TemporaryDirectory() as d:
            original = pp.get_ssl_hosts_config_dirs
            pp.get_ssl_hosts_config_dirs = lambda: [d]
            try:
                result = do_find_ssl_config_file("no.such.host", 9999, "cert.pem")
                assert result == ""
            finally:
                pp.get_ssl_hosts_config_dirs = original


def main():
    unittest.main()


if __name__ == '__main__':
    main()
