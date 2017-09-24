# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing just the password

from xpra.net.crypto import verify_digest
from xpra.server.auth.file_auth_base import FileAuthenticatorBase, init, log


#will be called when we init the module
assert init


class Authenticator(FileAuthenticatorBase):

    def authenticate_hmac(self, challenge_response, client_salt=None):
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        salt = self.get_response_salt(client_salt)
        password = self.get_password()
        if not password:
            log.warn("Warning: authentication failed")
            log.warn(" no password for '%s' in '%s'", self.username, self.password_filename)
            return False
        if not verify_digest(self.digest, password, salt, challenge_response):
            log.warn("Warning: %s challenge for '%s' does not match", self.digest, self.username)
            return False
        return True

    def __repr__(self):
        return "password file"
