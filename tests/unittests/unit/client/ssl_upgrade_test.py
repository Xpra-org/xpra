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
    confirm_ssl_upgrade_pin, get_ssl_upgrade_options, get_ssl_upgrade_pin, verify_ssl_upgrade_socket,
)
from xpra.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.net.common import Packet
from xpra.net.packet_type import SSL_UPGRADE
from xpra.util.objects import typedict


def client(options: dict | None = None) -> SSLUpgrade:
    conn = SimpleNamespace(options=options or {
        "host": "example.com",
        "port": 14500,
        "ssl-options": {"server-hostname": "example.com"},
    })
    owner = SimpleNamespace(
        idle_add=Mock(), timeout_add=Mock(), source_remove=Mock(), warn_and_quit=Mock(),
        cancel_verify_connected_timer=Mock(), send=Mock(), _protocol=SimpleNamespace(_conn=conn),
    )
    return SSLUpgrade(owner)


class SSLUpgradeTest(unittest.TestCase):

    def test_validated_certificate_schedules_upgrade_from_main_thread(self) -> None:
        value = client()
        with patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical") as validate, \
                patch("xpra.client.base.ssl_upgrade.start_thread") as start_thread:
            value._process_ssl_upgrade(Packet(SSL_UPGRADE, {"cert-data": b"certificate"}))
            validate.assert_called_once_with(b"certificate", MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
            self.assertEqual(value.server_cert_data, b"canonical")
            self.assertTrue(value.upgrade_pending)
            value.client.cancel_verify_connected_timer.assert_called_once_with()
            start_thread.assert_not_called()
            value.client.idle_add.assert_called_once()
            callback, ssl_attrs = value.client.idle_add.call_args.args
            self.assertEqual(ssl_attrs["cert-data"], b"canonical")
            callback(ssl_attrs)
            start_thread.assert_called_once_with(value.ssl_upgrade, "ssl-upgrade", True, args=(ssl_attrs,))
        value.client.warn_and_quit.assert_not_called()

    def test_duplicate_upgrade_offer_fails_closed(self) -> None:
        value = client()
        value.upgrade_pending = True
        value._process_ssl_upgrade(Packet(SSL_UPGRADE, {"cert-data": b"certificate"}))
        value.client.idle_add.assert_not_called()
        value.client.warn_and_quit.assert_called_once_with(ExitCode.SSL_FAILURE, "received more than one SSL upgrade offer")

    def test_invalid_certificate_data_fails_closed(self) -> None:
        for cert_data in (
            None, "certificate", b"", b"x" * (MAX_CERT_DATA_SIZE + 1),
            b"-----BEGIN CERTIFICATE-----\nY2VydA==\n-----END CERTIFICATE-----\n",
        ):
            value = client()
            packet = Packet(SSL_UPGRADE, {} if cert_data is None else {"cert-data": cert_data})
            with self.subTest(cert_data=type(cert_data).__name__):
                value._process_ssl_upgrade(packet)
            value.client.idle_add.assert_not_called()
            value.client.warn_and_quit.assert_called_once()
            self.assertEqual(value.client.warn_and_quit.call_args.args[0], ExitCode.SSL_FAILURE)

    def test_rejected_certificate_is_not_acknowledged(self) -> None:
        value = client()
        value.server_cert_data = b"certificate"
        with patch("xpra.client.base.ssl_upgrade.get_ssl_upgrade_pin", side_effect=ValueError("certificate was rejected")) as get_pin:
            value.ssl_upgrade(typedict({"cert-data": b"certificate"}))
        get_pin.assert_called_once_with(value.client._protocol._conn, b"certificate", confirm=True)
        value.client.send.assert_not_called()
        value.client.warn_and_quit.assert_called_once_with(
            ExitCode.SSL_FAILURE, "untrusted SSL upgrade certificate: certificate was rejected")

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

    def test_first_use_confirmation_becomes_pin(self) -> None:
        conn = SimpleNamespace(options={"host": "example.com", "port": 14500})
        with patch("xpra.net.tls.file.find_ssl_config_file", return_value=""), \
                patch("xpra.client.base.ssl_upgrade.confirm_ssl_upgrade_pin", return_value=b"accepted certificate") as confirm:
            pin_data = get_ssl_upgrade_pin(conn, b"advertised certificate", confirm=True)
        confirm.assert_called_once_with("example.com", 14500, b"advertised certificate")
        self.assertEqual(pin_data, b"accepted certificate")

    def test_changed_pin_requires_confirmation(self) -> None:
        conn = SimpleNamespace(options={"host": "example.com", "port": 14500})
        with patch("xpra.net.tls.file.find_ssl_config_file", return_value="/pin/cert.pem"), \
                patch("xpra.util.io.load_binary_file", return_value=b"saved pin"), \
                patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical pin"), \
                patch("xpra.net.tls.file.certificate_digest", side_effect=(b"advertised", b"saved")), \
                patch("xpra.client.base.ssl_upgrade.confirm_ssl_upgrade_pin", return_value=b"accepted certificate") as confirm:
            pin_data = get_ssl_upgrade_pin(conn, b"advertised certificate", confirm=True)
        confirm.assert_called_once_with("example.com", 14500, b"advertised certificate", b"canonical pin")
        self.assertEqual(pin_data, b"accepted certificate")

    def test_confirmation_prompts_and_saves_certificate(self) -> None:
        cases = (
            (b"", "Unverified SSL Upgrade Certificate", "accept and save", ("NEW",)),
            (b"previous pin", "SSL Upgrade Certificate Changed", "replace", ("NEW", "OLD")),
        )
        for previous_pin, expected_title, expected_prompt, fingerprints in cases:
            with self.subTest(previous_pin=bool(previous_pin)), \
                    patch("xpra.net.tls.socket.SSL_RETRY", True), \
                    patch("xpra.net.tls.socket.get_cert_fingerprint", side_effect=fingerprints), \
                    patch("xpra.scripts.pinentry.confirm", return_value=True) as confirm, \
                    patch("xpra.net.tls.file.save_ssl_config_file", return_value="/pin/cert.pem") as save:
                pin_data = confirm_ssl_upgrade_pin("example.com", 14500, b"new pin", previous_pin)
            self.assertEqual(pin_data, b"new pin")
            lines, title, prompt = confirm.call_args.args
            self.assertEqual(title, expected_title)
            self.assertIn(expected_prompt, prompt)
            self.assertTrue(any("example.com:14500" in line for line in lines))
            self.assertTrue(any("NEW" in line for line in lines))
            if previous_pin:
                self.assertTrue(any("OLD" in line for line in lines))
            save.assert_called_once_with("example.com", 14500, "cert.pem", "certificate", b"new pin")

    def test_rejected_or_disabled_confirmation_is_not_saved(self) -> None:
        for ssl_retry, accepted, error in (
            (False, True, "disabled"),
            (True, False, "rejected"),
        ):
            with self.subTest(ssl_retry=ssl_retry, accepted=accepted), \
                    patch("xpra.net.tls.socket.SSL_RETRY", ssl_retry), \
                    patch("xpra.net.tls.socket.get_cert_fingerprint", return_value="NEW"), \
                    patch("xpra.scripts.pinentry.confirm", return_value=accepted), \
                    patch("xpra.net.tls.file.save_ssl_config_file") as save, \
                    self.assertRaisesRegex(ValueError, error):
                confirm_ssl_upgrade_pin("example.com", 14500, b"new pin")
            save.assert_not_called()

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
