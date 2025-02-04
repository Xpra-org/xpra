# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# authentication from a file containing just the password

from xpra.net.digest import verify_digest
from xpra.auth.file_auth_base import FileAuthenticatorBase, log
from xpra.util.objects import typedict
from xpra.util.str_fn import obsc


class Authenticator(FileAuthenticatorBase):

    def authenticate_hmac(self, caps: typedict) -> bool:
        challenge_response = caps.bytesget("challenge_response")
        client_salt = caps.strget("challenge_client_salt")
        log(f"file_auth.authenticate_hmac challenge-response={challenge_response!r}, client-salt={client_salt!r}")
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return False
        salt = self.get_response_salt(client_salt)
        password = self.get_password()
        log("authenticate_hmac(..) get_password()=" + obsc(password))
        if not password:
            log.warn("Warning: authentication failed")
            log.warn(f" no password for {self.username!r} in {self.password_filename!r}")
            return False
        verified = verify_digest(self.digest, password, salt, challenge_response)
        log(f"authenticate_hmac(..) {verified=}")
        if not verified:
            log.warn(f"Warning: {self.digest!r} challenge for {self.username!r} does not match")
        return verified

    def parse_filedata(self, data: str) -> str:
        return data

    def get_password(self) -> str:
        password = super().get_password()
        if not password:
            return password
        if password.find("\n") >= 0 or password.find("\r") >= 0:
            log.warn("Warning: newline found in password data")
            log.warn(" this is usually a mistake")
        return password

    def __repr__(self):
        return "password file"
