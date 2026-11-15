#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.ssl_upgrade import (
    SSLUpgrade, MAX_CERT_DATA_SIZE, MAX_CERTIFICATES,
    get_ssl_upgrade_options, get_ssl_upgrade_pin, verify_ssl_upgrade_socket,
)
from xpra.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.net.common import Packet
from xpra.net.packet_type import SSL_UPGRADE


def client(options: dict | None = None) -> SSLUpgrade:
    conn = SimpleNamespace(options=options or {
        "host": "example.com",
        "port": 14500,
        "ssl-options": {"server-hostname": "example.com"},
    })
    owner = SimpleNamespace(
        idle_add=Mock(), timeout_add=Mock(), source_remove=Mock(), warn_and_quit=Mock(),
        _protocol=SimpleNamespace(_conn=conn),
    )
    return SSLUpgrade(owner)


class SSLUpgradeTest(unittest.TestCase):

    def test_validated_certificate_starts_upgrade(self) -> None:
        value = client()
        with patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical") as validate, \
                patch("xpra.client.base.ssl_upgrade.get_ssl_upgrade_pin", return_value=b"pin") as get_pin, \
                patch("xpra.client.base.ssl_upgrade.start_thread") as start_thread:
            value._process_ssl_upgrade(Packet(SSL_UPGRADE, {"cert-data": b"certificate"}))
        validate.assert_called_once_with(b"certificate", MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
        get_pin.assert_called_once_with(value.client._protocol._conn, b"canonical")
        self.assertEqual(value.server_cert_data, b"canonical")
        self.assertEqual(value.server_pin_data, b"pin")
        ssl_attrs = start_thread.call_args.kwargs["args"][0]
        self.assertEqual(ssl_attrs["cert-data"], b"canonical")
        value.client.warn_and_quit.assert_not_called()

    def test_invalid_certificate_data_fails_closed(self) -> None:
        for cert_data in (
            None, "certificate", b"", b"x" * (MAX_CERT_DATA_SIZE + 1),
            b"-----BEGIN CERTIFICATE-----\nY2VydA==\n-----END CERTIFICATE-----\n",
        ):
            value = client()
            packet = Packet(SSL_UPGRADE, {} if cert_data is None else {"cert-data": cert_data})
            with self.subTest(cert_data=type(cert_data).__name__), \
                    patch("xpra.client.base.ssl_upgrade.start_thread") as start_thread:
                value._process_ssl_upgrade(packet)
            start_thread.assert_not_called()
            value.client.warn_and_quit.assert_called_once()
            self.assertEqual(value.client.warn_and_quit.call_args.args[0], ExitCode.SSL_FAILURE)

    def test_untrusted_certificate_does_not_start_upgrade(self) -> None:
        for error in ("no certificate has been accepted", "certificate does not match the pin"):
            value = client()
            with self.subTest(error=error), \
                    patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical"), \
                    patch("xpra.client.base.ssl_upgrade.get_ssl_upgrade_pin", side_effect=ValueError(error)), \
                    patch("xpra.client.base.ssl_upgrade.start_thread") as start_thread:
                value._process_ssl_upgrade(Packet(SSL_UPGRADE, {"cert-data": b"certificate"}))
            start_thread.assert_not_called()
            value.client.warn_and_quit.assert_called_once()
            self.assertEqual(value.client.warn_and_quit.call_args.args[0], ExitCode.SSL_FAILURE)

    def test_matching_host_pin(self) -> None:
        conn = SimpleNamespace(options={
            "host": "connection.example.com",
            "port": 14500,
            "ssl-options": {"server-hostname": "certificate.example.com"},
        })
        with patch("xpra.net.tls.file.find_ssl_config_file", return_value="/pin/cert.pem") as find_pin, \
                patch("xpra.util.io.load_binary_file", return_value=b"saved pin") as load_pin, \
                patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical pin") as validate, \
                patch("xpra.net.tls.file.certificate_digest", return_value=b"matching digest"):
            pin_data = get_ssl_upgrade_pin(conn, b"advertised certificate")
        find_pin.assert_called_once_with("certificate.example.com", 14500)
        load_pin.assert_called_once_with("/pin/cert.pem")
        validate.assert_called_once_with(b"saved pin", MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
        self.assertEqual(pin_data, b"canonical pin")

    def test_missing_or_changed_host_pin(self) -> None:
        conn = SimpleNamespace(options={"host": "example.com", "port": 14500})
        with patch("xpra.net.tls.file.find_ssl_config_file", return_value=""):
            with self.assertRaisesRegex(ValueError, "no certificate has been accepted"):
                get_ssl_upgrade_pin(conn, b"advertised certificate")
        with patch("xpra.net.tls.file.find_ssl_config_file", return_value="/pin/cert.pem"), \
                patch("xpra.util.io.load_binary_file", return_value=b"saved pin"), \
                patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical pin"), \
                patch("xpra.net.tls.file.certificate_digest", side_effect=(b"advertised", b"saved")):
            with self.assertRaisesRegex(ValueError, "does not match the pin"):
                get_ssl_upgrade_pin(conn, b"advertised certificate")

    def test_pin_forces_certificate_verification(self) -> None:
        from base64 import b64decode
        options = {"ssl-options": {
            "server-verify-mode": "none",
            "ca-certs": "/untrusted/override.pem",
            "ca-data": "base64:dW50cnVzdGVk",
        }}
        with patch("xpra.net.tls.file.certificate_der", return_value=b"saved pin DER"):
            ssl_options = get_ssl_upgrade_options(options, b"saved pin")
        self.assertEqual(ssl_options["server_verify_mode"], "required")
        self.assertEqual(ssl_options["ca_certs"], "")
        self.assertEqual(b64decode(ssl_options["ca_data"].removeprefix("base64:")), b"saved pin DER")

    def test_peer_certificate_must_equal_pin(self) -> None:
        ssl_sock = Mock()
        ssl_sock.getpeercert.return_value = b"peer DER"
        with patch("xpra.net.tls.file.certificate_der", return_value=b"peer DER"):
            verify_ssl_upgrade_socket(ssl_sock, b"saved pin")
        for peer_certificate in (b"", b"different DER"):
            ssl_sock.getpeercert.return_value = peer_certificate
            with self.subTest(peer_certificate=peer_certificate), \
                    patch("xpra.net.tls.file.certificate_der", return_value=b"peer DER"), \
                    self.assertRaises(InitExit) as cm:
                verify_ssl_upgrade_socket(ssl_sock, b"saved pin")
            self.assertEqual(cm.exception.status, ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE)


if __name__ == "__main__":
    unittest.main()
