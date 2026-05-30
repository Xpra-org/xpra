# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Session registry reading the same pipe-delimited file the `multifile`
authentication module uses:

    username|password|uid|gid|displays|env_options|session_options

The password column is *not* consulted by the registry; lookup is by
username only. Authentication is performed by whatever authenticator the
socket is configured with; the registry is purely the per-user session
mapping.
"""

import os

from xpra.auth.multifile import parse_auth_line
from xpra.server.session_registry import Session, SessionRegistry
from xpra.log import Logger

log = Logger("auth")


class Registry(SessionRegistry):
    NAME = "multifile"

    def __init__(self, **options):
        super().__init__(**options)
        filename = options.get("filename", "")
        if filename and not os.path.isabs(filename):
            cwd = options.get("exec_cwd") or os.getcwd()
            filename = os.path.join(cwd, filename)
        self.filename: str = filename
        if not filename:
            log.warn("Warning: %r session registry is missing the 'filename' option", self)

    def _load(self) -> dict[str, tuple]:
        if not self.filename or not os.path.exists(self.filename):
            log.error(f"Error: multifile session registry: file {self.filename!r} not found")
            return {}
        out: dict[str, tuple] = {}
        try:
            with open(self.filename, encoding="utf8") as f:
                data = f.read()
        except OSError as e:
            log.error(f"Error reading {self.filename!r}: {e}")
            return {}
        for i, line in enumerate(data.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entry = parse_auth_line(line)
            except Exception as e:
                log(f"parsing error at line {i}", exc_info=True)
                log.error(f"Error: {self.filename!r} line {i}: {e}")
                continue
            out[entry[0]] = entry
        return out

    def lookup(self, authenticator) -> Session | None:
        username = getattr(authenticator, "username", "")
        if not username:
            return None
        entry = self._load().get(username)
        log("%s.lookup(%s) entry=%s", self, username, entry)
        if entry is None:
            return None
        _user, _password, uid, gid, displays, env_options, session_options = entry
        return Session(uid=uid, gid=gid, displays=list(displays),
                       env_options=dict(env_options), session_options=dict(session_options))
