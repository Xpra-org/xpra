# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing just the password

import binascii
import os.path
import hmac, hashlib

from xpra.os_util import get_hex_uuid, strtobytes
from xpra.server.auth.sys_auth_base import SysAuthenticator
from xpra.util import xor
from xpra.log import Logger
log = Logger("auth")


password_file = None
def init(opts):
    global password_file
    password_file = opts.password_file


password_data = None
password_file_time = None
def get_password_file_time():
    try:
        return os.stat(password_file).st_mtime
    except Exception as e:
        log.error("error accessing password file time: %s", e)
        return 0
def load_password_file():
    global password_data, password_file_time, password_file
    if not password_file:
        return None
    if not os.path.exists(password_file):
        log.error("Error: password file %s is missing", password_file)
        password_data = None
        return password_data
    ptime = get_password_file_time()
    if password_data is None or ptime!=password_file_time:
        password_file_time = None
        password_data = None
        try:
            with open(password_file, mode='rb') as f:
                password_data = f.read()
            log("loaded %s bytes from %s", len(password_data), password_file)
            password_file_time = ptime
        except Exception as e:
            log.error("error loading %s: %s", password_file, e)
            password_data = None
    return password_data


class Authenticator(SysAuthenticator):
    def __init__(self, username):
        SysAuthenticator.__init__(self, username)
        self.salt = None

    def requires_challenge(self):
        return True

    def get_challenge(self):
        if self.salt is not None:
            log.error("challenge already sent!")
            if self.salt is not False:
                self.salt = False
            return None
        self.salt = get_hex_uuid()+get_hex_uuid()
        #this authenticator can use the safer "hmac" digest:
        return self.salt, "hmac"

    def get_password(self):
        file_data = load_password_file()
        if file_data is None:
            return None
        return strtobytes(file_data)

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
            log.error(" no password for '%s' in %s", self.username, password_file)
            return False
        verify = hmac.HMAC(password, salt, digestmod=hashlib.md5).hexdigest()
        log("authenticate(%s) password=%s, hex(salt)=%s, hash=%s", challenge_response, password, binascii.hexlify(salt), verify)
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
