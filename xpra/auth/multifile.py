# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# authentication from a file containing a list of entries of the form:
# username|password|uid|gid|displays|env_options|session_options

from xpra.auth.common import SessionData, AuthLine, parse_filedata
from xpra.auth.file_auth_base import log, FileAuthenticatorBase
from xpra.util.str_fn import hexstr
from xpra.util.objects import typedict
from xpra.net.digest import verify_digest


class Authenticator(FileAuthenticatorBase):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sessions: SessionData | None = None

    def parse_filedata(self, data: str) -> dict[str, AuthLine]:
        return parse_filedata(data, self.password_filename, reject_duplicates=True)

    def get_auth_info(self) -> AuthLine | None:
        self.load_password_file()
        if not self.password_filedata:
            return None
        return self.password_filedata.get(self.username)

    def get_password(self) -> str:
        entry = self.get_auth_info()
        log(f"get_password() found entry={entry}")
        if entry is None:
            return ""
        return entry[1]

    def authenticate_hmac(self, caps: typedict) -> bool:
        challenge_response = caps.bytesget("challenge_response")
        client_salt = caps.bytesget("challenge_client_salt")
        log(f"multifile_auth.authenticate_hmac challenge-response={challenge_response!r}, client-salt={client_salt!r}")
        self.sessions = None
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return False
        # ensure this salt does not get re-used:
        salt = self.get_response_salt(client_salt)
        entry = self.get_auth_info()
        if entry is None:
            log.warn("Warning: authentication failed")
            log.warn(f" no password for {self.username!r} in {self.password_filename!r}")
            return False
        log("authenticate: auth-info(%s)=%s", self.username, entry)
        fpassword, uid, gid, displays, env_options, session_options = entry[1:]
        log("multifile authenticate_hmac password='%r', hex(salt)=%s", fpassword, hexstr(salt))
        if not verify_digest(self.digest, fpassword, salt, challenge_response):
            log.warn("Warning: %s challenge for '%s' does not match", self.digest, self.username)
            return False
        self.sessions = uid, gid, displays, env_options, session_options
        return True

    def get_sessions(self) -> SessionData | None:
        return self.sessions

    def __repr__(self):
        return "multi password file"
