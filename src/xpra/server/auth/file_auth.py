# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing just the password

from xpra.net.digest import verify_digest
from xpra.server.auth.file_auth_base import FileAuthenticatorBase, log
from xpra.util import obsc


class Authenticator(FileAuthenticatorBase):

    def authenticate_hmac(self, challenge_response, client_salt=None) -> bool:
        log("file_auth.authenticate_hmac(%r, %r)", challenge_response, client_salt)
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        salt = self.get_response_salt(client_salt)
        password = self.get_password()
        log("authenticate_hmac() get_password()=%s", obsc(password))
        if not password:
            log.warn("Warning: authentication failed")
            log.warn(" no password for '%s' in '%s'", self.username, self.password_filename)
            return False
        if not verify_digest(self.digest, password, salt, challenge_response):
            log.warn("Warning: %s challenge for '%s' does not match", self.digest, self.username)
            return False
        return True

    def get_password(self) -> str:
        password = FileAuthenticatorBase.get_password(self)
        if not password:
            return password
        if password.find(b"\n")>=0 or password.find(b"\r")>=0:
            log.warn("Warning: newline found in password data")
            log.warn(" this is usually a mistake")
        return password

    def __repr__(self):
        return "password file"
