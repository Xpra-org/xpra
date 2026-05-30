# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Session registry: where the proxy server looks up which xpra sessions are
reachable for an authenticated client.

The default backend (`auth`) delegates to `authenticator.get_sessions()`, which
preserves the historical behaviour where the authentication module was also the
source of truth for session lookup. Other backends decouple the two — for
example the `socket` backend always performs a DotXpra socket scan, regardless
of which authenticator was used.

The `Session` data carrier is iterable as a 5-tuple
`(uid, gid, displays, env_options, session_options)` so existing call sites
that destructure the tuple keep working. Optional fields (`uuid`,
`session_name`, `endpoint`) leave room for a future `live` backend where
xpra servers register themselves with the proxy at startup.
"""

from dataclasses import dataclass, field
from typing import Any

from xpra.auth.common import SessionData


@dataclass
class Session:
    uid: int
    gid: int
    displays: list[str]
    env_options: dict[str, str] = field(default_factory=dict)
    session_options: dict[str, str] = field(default_factory=dict)
    # forward-looking fields used by the "live" backend:
    uuid: str = ""
    session_name: str = ""
    endpoint: Any = None
    # the full server caps from the registration hello, stashed for the
    # phase-3b brokering layer (which adopts the registration connection and
    # therefore must not re-hello with the server):
    server_caps: dict = field(default_factory=dict)

    @classmethod
    def from_tuple(cls, data: SessionData | None) -> "Session | None":
        if data is None:
            return None
        uid, gid, displays, env_options, session_options = data
        return cls(uid, gid, list(displays), dict(env_options), dict(session_options))

    def as_tuple(self) -> SessionData:
        return self.uid, self.gid, self.displays, self.env_options, self.session_options

    # Backwards-compatible tuple destructuring (`uid, gid, ... = session`)
    # and slicing (`session[:2]`) — many callers were written against the
    # 5-tuple SessionData type and we don't want to rewrite all of them.
    def __iter__(self):
        return iter(self.as_tuple())

    def __getitem__(self, idx):
        return self.as_tuple()[idx]

    def __len__(self) -> int:
        return 5


class SessionRegistry:
    """
    Abstract base for session registry backends.

    A backend resolves an authenticated protocol's authenticator into the
    `Session` it should be routed to. Backends are stateless lookups by
    default; the mutation hooks (`register` / `unregister`) exist for the
    future `live` backend where servers announce themselves to the proxy.
    """

    NAME = ""

    def __init__(self, **options):
        # backends may consume options here; unknown options are ignored
        # so that the helper's parse_simple_dict() output is permissive.
        pass

    def lookup(self, authenticator, client_caps=None) -> Session | None:
        """
        Look up the Session this authenticated client should be routed to.

        `client_caps` is the client's hello caps (a `typedict`) or None.
        Most backends ignore it — they identify the user from the
        authenticator alone — but the `live` backend uses it to pick
        which registered server the client wants to reach.
        """
        raise NotImplementedError

    # --- mutation hooks (no-op by default) ---

    def register(self, session: Session) -> None:
        raise NotImplementedError(f"{self.NAME!r} registry does not support registration")

    def unregister(self, session: Session) -> None:
        raise NotImplementedError(f"{self.NAME!r} registry does not support registration")

    def list_sessions(self) -> list[Session]:
        raise NotImplementedError(f"{self.NAME!r} registry does not support enumeration")

    def __repr__(self):
        return f"SessionRegistry({self.NAME!r})"
