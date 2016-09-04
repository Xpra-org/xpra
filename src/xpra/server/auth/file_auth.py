# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing just the password

import binascii
import hmac, hashlib

from xpra.os_util import strtobytes
from xpra.server.auth.file_auth_base import FileAuthenticatorBase, init, log
from xpra.util import xor, nonl


#will be called when we init the module
assert init


class Authenticator(FileAuthenticatorBase):

    def authenticate(self, challenge_response, client_salt):
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        #ensure this salt does not get re-used:
        if client_salt is None:
            salt = self.salt
        else:
            salt = xor(self.salt, client_salt)
        self.salt = None
        password = self.get_password()
        if not password:
            log.error("Error: authentication failed")
            log.error(" no password for '%s' in '%s'", self.username, self.password_filename)
            return False
        verify = hmac.HMAC(strtobytes(password), strtobytes(salt), digestmod=hashlib.md5).hexdigest()
        log("authenticate(%s) password='%s', hex(salt)=%s, hash=%s", challenge_response, nonl(password), binascii.hexlify(strtobytes(salt)), verify)
        if hasattr(hmac, "compare_digest"):
            eq = hmac.compare_digest(verify, challenge_response)
        else:
            eq = verify==challenge_response
        if not eq:
            log("expected '%s' but got '%s'", verify, challenge_response)
            log.error("Error: hmac password challenge for '%s' does not match", self.username)
            return False
        return True

    def __repr__(self):
        return "password file"
