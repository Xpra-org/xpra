# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Session registry backed by a DotXpra socket-directory scan.

This is the same logic that lives in `SysAuthenticatorBase.get_sessions()` as
the default for system-based authenticators (pam, ldap, password, ...).
Lifting it into its own registry lets any authenticator — including ones
that do not know about uid/gid — be paired with socket discovery.
"""

from xpra.net.constants import SocketState
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_socket_dirs
from xpra.server.session_registry import Session, SessionRegistry
from xpra.log import Logger

log = Logger("auth")


class Registry(SessionRegistry):
    NAME = "socket"

    def __init__(self, **options):
        super().__init__(**options)
        socket_dirs = options.get("socket-dirs") or options.get("socket_dirs")
        if isinstance(socket_dirs, str):
            socket_dirs = [d for d in socket_dirs.split(":") if d]
        self.socket_dirs: list[str] = socket_dirs or list(get_socket_dirs())

    def lookup(self, authenticator, client_caps=None) -> Session | None:
        username = getattr(authenticator, "username", "")
        try:
            uid = authenticator.get_uid()
            gid = authenticator.get_gid()
        except NotImplementedError:
            log("%s.lookup: authenticator %s does not expose uid/gid", self, authenticator)
            return None
        socket_dirs = self.socket_dirs or list(getattr(authenticator, "socket_dirs", ()) or get_socket_dirs())
        displays: list[str] = []
        try:
            sockdir = DotXpra(None, socket_dirs, actual_username=username, uid=uid, gid=gid)
            for state, display in sockdir.sockets(check_uid=uid):
                if state == SocketState.LIVE and display not in displays:
                    displays.append(display)
        except Exception as e:
            log("%s.lookup: socket scan failed", self, exc_info=True)
            log.error(f"Error: cannot list xpra sessions for {username!r}: {e}")
            return None
        log("%s.lookup(%s) uid=%s gid=%s displays=%s", self, authenticator, uid, gid, displays)
        return Session(uid=uid, gid=gid, displays=displays)
