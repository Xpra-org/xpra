# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import base64
import binascii
from collections.abc import Sequence

from xpra.util.str_fn import obsc
from xpra.util.env import envbool
from xpra.net.digest import get_salt
from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.log import enable_color

SHOW = envbool("XPRA_OTP_SHOW", False)
SHOW_URI = envbool("XPRA_OTP_SHOW_URI", False)


def b32(s):
    try:
        assert base64.b32decode(s, casefold=True)
        return s
    except binascii.Error:
        return base64.b32encode(s.encode())


class Authenticator(SysAuthenticator):
    # DEFAULT_PROMPT = "OTP for '{username}'"
    DEFAULT_PROMPT = "OTP"

    def __init__(self, **kwargs):
        log("otp.Authenticator(%s)", kwargs)
        self.uid = -1
        self.gid = -1
        import pyotp  # @UnresolvedImport
        assert pyotp
        self.issuer_name = kwargs.pop("issuer-name", "Xpra")
        self.secret = b32(kwargs.pop("secret", pyotp.random_hex()))
        self.valid_window = int(kwargs.pop("valid-window", 0))
        # validate the base32 secret early:
        base64.b32decode(self.secret, casefold=True)
        super().__init__(**kwargs)
        if SHOW_URI:
            totp_uri = pyotp.totp.TOTP(self.secret).provisioning_uri(self.username, issuer_name=self.issuer_name)
            log("provisioning_uri=%s", totp_uri)

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def requires_challenge(self) -> bool:
        return True

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if self.salt is not None:
            log.error("Error: authentication challenge already sent!")
            return b"", ""
        if "xor" not in digests:
            log.error("Error: xor is not supported by the client")
            return b"", ""
        self.salt = get_salt()
        self.digest = "xor"
        self.challenge_sent = True
        if SHOW:
            import pyotp  # @UnresolvedImport
            totp = pyotp.TOTP(self.secret)
            now = totp.now()
            log("otp current value for secret %s: %s", self.secret, now)
            log("recheck: %s", totp.verify(now))
        return self.salt, self.digest

    def check_password(self, password: str) -> bool:
        log("otp.check_password(%s)", obsc(password))
        import pyotp  # @UnresolvedImport
        totp = pyotp.TOTP(self.secret)
        r = totp.verify(password, valid_window=self.valid_window)
        log("otp.check_password(%s)=%s", obsc(password), r)
        if not r:
            raise ValueError("invalid OTP value")
        return True

    def __repr__(self):
        return "otp"


def main(argv) -> int:
    if len(argv) < 2 or len(argv) > 4:
        print(f"usage: {argv[0]} SECRET [username] [issuer-name]")
        return 1
    enable_color()
    import os
    secret = b32(argv[1])
    username = os.environ.get("USERNAME", "")
    issuer_name = "Xpra"
    if len(argv) >= 3:
        username = argv[2]
    if len(argv) >= 4:
        issuer_name = argv[3]
    import pyotp  # @UnresolvedImport
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(username, issuer_name)
    log.info("provisioning_uri=%s", totp_uri)
    # qrcode module has problems - don't use it for now
    try:
        from xpra.gtk.dialogs.qrcode import show_qr
    except ImportError as e:
        log.info(" unable to show qr code: %s", e)
    else:
        show_qr(totp_uri)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
