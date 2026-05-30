# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Live session registry.

Servers register themselves with the proxy at startup via the `--register`
option. The proxy stores each registration in this in-memory map, keyed by
the registered server's `uuid`. When a client connects to the proxy and
asks for a session, `lookup()` matches by `session-name`, `uuid` or
`display` (configurable via the `lookup-by` option).

This backend is mutable — `register()` / `unregister()` are called from
the proxy server's `register` hello-request handler.
"""

from typing import Optional

from xpra.util.objects import typedict
from xpra.server.session_registry import Session, SessionRegistry
from xpra.log import Logger

log = Logger("auth")

_VALID_LOOKUP_BY = ("session-name", "uuid", "display")


class Registry(SessionRegistry):
    NAME = "live"

    def __init__(self, **options):
        super().__init__(**options)
        lookup_by = options.get("lookup-by") or options.get("lookup_by") or "session-name"
        if lookup_by not in _VALID_LOOKUP_BY:
            raise ValueError(f"live registry: lookup-by must be one of {_VALID_LOOKUP_BY}, got {lookup_by!r}")
        self.lookup_by: str = lookup_by
        self._sessions: dict[str, Session] = {}

    def register(self, session: Session) -> None:
        if not session.uuid:
            raise ValueError("live registry: cannot register a session without a uuid")
        existing = self._sessions.get(session.uuid)
        if existing is not None:
            log.warn("Warning: replacing existing live session %r", session.uuid)
        self._sessions[session.uuid] = session
        log("%s.register(%s); %i session(s) registered", self, session, len(self._sessions))

    def unregister(self, session: Session) -> None:
        removed = self._sessions.pop(session.uuid, None)
        log("%s.unregister(%s) removed=%s; %i remaining",
            self, session, removed is not None, len(self._sessions))

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def lookup(self, authenticator, client_caps: Optional[typedict] = None) -> Session | None:
        if not self._sessions:
            return None
        requested = ""
        if client_caps is not None:
            requested = client_caps.strget("session-name") or client_caps.strget("display") or client_caps.strget("uuid")
        log("%s.lookup(%s) requested=%r among %i session(s)", self, authenticator, requested, len(self._sessions))
        if requested:
            for s in self._sessions.values():
                if self._matches(s, requested):
                    return s
            return None
        # no specific hint: only auto-select if exactly one session is registered
        if len(self._sessions) == 1:
            return next(iter(self._sessions.values()))
        return None

    def _matches(self, session: Session, requested: str) -> bool:
        if self.lookup_by == "uuid":
            return session.uuid == requested
        if self.lookup_by == "display":
            return requested in session.displays
        # session-name (default): match name first, fall back to uuid and display
        # so a client can address the session in whichever way is convenient.
        return session.session_name == requested or session.uuid == requested or requested in session.displays
