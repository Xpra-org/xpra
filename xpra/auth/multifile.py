# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# authentication from a file containing a list of entries of the form:
# username|password|uid|gid|displays|env_options|session_options

from xpra.auth.common import SessionData, parse_uid, parse_gid
from xpra.auth.file_auth_base import log, FileAuthenticatorBase
from xpra.util.str_fn import hexstr
from xpra.util.parsing import parse_str_dict
from xpra.util.objects import typedict
from xpra.net.digest import verify_digest

AuthLine = tuple[str, str, int, int, list[str], dict[str, str], dict[str, str]]


def parse_auth_line(line: str) -> AuthLine:
    ldata = line.split("|")
    if len(ldata) < 2:
        raise ValueError(f"not enough fields: {len(ldata)}, minimum is 2")
    log(f"found {len(ldata)} fields")
    # parse fields:
    username = ldata[0]
    password = ldata[1]
    if len(ldata) >= 5:
        uid = parse_uid(ldata[2])
        gid = parse_gid(ldata[3])
        displays = ldata[4].split(",")
    else:
        # this will use the default value, usually "nobody":
        uid = parse_uid(None)
        gid = parse_gid(None)
        displays = []
    env_options: dict[str, str] = {}
    session_options: dict[str, str] = {}
    if len(ldata) >= 6:
        env_options = parse_str_dict(ldata[5], ";")
    if len(ldata) >= 7:
        session_options = parse_str_dict(ldata[6], ";")
    return username, password, uid, gid, displays, env_options, session_options


class Authenticator(FileAuthenticatorBase):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sessions: SessionData | None = None

    def parse_filedata(self, data: str) -> dict[str, AuthLine]:
        if not data:
            return {}
        auth_data: dict[str, AuthLine] = {}
        i = 0
        for line in data.splitlines():
            i += 1
            line = line.strip()
            log(f"line {i}: {line!r}")
            if not line or line.startswith("#"):
                continue
            try:
                v = parse_auth_line(line)
                if v:
                    username = v[0]
                    if username in auth_data:
                        log.error(f"Error: duplicate entry for username {username!r} in {self.password_filename!r}")
                    else:
                        auth_data[username] = v
            except Exception as e:
                log("parsing error", exc_info=True)
                log.error(f"Error parsing password file {self.password_filename!r} at line {i}:")
                log.error(f" {line!r}")
                log.estr(e)
                continue
        log(f"parsed auth data from file {self.password_filename!r}: {auth_data}")
        return auth_data

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
