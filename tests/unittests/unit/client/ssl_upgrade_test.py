#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.ssl_upgrade import SSLUpgrade, MAX_CERT_DATA_SIZE, MAX_CERTIFICATES
from xpra.exit_codes import ExitCode
from xpra.net.common import Packet
from xpra.net.packet_type import SSL_UPGRADE


def client() -> SSLUpgrade:
    owner = SimpleNamespace(
        idle_add=Mock(), timeout_add=Mock(), source_remove=Mock(), warn_and_quit=Mock(),
    )
    return SSLUpgrade(owner)


class SSLUpgradeTest(unittest.TestCase):

    def test_validated_certificate_starts_upgrade(self) -> None:
        value = client()
        with patch("xpra.net.tls.file.validate_certificates", return_value=b"canonical") as validate, \
                patch("xpra.client.base.ssl_upgrade.start_thread") as start_thread:
            value._process_ssl_upgrade(Packet(SSL_UPGRADE, {"cert-data": b"certificate"}))
        validate.assert_called_once_with(b"certificate", MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
        self.assertEqual(value.server_cert_data, b"canonical")
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


if __name__ == "__main__":
    unittest.main()
