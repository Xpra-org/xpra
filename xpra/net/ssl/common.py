# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from typing import Sequence

from xpra.scripts.config import InitExit

SSL_VERIFY_EXPIRED = 10
SSL_VERIFY_WRONG_HOST = 20
SSL_VERIFY_SELF_SIGNED = 18
SSL_VERIFY_UNTRUSTED_ROOT = 19
SSL_VERIFY_IP_MISMATCH = 64
SSL_VERIFY_HOSTNAME_MISMATCH = 62
SSL_VERIFY_CODES: dict[int, str] = {
    SSL_VERIFY_EXPIRED: "expired",  # also revoked!
    SSL_VERIFY_WRONG_HOST: "wrong host",
    SSL_VERIFY_SELF_SIGNED: "self-signed",
    SSL_VERIFY_UNTRUSTED_ROOT: "untrusted-root",
    SSL_VERIFY_IP_MISMATCH: "ip-mismatch",
    SSL_VERIFY_HOSTNAME_MISMATCH: "hostname-mismatch",
}


class SSLVerifyFailure(InitExit):
    def __init__(self, status, msg, verify_code, ssl_sock):
        super().__init__(status, msg)
        self.verify_code = verify_code
        self.ssl_sock = ssl_sock


KEY_FILENAME = "key.pem"
CERT_FILENAME = "cert.pem"
SSL_CERT_FILENAME = "ssl-cert.pem"
SSL_ATTRIBUTES: Sequence[str] = (
    "cert", "key", "ca-certs", "ca-data",
    "protocol",
    "client-verify-mode", "server-verify-mode", "verify-flags",
    "check-hostname", "server-hostname",
    "options", "ciphers",
)

logger = None


def get_ssl_logger():
    global logger
    if not logger:
        from xpra.log import Logger
        logger = Logger("network", "ssl")
    return logger
