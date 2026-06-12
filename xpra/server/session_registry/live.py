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

import threading
from typing import Optional

from xpra.net.common import BACKWARDS_COMPATIBLE
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
        # register()/unregister() are called from the proxy's packet
        # dispatch path; lookup()/list_sessions()/get_info() may be called
        # from get_threaded_info()'s worker thread. Guard every access.
        self._lock = threading.Lock()

    def register(self, session: Session) -> None:
        if not session.uuid:
            raise ValueError("live registry: cannot register a session without a uuid")
        with self._lock:
            existing = self._sessions.get(session.uuid)
            self._sessions[session.uuid] = session
            count = len(self._sessions)
        if existing:
            log.warn("Warning: replacing existing live session %r", session.uuid)
        log("%s.register(%s); %i session(s) registered", self, session, count)

    def unregister(self, session: Session) -> None:
        with self._lock:
            removed = self._sessions.pop(session.uuid, None)
            count = len(self._sessions)
        log("%s.unregister(%s) removed=%s; %i remaining", self, session, removed is not None, count)

    def list_sessions(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def get_info(self) -> dict:
        return {
            "registered": {
                i: {
                    "uuid": s.uuid,
                    "session-name": s.session_name,
                    "displays": list(s.displays),
                }
                for i, s in enumerate(self.list_sessions())
            },
        }

    def lookup(self, authenticator, client_caps: Optional[typedict] = None) -> Session | None:
        sessions = self.list_sessions()
        if not sessions:
            return None
        requested = self._request_hints(client_caps)
        log("%s.lookup(%s) requested=%r among %i session(s)", self, authenticator, requested, len(sessions))
        if requested:
            for hint in requested:
                for s in sessions:
                    if self._matches(s, hint):
                        return s
            # an explicit hint that doesn't match is a miss, not a fallback
            return None
        # no usable hint: auto-select only if there is exactly one
        if len(sessions) == 1:
            return sessions[0]
        return None

    @staticmethod
    def _request_hints(client_caps: Optional[typedict]) -> list[str]:
        """
        Extract the session identifiers the connecting client wants.

        Prefer the new `session` sub-dict sent by XpraClientBase, then
        keep accepting legacy top-level `session-name` and `display`.
        We deliberately do NOT consult the top-level `uuid` cap: clients
        send their own uuid there for tracking, which has nothing to do
        with which registered session they want to reach. We also skip
        the legacy `display` cap when its value is not a plain string:
        the GTK client in backwards-compatible mode overloads it with
        its display-metrics sub-dict rather than the target name.
        """
        hints: list[str] = []

        def add(v: str) -> None:
            if v and v not in hints:
                hints.append(v)

        if client_caps is None:
            return hints
        session = client_caps.dictget("session")
        if session:
            sd = typedict(session)
            for key in ("name", "uuid", "display"):
                add(sd.strget(key))
        add(client_caps.strget("session-name"))
        raw = client_caps.get("display")
        if BACKWARDS_COMPATIBLE and isinstance(raw, str):
            add(str(raw))
        return hints

    def _matches(self, session: Session, requested: str) -> bool:
        if self.lookup_by == "uuid":
            return session.uuid == requested
        if self.lookup_by == "display":
            return requested in session.displays
        # session-name (default): match name first, fall back to uuid and display
        # so a client can address the session in whichever way is convenient.
        return session.session_name == requested or session.uuid == requested or requested in session.displays
