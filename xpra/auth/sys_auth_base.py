# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections import deque
from typing import Deque
from collections.abc import Callable, Sequence

from xpra.common import SocketState
from xpra.platform.info import get_username
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_socket_dirs
from xpra.util.objects import typedict
from xpra.util.str_fn import std, obsc, hexstr
from xpra.util.env import envint
from xpra.scripts.config import TRUE_OPTIONS
from xpra.net.digest import get_salt, choose_digest, verify_digest, gendigest
from xpra.os_util import POSIX, is_admin
from xpra.log import Logger

log = Logger("auth")

USED_SALT_CACHE_SIZE = envint("XPRA_USED_SALT_CACHE_SIZE", 1024 * 1024)
DEFAULT_UID = os.environ.get("XPRA_AUTHENTICATION_DEFAULT_UID", "nobody")
DEFAULT_GID = os.environ.get("XPRA_AUTHENTICATION_DEFAULT_GID", "nobody")

# uid, gid, displays, env_options, session_options
SessionData = tuple[int, int, list[str], dict[str, str], dict[str, str]]


def xor(s1, s2) -> bytes:
    return b"".join(b"%c" % (a ^ b) for a, b in zip(s1, s2))


class SysAuthenticatorBase:
    USED_SALT: Deque[bytes] = deque(maxlen=USED_SALT_CACHE_SIZE)
    DEFAULT_PROMPT = "password for user '{username}'"
    CLIENT_USERNAME = False
    VERIFY_USERNAME = is_admin()

    def __init__(self, **kwargs):
        self.username = kwargs.get("username", get_username())
        remote_props = typedict(kwargs.get("remote", {}))
        remote_username = remote_props.strget("username", "")
        verify_username = str(kwargs.get("verify-username", self.VERIFY_USERNAME)).lower() in TRUE_OPTIONS
        client_username = str(kwargs.get("client-username", self.CLIENT_USERNAME)).lower() in TRUE_OPTIONS
        log(f"{self!r}: {verify_username=}, {client_username=}")
        if client_username:
            # allow the client to specify the username to authenticate with:
            self.username = kwargs.get("remote", {}).get("username", self.username)
            log(f"username={self.username!r}")
        elif verify_username:
            self.verify_username(remote_username)
        self.salt = None
        self.digest = None
        self.salt_digest = None
        prompt_attr = {"username": std(self.username)}
        self.prompt = kwargs.pop("prompt", self.DEFAULT_PROMPT).format(**prompt_attr)
        self.socket_dirs = kwargs.pop("socket-dirs", get_socket_dirs())
        self.challenge_sent = False
        self.passed = False
        self.password_used = None
        self.authenticate_check: Callable[[typedict], bool] = self.default_authenticate_check
        # we can't warn about unused options
        # because the options are shared with other socket options (nodelay, cork, etc)
        # unused = dict((k,v) for k,v in kwargs.items() if k not in ("connection", "exec_cwd", "username"))
        # if unused:
        #    log.warn("Warning: unused keyword arguments for %s authentication:", self)
        #    log.warn(" %s", unused)
        log("auth prompt=%s, socket_dirs=%s", self.prompt, self.socket_dirs)

    def verify_username(self, remote_username: str) -> None:
        if remote_username != self.username:
            log(f"verifying username={self.username!r} vs remote={remote_username!r}")
            raise ValueError(f"invalid username {remote_username!r}")

    def get_uid(self) -> int:
        raise NotImplementedError()

    def get_gid(self) -> int:
        raise NotImplementedError()

    def requires_challenge(self) -> bool:
        return True

    def req_xor(self, digests):
        self.req_challenge(digests, "xor")

    def req_challenge(self, digests, required="xor") -> None:
        if required not in digests:
            raise ValueError(f"{self!r} authenticator requires the {required!r} digest")

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if self.salt is not None:
            log.error("Error: authentication challenge already sent!")
            return b"", ""
        return self.do_get_challenge(digests)

    def do_get_challenge(self, digests) -> tuple[bytes, str]:
        self.salt = get_salt()
        self.digest = choose_digest(digests)
        self.challenge_sent = True
        return self.salt, self.digest

    def get_passwords(self) -> Sequence[str]:
        """ this default implementation just returns a tuple
            with the password from `get_password` if there is one """
        p = self.get_password()  # pylint: disable=assignment-from-none
        if p:
            if not isinstance(p, str):
                raise ValueError(f"password value is not a string: {type(p)}")
            return (p,)
        return ()

    def get_password(self) -> str:
        return ""

    def check(self, value: bytes) -> bool:
        try:
            password = value.decode("utf8")
        except UnicodeDecodeError:
            password = value.decode("latin1")
        return self.check_password(password)

    def check_password(self, password: str) -> bool:
        return password and self.get_password() == password

    def authenticate(self, caps: typedict) -> bool:
        r = self.do_authenticate(caps)
        if r:
            self.passed = True
            log("authentication challenge passed for %s", self)
        return r

    def validate_caps(self, caps: typedict) -> bool:
        if self.passed:
            log("invalid state: challenge has already been passed")
            return False
        if not caps:
            log("invalid state: no capabilities")
            return False
        if not self.challenge_sent:
            log("invalid state: challenge has not been sent yet!")
            return False
        challenge_response = caps.bytesget("challenge_response")
        # challenge has been sent already for this module
        if not challenge_response:
            log("invalid state: challenge already sent but no response found!")
            return False
        return True

    def do_authenticate(self, caps: typedict) -> bool:
        if not self.validate_caps(caps):
            return False
        return self.authenticate_check(caps)

    def choose_salt_digest(self, digest_modes) -> str:
        self.salt_digest = choose_digest(digest_modes)
        return self.salt_digest

    def get_response_salt(self, client_salt=None) -> bytes:
        server_salt = self.salt
        # make sure it does not get re-used:
        self.salt = None
        if client_salt is None:
            return server_salt
        salt = gendigest(self.salt_digest, client_salt, server_salt)
        if salt in SysAuthenticator.USED_SALT:
            raise RuntimeError("danger: an attempt was made to re-use the same computed salt")
        log("combined salt using %r: (%s, %s)=%r", self.salt_digest, hexstr(server_salt), hexstr(client_salt), salt)
        log("salt=%r", salt)
        SysAuthenticator.USED_SALT.append(salt)
        return salt

    def unxor_response(self, caps: typedict) -> bytes:
        challenge_response = caps.bytesget("challenge_response")
        client_salt = caps.strget("challenge_client_salt")
        if self.salt is None:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return b""
        salt = self.get_response_salt(client_salt)
        value = gendigest("xor", challenge_response, salt)
        log(f"unxor_response(..) challenge-response={obsc(repr(challenge_response))}")
        log(f"client-salt={client_salt!r}, response salt={salt!r}")
        return value

    def default_authenticate_check(self, caps: typedict) -> bool:
        value: bytes = self.unxor_response(caps)
        # warning: enabling logging here would log the actual system password!
        # log.info("authenticate(%s, %s) password=%s (%s)",
        #    hexstr(challenge_response), hexstr(client_salt), password, hexstr(password))
        # verify login:
        try:
            ret = self.check(value)
            log(f"authenticate_check(..)={ret}")
        except Exception as e:
            log("check(..)", exc_info=True)
            log.error(f"Error: {self} authentication check failed:")
            log.estr(e)
            return False
        return ret

    def authenticate_hmac(self, caps: typedict) -> bool:
        challenge_response = caps.bytesget("challenge_response")
        client_salt = caps.strget("challenge_client_salt")
        log("sys_auth_base.authenticate_hmac(%r, %r)", challenge_response, client_salt)
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return False
        salt = self.get_response_salt(client_salt)
        passwords = self.get_passwords()
        if not passwords:
            log.warn(f"Warning: {self} authentication failed")
            log.warn(f" no password defined for {self.username!r}")
            return False
        log(f"found {len(passwords)} passwords using {self!r}")
        for x in passwords:
            if verify_digest(self.digest, x, salt, challenge_response):
                self.password_used = x
                return True
        log.warn(f"Warning: {self.digest} challenge for {self.username!r} does not match")
        if len(passwords) > 1:
            log.warn(f" checked {len(passwords)} passwords")
        return False

    def get_sessions(self) -> SessionData:
        uid = self.get_uid()
        gid = self.get_gid()
        log(f"{self}.get_sessions() uid={uid}, gid={gid}")
        try:
            sockdir = DotXpra(None, self.socket_dirs, actual_username=self.username, uid=uid, gid=gid)
            results = sockdir.sockets(check_uid=uid)
            displays = []
            for state, display in results:
                if state == SocketState.LIVE and display not in displays:
                    displays.append(display)
            log(f"sockdir={sockdir}, results={results}, displays={displays}")
        except Exception as e:
            log("get_sessions()", exc_info=True)
            log.error(f"Error: cannot get the list of sessions for {self.username!r}:")
            log.estr(e)
            displays = []
        v: SessionData = (uid, gid, displays, {}, {})
        log(f"{self}.get_sessions()={v}")
        return v


class SysAuthenticator(SysAuthenticatorBase):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pw = None
        if POSIX:
            try:
                import pwd  # pylint: disable=import-outside-toplevel
                self.pw = pwd.getpwnam(self.username)
            except (OSError, KeyError):
                log(f"cannot load password database entry for {self.username!r}", exc_info=True)

    def get_uid(self) -> int:
        if self.pw is None:
            raise RuntimeError(f"username {self.username!r} not found")
        return self.pw.pw_uid

    def get_gid(self) -> int:
        if self.pw is None:
            raise RuntimeError(f"username {self.username!r} not found")
        return self.pw.pw_gid
